# system/run_simulation.py
# Orchestrates a single simulation row (CHARGE → FDE → processing → cost → CSV).

import os
import time
import traceback
import json
from datetime import datetime
import pandas as pd
import numpy as np

import config
import cost as cost_module
import sim_handler
import data_processor


def debug_prompt(message):
    if not config.DEBUG:
        return True
    return input(f"[DEBUG] {message} — Enter to continue, 's' skip: ").strip().lower() != 's'


def cooling_delay(skip=False):
    if skip or config.DELAY_BETWEEN_RUNS <= 0:
        return
    time.sleep(config.DELAY_BETWEEN_RUNS)


def _save_to_csv(filename, result_df, columns=None):
    if columns is not None:
        df_to_save = result_df[[c for c in columns if c in result_df.columns]].copy()
    else:
        df_to_save = result_df.copy()

    if not os.path.exists(filename):
        df_to_save.to_csv(filename, index=False, mode='w', float_format='%.6e')
        return

    try:
        existing_header = pd.read_csv(filename, nrows=0).columns.tolist()
        for col in existing_header:
            if col not in df_to_save.columns:
                df_to_save[col] = np.nan
        df_to_save = df_to_save[existing_header]
    except Exception:
        pass
    df_to_save.to_csv(filename, index=False, mode='a', header=False, float_format='%.6e')


def save_single_result_to_csv(filename, current_result):
    result_df = pd.DataFrame([current_result])
    input_params = list(config.SWEEP_PARAMETERS.keys())
    output_metrics = [c for c in result_df.columns if c not in input_params and c != 'sim_id']
    column_order = ['sim_id'] + input_params + output_metrics
    if all(c in result_df.columns for c in column_order):
        result_df = result_df[column_order]

    _save_to_csv(filename, result_df, columns=config.MINIMAL_RESULT_COLUMNS)
    _save_to_csv(config.RESULTS_FULL_CSV_FILE, result_df)


def save_error_to_csv(sim_id, stage, error, params=None):
    error_record = {
        'sim_id': sim_id,
        'stage': stage,
        'error_type': type(error).__name__,
        'error_message': str(error),
        'traceback': ''.join(traceback.format_exception(type(error), error, error.__traceback__)),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'params': json.dumps(params) if params else ''
    }
    error_df = pd.DataFrame([error_record])
    file_exists = os.path.exists(config.ERRORS_CSV_FILE)
    error_df.to_csv(config.ERRORS_CSV_FILE, index=False,
                    mode='a' if file_exists else 'w',
                    header=not file_exists)


def run_init_file(params_csv_path=None, logger_func=None):
    if params_csv_path is None:
        params_csv_path = config.PARAMS_CSV_FILE

    params_df = pd.read_csv(params_csv_path, skiprows=[1])
    log = logger_func or (lambda m: None)
    log(f"Initial sims: {len(params_df)} parameter sets")

    completed_ids = set()
    if os.path.exists(config.RESULTS_CSV_FILE):
        existing_df = pd.read_csv(config.RESULTS_CSV_FILE)
        completed_ids = set(existing_df['sim_id'].astype(int).tolist())
        if completed_ids:
            log(f"Resuming: {len(completed_ids)} sims already in result.csv")

    total = len(params_df)
    successful = failed = skipped = 0

    for idx, row in params_df.iterrows():
        sim_id = int(row['sim_id'])
        is_last = (idx == total - 1)

        if sim_id in completed_ids:
            skipped += 1
            continue

        if not debug_prompt(f"Run sim {sim_id}"):
            continue

        try:
            result = run_row(row, sim_id=sim_id, is_last=is_last)
            if result is None:
                failed += 1
                log(f"[{sim_id}/{total}] FAILED")
            else:
                successful += 1
                v_pi = result.get('v_pi_V', float('nan'))
                if not np.isnan(v_pi):
                    log(f"[{sim_id}/{total}] V_pi={v_pi:.2f}V, "
                        f"V_pi*L={result.get('v_pi_l_Vmm', 0):.3f}, "
                        f"loss={result.get('loss_at_v_pi_dB_per_cm', 0):.2f} dB/cm, "
                        f"cost={result.get('cost', 0):.3f}")
                else:
                    log(f"[{sim_id}/{total}] INVALID max_dphi={result.get('max_dphi_rad', 0):.2f}, "
                        f"cost={result.get('cost', 0):.3f}")
        except Exception as e:
            failed += 1
            log(f"[{sim_id}/{total}] ERROR: {e}")

    log(f"Initial sims complete: {successful}/{total} ok, {failed} failed, {skipped} resumed")
    return config.RESULTS_CSV_FILE


