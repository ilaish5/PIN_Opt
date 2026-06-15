# system/run_specific_wavelength.py
"""Laser-drift / wavelength-stability sweep for ANY recorded sim_id.

Duplicated from wavelength_stability/wavelength_sweep.py and generalized: instead
of hard-coding the Sim-109 optimum, it mirrors run_specific_sim.py's CLI — it asks
for a results CSV path and a sim_id, reads that design's 6 input parameters, then
re-simulates the SAME geometry across a wavelength span centered on the design's
own wavelength (the laser drifts; geometry + drive stay fixed). It records V_pi,
V_pi*L, optical loss and phase shift at each wavelength.

CHARGE (carrier injection) is solved ONCE — carriers do not depend on the optical
wavelength. Only the FDE mode solve repeats per wavelength.

Uses the project's Lumerical files in Lumerical_Files/ directly (same as main.py);
everything it creates lands in results_archive/wavelength_<sim_id>/.

Run on the VM (Lumerical required), from the PS_Opt_V2 directory:
    python system/run_specific_wavelength.py
    python system/run_specific_wavelength.py --sim-id 109 --span 10 --step 1
    python system/run_specific_wavelength.py --force-charge   (re-solve carriers)
"""

import argparse
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))     # .../PS_Opt_V2/system
PROJECT = os.path.dirname(HERE)                        # .../PS_Opt_V2
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config  # noqa: E402

# Lumerical input files: the project's originals, opened in place.
LUM_FILES = os.path.join(PROJECT, "Lumerical_Files")
config.CHARGE_SIM_FILE = os.path.join(LUM_FILES, "PIN_Ref_paper_Charge.ldev")
config.FDE_SIM_FILE = os.path.join(LUM_FILES, "PIN_Ref_phase_shifter.lms")
config.HIDE_GUI = True
# The main pipeline fixes lambda at 1310 nm (config.FIXED_PARAMETERS) and does not
# snap it to a grid, so this script is free to set lambda explicitly per sweep point.

import sim_handler        # noqa: E402
import data_processor     # noqa: E402
import cost as cost_module  # noqa: E402

PARAM_COLS = list(config.SWEEP_PARAMETERS.keys())   # w_r, h_si, doping, S, length
ARCHIVE_DIR = os.path.join(PROJECT, "results_archive")
DEFAULT_CSV = config.RESULTS_CSV_FILE
TOLERANCE = 0.02                                    # anchor pass band vs the record

DEFAULT_SPAN_NM = 10.0      # sweep center ± span  (1310 -> 1300..1320)
DEFAULT_STEP_NM = 1.0

COLUMNS = ['lambda_pm', 'lambda_nm', 'v_pi_V', 'v_pi_l_Vmm',
           'loss_at_v_pi_dB_per_cm', 'max_dphi_rad', 'dphi_fixed_drive_over_pi',
           'is_valid', 'cost', 'neff_re_0V', 'fde_time_s', 'timestamp']

# Plot colors — the presentation's design palette.
C_BLUE, C_PURPLE, C_GOLD, C_GREEN = '#1B3B6F', '#7209B7', '#F4A300', '#52796F'


# ===========================================================================
# CLI / UX  (mirrors run_specific_sim.py)
# ===========================================================================

def ask_results_csv():
    """Prompt for a results-file path (Enter = canonical result.csv)."""
    while True:
        raw = input(f"Path to results CSV [{DEFAULT_CSV}]: ").strip().strip('"')
        path = raw or DEFAULT_CSV
        if os.path.exists(path):
            return path
        print(f"  not found: {path}")


def ask_sim_id(df):
    """Prompt for a sim_id that exists in the loaded file."""
    ids = sorted(df["sim_id"].astype(int).tolist())
    print(f"Available sim_ids: {ids[0]}..{ids[-1]} ({len(ids)} total)")
    while True:
        raw = input("Enter sim_id for the wavelength sweep: ").strip()
        try:
            sim_id = int(raw)
        except ValueError:
            print("  please enter an integer")
            continue
        if sim_id in ids:
            return sim_id
        print(f"  sim_id {sim_id} is not in this file")


def read_params(src, sim_id):
    """Read a sim's 5 input params + its recorded V_pi / V_pi*L / loss (anchor)."""
    df = pd.read_csv(src)
    if "sim_id" not in df.columns:
        sys.exit(f"[ERROR] no 'sim_id' column in {src}")
    df["sim_id"] = df["sim_id"].astype(int)
    if sim_id not in set(df["sim_id"]):
        sys.exit(f"[ERROR] sim_id {sim_id} not in {src}")
    row = df[df["sim_id"] == sim_id].iloc[0]
    missing = [c for c in PARAM_COLS if c not in row or pd.isna(row[c])]
    if missing:
        sys.exit(f"[ERROR] sim_id {sim_id} is missing parameters: {missing}")
    params = {c: float(row[c]) for c in PARAM_COLS}
    return params, row


# ===========================================================================
# Simulation  (CHARGE once, FDE per wavelength — same math as the main pipeline)
# ===========================================================================

def run_charge(params, charge_data_file):
    """Solve carrier injection once for this design's geometry."""
    print("CHARGE: solving carriers for this geometry (~7 min) ...")
    dev = sim_handler.lumapi.DEVICE(hide=True)
    try:
        dev.load(config.CHARGE_SIM_FILE)
        sim_handler.set_charge_parameters(dev, params, charge_data_file)
        sim_handler.run_charge_simulation(dev)
        data = sim_handler.extract_raw_charge_data(dev)
    finally:
        dev.close()
    print(f"CHARGE: done, {len(data['V_drain'])} bias points")


def run_fde(params, lam_nm, charge_data_file):
    """Solve the FDE voltage sweep at one wavelength; return complex neff(V)."""
    lam_m = lam_nm * 1e-9
    fde = sim_handler.lumapi.MODE(hide=True)
    try:
        fde.load(config.FDE_SIM_FILE)
        sim_handler.set_fde_parameters(fde, dict(params, **{'lambda': lam_m}))
        assert abs(float(fde.getnamed("FDE", "wavelength")) - lam_m) < 1e-6 * lam_m
        fde.select("::model::np")
        fde.importdataset(charge_data_file)
        sim_handler.run_fde_sweep(fde)               # save -> mesh -> runsweep
        neff = np.squeeze(fde.getsweepresult("voltage", "neff")['neff'])
    finally:
        fde.close()
    return np.atleast_1d(neff)