def run_row(row, sim_id=None, is_last=False):
    params = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    if sim_id is None:
        sim_id = int(params.get('sim_id', 0))

    # Inject fixed (non-optimized) parameters, e.g. lambda=1310nm, so downstream
    # consumers (FDE setup, optical processing, result record) always receive them.
    for name, value in config.FIXED_PARAMETERS.items():
        params.setdefault(name, value)

    params = sim_handler.snap_params_dict(params)
    sim_start_time = time.time()

    try:
        raw_df, raw_csv_path, timing = sim_handler.run_full_simulation(params, sim_id=sim_id)
    except sim_handler.SimulationError as e:
        save_error_to_csv(sim_id, e.stage, e.original_error or e, params)
        return None

    try:
        V_cap, C_total_pF_cm = data_processor.process_charge_data(
            raw_df['V'].values, raw_df['n'].values, raw_df['p'].values)
        neff = raw_df['neff_re'].values + 1j * raw_df['neff_im'].values
        d_neff, alpha_dB_per_cm, d_phi, v_pi, max_dphi = data_processor.process_optical_data(
            neff, float(params['length']), float(params['lambda']))
    except Exception as e:
        save_error_to_csv(sim_id, "DATA_PROCESSING", e, params)
        return None

    raw_df['d_neff'] = d_neff
    raw_df['d_phi'] = d_phi
    raw_df['C_total_pF_cm'] = C_total_pF_cm
    raw_df.to_csv(raw_csv_path, index=False)

    try:
        result = _build_result(
            sim_id, params, timing, V_cap, C_total_pF_cm,
            d_neff, alpha_dB_per_cm, d_phi, v_pi, max_dphi,
            time.time() - sim_start_time)
    except Exception as e:
        save_error_to_csv(sim_id, "RESULTS_CALC", e, params)
        return None

    if debug_prompt("Save result to CSV"):
        save_single_result_to_csv(config.RESULTS_CSV_FILE, result)

    cooling_delay(skip=is_last)
    return result


def _build_result(sim_id, params, timing, V_cap, C_total_pF_cm,
                  d_neff, alpha_dB_per_cm, d_phi, v_pi, max_dphi, total_time):
    V_fde = np.linspace(0, config.V_MAX, len(d_neff))
    w_r = float(params['w_r'])
    S = float(params['S'])
    is_valid = not np.isnan(v_pi)

    if is_valid:
        loss_at_v_pi = np.interp(v_pi, V_fde, alpha_dB_per_cm)
        C_at_v_pi = np.interp(v_pi, V_cap, C_total_pF_cm)
        v_pi_l = v_pi * float(params['length']) * 1e3
    else:
        loss_at_v_pi = np.max(alpha_dB_per_cm)
        C_at_v_pi = np.nan
        v_pi_l = config.V_MAX * float(params['length']) * 1e3

    neg_cost = cost_module.calculate_cost(alpha=loss_at_v_pi, v_pi_l=v_pi_l, max_dphi=max_dphi)
    cost_value = -neg_cost

    return {
        'sim_id': sim_id,
        **params,
        'v_pi_V': v_pi,
        'v_pi_l_Vmm': v_pi_l,
        'loss_at_v_pi_dB_per_cm': loss_at_v_pi,
        'C_at_v_pi_pF_per_cm': C_at_v_pi,
        'max_dphi_rad': max_dphi,
        'is_valid': is_valid,
        'norm_loss': loss_at_v_pi / config.TARGETS['loss'],
        'norm_vpil': v_pi_l / config.TARGETS['vpil'],
        'cost': cost_value,
        'charge_time_s': timing.get('charge_time', 0),
        'fde_time_s': timing.get('fde_time', 0),
        'total_time_s': total_time,
        'intrinsic_width_m': w_r + 2 * S,
        'loss_min_dB_per_cm': np.min(alpha_dB_per_cm),
        'loss_max_dB_per_cm': np.max(alpha_dB_per_cm),
        'C_min_pF_per_cm': np.min(C_total_pF_cm),
        'C_max_pF_per_cm': np.max(C_total_pF_cm),
    }