def metrics(neff, params, lam_nm, fde_time, fixed_drive_v, raw_dir):
    """Same math as the main pipeline (run_simulation._build_result)."""
    lam_m = lam_nm * 1e-9
    length = params['length']
    d_neff, alpha, d_phi, v_pi, max_dphi = data_processor.process_optical_data(
        neff, length, lam_m)
    V = np.linspace(0, config.V_MAX, len(neff))
    is_valid = not np.isnan(v_pi)

    if is_valid:
        loss_at_v_pi = float(np.interp(v_pi, V, alpha))
        v_pi_l = v_pi * length * 1e3
    else:
        loss_at_v_pi = float(np.max(alpha))
        v_pi_l = config.V_MAX * length * 1e3

    pd.DataFrame({'V': V, 'neff_re': np.real(neff), 'neff_im': np.imag(neff),
                  'd_neff': d_neff, 'alpha_dB_per_cm': alpha, 'd_phi': d_phi}
                 ).to_csv(os.path.join(raw_dir, f"lambda_{lam_nm:.2f}nm.csv"),
                          index=False)

    return {
        'lambda_pm': int(round(lam_nm * 1000)),
        'lambda_nm': round(lam_nm, 2),
        'v_pi_V': v_pi,
        'v_pi_l_Vmm': v_pi_l,
        'loss_at_v_pi_dB_per_cm': loss_at_v_pi,
        'max_dphi_rad': max_dphi,
        'dphi_fixed_drive_over_pi': float(np.interp(fixed_drive_v, V, np.abs(d_phi)) / np.pi),
        'is_valid': is_valid,
        'cost': -cost_module.calculate_cost(alpha=loss_at_v_pi, v_pi_l=v_pi_l,
                                            max_dphi=max_dphi),
        'neff_re_0V': float(np.real(neff[0])),
        'fde_time_s': fde_time,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def make_plots(df, sim_id, anchor_nm, fixed_drive_v, plots_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    df = df.sort_values('lambda_nm')
    lam = df['lambda_nm']
    anchor = df[df['lambda_nm'].round(2) == round(anchor_nm, 2)]

    def style(ax, ylabel, title):
        ax.set_xlabel('Wavelength (nm)')
        ax.set_ylabel(ylabel)
        ax.set_title(title, color=C_BLUE, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.axvline(anchor_nm, color=C_GOLD, linestyle=':', lw=1.2)

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f'Wavelength Stability — sim_id {sim_id} (anchor {anchor_nm:.1f} nm)',
                 fontsize=14, fontweight='bold', color=C_BLUE)

    panels = [
        (axes[0, 0], df['v_pi_l_Vmm'], 'o-', C_BLUE,
         r'$V_\pi L$ (V·mm)', r'Modulation efficiency vs $\lambda$'),
        (axes[0, 1], df['loss_at_v_pi_dB_per_cm'], 's-', C_GREEN,
         r'$\alpha$ at $V_\pi$ (dB/cm)', r'Optical loss vs $\lambda$'),
        (axes[1, 0], df['v_pi_V'], '^-', C_PURPLE,
         r'$V_\pi$ (V)', r'$V_\pi$ vs $\lambda$'),
        (axes[1, 1], df['dphi_fixed_drive_over_pi'], 'd-', C_BLUE,
         rf'$\Delta\varphi({fixed_drive_v:.3f}\,V)/\pi$', 'Fixed-drive phase (no re-bias)'),
    ]
    for ax, series, marker, color, ylabel, title in panels:
        ax.plot(lam, series, marker, color=color, lw=2, ms=5)
        style(ax, ylabel, title)
    axes[1, 1].axhline(1.0, color=C_GOLD, linestyle='--', lw=1.5)
    if len(anchor):
        for ax, col in [(axes[0, 0], 'v_pi_l_Vmm'),
                        (axes[0, 1], 'loss_at_v_pi_dB_per_cm'),
                        (axes[1, 0], 'v_pi_V')]:
            ax.plot(anchor_nm, anchor[col].iloc[0], '*', color=C_GOLD, ms=18, zorder=5)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = os.path.join(plots_dir, 'stability_overview.png')
    fig.savefig(out, dpi=200)
    plt.close(fig)
    print(f"saved {os.path.relpath(out, PROJECT)}")


# ===========================================================================
# main
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--csv', default=None, help='results CSV path')
    ap.add_argument('--sim-id', type=int, default=None)
    ap.add_argument('--span', type=float, default=DEFAULT_SPAN_NM,
                    help='half-width of the sweep around the design wavelength, nm (default 10)')
    ap.add_argument('--step', type=float, default=DEFAULT_STEP_NM,
                    help='wavelength step in nm (default 1)')
    ap.add_argument('--force-charge', action='store_true',
                    help='re-solve carriers even if charge_data.mat exists')
    args = ap.parse_args()

    src = args.csv or ask_results_csv()
    df = pd.read_csv(src)
    df["sim_id"] = df["sim_id"].astype(int)
    sim_id = args.sim_id if args.sim_id is not None else ask_sim_id(df)
    params, row = read_params(src, sim_id)

    # The design wavelength is the sweep center (the laser drifts around it).
    anchor_nm = round(float(config.FIXED_PARAMETERS['lambda']) * 1e9, 2)
    fixed_drive_v = float(row['v_pi_V']) if 'v_pi_V' in row and not pd.isna(row['v_pi_V']) \
        else float('nan')
    anchor_vpil = float(row['v_pi_l_Vmm']) if 'v_pi_l_Vmm' in row and not pd.isna(row['v_pi_l_Vmm']) else None
    anchor_loss = float(row['loss_at_v_pi_dB_per_cm']) if 'loss_at_v_pi_dB_per_cm' in row \
        and not pd.isna(row['loss_at_v_pi_dB_per_cm']) else None

    out_dir = os.path.join(ARCHIVE_DIR, f"wavelength_{sim_id}")
    raw_dir = os.path.join(out_dir, "raw")
    plots_dir = os.path.join(out_dir, "plots")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(plots_dir, exist_ok=True)
    results_csv = os.path.join(out_dir, "stability_results.csv")
    charge_data_file = os.path.join(out_dir, "charge_data.mat")
    config.CHARGE_DATA_FILE = charge_data_file

    print(f"\n=== Wavelength sweep for sim_id {sim_id} (source: {src}) ===")
    for c in PARAM_COLS:
        print(f"  {c:<10} = {params[c]:.6g}")
    print(f"  anchor wavelength = {anchor_nm:.2f} nm   fixed drive V_pi = {fixed_drive_v:.4g} V")
    print(f"Output dir: {out_dir}\n")

    # Build the sweep grid centered on the design wavelength (anchor included).
    n = int(round(args.span / args.step))
    lambdas = sorted({round(anchor_nm + args.step * k, 2) for k in range(-n, n + 1)})

    done = set()
    if os.path.exists(results_csv):
        done = set(pd.read_csv(results_csv)['lambda_nm'].round(2))
    todo = [lam for lam in lambdas if lam not in done]
    print(f"{len(lambdas)} wavelengths ({lambdas[0]:.1f}-{lambdas[-1]:.1f} nm); "
          f"{len(done)} done, {len(todo)} to run")

    if todo and (args.force_charge or not os.path.exists(charge_data_file)):
        run_charge(params, charge_data_file)

    for lam_nm in todo:
        print(f"FDE: lambda = {lam_nm:.1f} nm ...")
        t0 = time.time()
        neff = run_fde(params, lam_nm, charge_data_file)
        r = metrics(neff, params, lam_nm, time.time() - t0, fixed_drive_v, raw_dir)
        pd.DataFrame([r])[COLUMNS].to_csv(
            results_csv, mode='a', header=not os.path.exists(results_csv),
            index=False, float_format='%.6e')
        print(f"  V_pi={r['v_pi_V']:.3f} V  V_pi*L={r['v_pi_l_Vmm']:.4f} V*mm  "
              f"loss={r['loss_at_v_pi_dB_per_cm']:.2f} dB/cm  valid={r['is_valid']}  "
              f"({r['fde_time_s']:.0f}s)")

        # At the design wavelength, confirm the sweep reproduces the record.
        if round(lam_nm, 2) == round(anchor_nm, 2) and anchor_vpil and anchor_loss:
            dv = abs(r['v_pi_l_Vmm'] - anchor_vpil) / anchor_vpil * 100
            da = abs(r['loss_at_v_pi_dB_per_cm'] - anchor_loss) / anchor_loss * 100
            print(f"  anchor check vs record: V_pi*L dev {dv:.2f}%, loss dev {da:.2f}%")
            if max(dv, da) > TOLERANCE * 100:
                print(f"  WARNING: anchor deviates >{TOLERANCE*100:.0f}% from the "
                      f"recorded sim_id {sim_id} — setup may not reproduce it!")

    df_out = pd.read_csv(results_csv).sort_values('lambda_nm')
    make_plots(df_out, sim_id, anchor_nm, fixed_drive_v, plots_dir)

    anchor = df_out[df_out['lambda_nm'].round(2) == round(anchor_nm, 2)]
    if len(anchor):
        a = anchor.iloc[0]
        dv = (df_out['v_pi_l_Vmm'] / a['v_pi_l_Vmm'] - 1) * 100
        da = (df_out['loss_at_v_pi_dB_per_cm'] / a['loss_at_v_pi_dB_per_cm'] - 1) * 100
        print(f"\nSummary over {df_out['lambda_nm'].min():.0f}-{df_out['lambda_nm'].max():.0f} nm "
              f"({len(df_out)} points), sim_id {sim_id}:")
        print(f"  V_pi*L drift vs {anchor_nm:.0f} nm: {dv.min():+.2f}% .. {dv.max():+.2f}%")
        print(f"  loss drift vs {anchor_nm:.0f} nm:   {da.min():+.2f}% .. {da.max():+.2f}%")
        print(f"  all points valid: {bool(df_out['is_valid'].all())}")
    print(f"\nDone. Outputs in {out_dir}")


if __name__ == "__main__":
    main()
