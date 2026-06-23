# system/sim_handler.py
# The only module that touches lumapi. Handles CHARGE + FDE simulations.

import sys
import time
import os
import config
import numpy as np
import pandas as pd

sys.path.append(config.LUMERICAL_API_PATH)
try:
    import lumapi
except ImportError:
    lumapi = None


class SimulationError(Exception):
    def __init__(self, stage, message, original_error=None):
        self.stage = stage
        self.original_error = original_error
        super().__init__(f"[{stage}] {message}")


# ============================================================================
# Stage progress / step-by-step debug
# ============================================================================

def _stage(label):
    """Announce a pipeline stage on the terminal.

    Printing is opt-in and off by default, so main.py's batch runs stay quiet:
    it activates only when a caller sets config.SHOW_PROGRESS = True at runtime
    (e.g. run_specific_sim.py) or when config.DEBUG is on. In DEBUG mode it also
    blocks for Enter, so each step can be inspected before it runs.
    """
    if not (config.DEBUG or getattr(config, "SHOW_PROGRESS", False)):
        return
    print(f"   -> {label}", flush=True)
    if config.DEBUG:
        try:
            input("      [DEBUG] Enter to proceed... ")
        except EOFError:
            pass


# ============================================================================
# Discrete parameter snapping
# ============================================================================

def snap_to_discrete(param_name, value):
    """Snap value(s) to the nearest point of the discrete grid for param_name."""
    if param_name not in config.DISCRETE_PARAMETERS:
        return value
    param_config = config.DISCRETE_PARAMETERS[param_name]
    if not param_config.get('enabled', False):
        return value

    grid = param_config['values']
    is_scalar = np.isscalar(value)
    value_array = np.atleast_1d(value)
    indices = np.searchsorted(grid, value_array)
    snapped = np.zeros_like(value_array)
    for i, (val, idx) in enumerate(zip(value_array, indices)):
        if idx == 0:
            snapped[i] = grid[0]
        elif idx == len(grid):
            snapped[i] = grid[-1]
        else:
            snapped[i] = grid[idx - 1] if abs(val - grid[idx - 1]) <= abs(val - grid[idx]) else grid[idx]
    return float(snapped[0]) if is_scalar else snapped


def snap_params_dict(params_dict):
    return {k: snap_to_discrete(k, v) for k, v in params_dict.items()}


def verify_discrete_compliance(df, param_name):
    """Return (is_compliant, violations) — violations is a list of (index, value)."""
    if param_name not in config.DISCRETE_PARAMETERS:
        return (True, [])
    param_config = config.DISCRETE_PARAMETERS[param_name]
    if not param_config.get('enabled', False) or param_name not in df.columns:
        return (True, [])

    grid = param_config['values']
    tolerance = 1e-12
    violations = [(idx, value) for idx, value in df[param_name].items()
                  if not np.any(np.abs(grid - value) < tolerance)]
    return (len(violations) == 0, violations)


def validate_discrete_config():
    """Raise ValueError if any discrete grid extends outside SWEEP_PARAMETERS bounds."""
    for param_name, param_config in config.DISCRETE_PARAMETERS.items():
        if not param_config.get('enabled', False):
            continue
        if param_name not in config.SWEEP_PARAMETERS:
            raise ValueError(f"Discrete parameter '{param_name}' not in SWEEP_PARAMETERS")
        grid = param_config['values']
        bounds = config.SWEEP_PARAMETERS[param_name]
        if np.any(grid < bounds['min']) or np.any(grid > bounds['max']):
            violating = grid[(grid < bounds['min']) | (grid > bounds['max'])]
            raise ValueError(
                f"Discrete grid for '{param_name}' contains values outside "
                f"[{bounds['min']:.4e}, {bounds['max']:.4e}]: {violating}")


validate_discrete_config()


# ============================================================================
# Lumerical data extraction
# ============================================================================

def extract_raw_charge_data(charge_session):
    charge_data = charge_session.getresult("CHARGE::monitor_charge", "total_charge")
    out = {
        'V_drain': charge_data['V_drain'].flatten(),
        'n': charge_data['n'].flatten(),
        'p': charge_data['p'].flatten(),
    }
    # Terminal current I(V) on the swept 'drain' contact — used to derive the
    # forward-bias differential resistance r_d = dV/dI (-> R_F in the small-signal
    # circuit). Optional: skipped if CHARGE doesn't expose a matching current.
    I = extract_charge_current(charge_session, n_points=len(out['V_drain']))
    if I is not None:
        out['I'] = I
    return out


def extract_charge_current(charge_session, n_points=None):
    """Extract the swept terminal current I(V) from the 'drain' contact.

    'drain' is the biased contact (its voltage 'V_drain' is the sweep). Returns a
    flattened current array aligned to the V sweep, or None if CHARGE didn't
    expose a usable, length-matching 'I' field."""
    try:
        I = np.asarray(charge_session.getresult("CHARGE", "drain")['I']).flatten()
    except Exception:
        print("      WARN: no CHARGE terminal current found — r_d will be unavailable")
        return None
    if n_points is not None and I.size != n_points:
        print("      WARN: CHARGE current length mismatch — r_d will be unavailable")
        return None
    return I


def extract_raw_optical_data(fde_session):
    sweep_result = fde_session.getsweepresult("voltage", "neff")
    return {'neff': np.squeeze(sweep_result['neff'])}


def set_charge_parameters(charge_session, params, charge_file_path):
    """Configure CHARGE geometry and doping. doping is given in cm^-3 and converted to m^-3."""
    w_r = float(params['w_r'])
    h_si = float(params['h_si'])
    S = float(params['S'])
    doping_cm3 = float(params['doping'])
    length = float(params['length'])
    doping = doping_cm3 * 1e6  # cm^-3 → m^-3 for Lumerical
    h_r = float(config.WAFER_THICKNESS - h_si)

    charge_session.switchtolayout()

    # Waveguide
    charge_session.select("::model::geometry::waveguide")
    charge_session.set("x span", w_r)
    charge_session.set("y span", length)
    charge_session.set("z max", h_r + h_si)
    charge_session.set("z min", h_si)

    # Pad (slab)
    charge_session.select("::model::geometry::pad")
    charge_session.set("y span", length)
    charge_session.set("z max", h_si)
    charge_session.set("z min", 0.0)

    # Contacts
    for name in ("::model::geometry::source", "::model::geometry::drain"):
        charge_session.select(name)
        charge_session.set("y span", length)
        charge_session.set("z min", h_si)

    # Buried + surface oxide
    charge_session.select("::model::geometry::buried_oxide")
    charge_session.set("y span", length)
    charge_session.set("z max", 0.0)

    charge_session.select("::model::geometry::surface_oxide")
    charge_session.set("y span", length)
    charge_session.set("z min", 0.0)

    # Background doping
    charge_session.select("::model::CHARGE::doping::pepi")
    charge_session.set("y span", length)

    # Wells — S is offset from rib edge (w_r/2)
    charge_session.select("::model::CHARGE::doping::source_nwell")
    charge_session.set("x min", config.DOPING_X_MIN)
    charge_session.set("x max", -(w_r / 2) - S)
    charge_session.set("concentration", doping)
    charge_session.set("z max", h_si)
    charge_session.set("y span", length)

    charge_session.select("::model::CHARGE::doping::drain_pwell")
    charge_session.set("x min", (w_r / 2) + S)
    charge_session.set("x max", config.DOPING_X_MAX)
    charge_session.set("concentration", doping)
    charge_session.set("z max", h_si)
    charge_session.set("y span", length)

    # Ohmic contacts: nplus/pplus (1e20 cm^-3 = 1e26 m^-3) must stay above wells
    for name in ("::model::CHARGE::doping::nplus", "::model::CHARGE::doping::pplus"):
        charge_session.select(name)
        charge_session.set("concentration", 1e26)
        charge_session.set("z max", h_si)
        charge_session.set("y span", length)

    charge_session.select("::model::CHARGE::monitor_charge")
    charge_session.set("filename", charge_file_path)


def run_charge_simulation(charge_session):
    """Run CHARGE and verify results were produced."""
    charge_session.save(config.CHARGE_SIM_FILE)
    _stage("CHARGE: meshing")
    charge_session.mesh()
    _stage("CHARGE: running solver")
    charge_session.run()

    result = charge_session.getresult("CHARGE::monitor_charge", "total_charge")
    if result is None or 'V_drain' not in result or len(result['V_drain']) == 0:
        raise RuntimeError("CHARGE produced no/empty results")
    if 'n' not in result or 'p' not in result:
        raise RuntimeError("CHARGE results missing carrier data")


def set_fde_parameters(fde_session, params):
    """Configure FDE/MODE geometry and wavelength. Mirrors CHARGE geometry under ::model::."""
    w_r = float(params['w_r'])
    h_si = float(params['h_si'])
    length = float(params['length'])
    wavelength = float(params['lambda'])
    h_r = float(config.WAFER_THICKNESS - h_si)

    fde_session.switchtolayout()
    fde_session.setnamed("FDE", "wavelength", wavelength)

    fde_session.select("::model::waveguide")
    fde_session.set("x span", w_r)
    fde_session.set("y span", length)
    fde_session.set("z max", h_r + h_si)
    fde_session.set("z min", h_si)

    fde_session.select("::model::pad")
    fde_session.set("y span", length)
    fde_session.set("z max", h_si)
    fde_session.set("z min", 0.0)

    for name in ("::model::source", "::model::drain"):
        fde_session.select(name)
        fde_session.set("y span", length)
        fde_session.set("z min", h_si)

    fde_session.select("::model::buried_oxide")
    fde_session.set("y span", length)
    fde_session.set("z max", 0.0)

    fde_session.select("::model::surface_oxide")
    fde_session.set("y span", length)
    fde_session.set("z min", 0.0)


def run_fde_sweep(fde_session):
    """Run FDE voltage sweep and verify results."""
    fde_session.save(config.FDE_SIM_FILE)
    _stage("FDE: meshing")
    fde_session.mesh()
    _stage("FDE: running voltage sweep")
    fde_session.runsweep("voltage")

    result = fde_session.getsweepresult("voltage", "neff")
    if result is None or 'neff' not in result:
        raise RuntimeError("FDE sweep produced no/incomplete results")
    if result['neff'] is None or len(result['neff']) == 0:
        raise RuntimeError("FDE sweep produced empty neff array")


def import_charge_data(fde_session, charge_file_path):
    fde_session.switchtolayout()
    fde_session.select("::model::np")

    charge_filename = os.path.basename(charge_file_path)
    if os.path.exists(charge_file_path):
        fde_session.importdataset(charge_filename)
    elif os.path.exists(charge_filename):
        fde_session.importdataset(charge_filename)
    else:
        raise FileNotFoundError(f"Charge data file not found: {charge_file_path}")


def run_full_simulation(params, sim_id=None):
    """Run CHARGE → FDE pipeline. Returns (raw_df, raw_csv_path, timing)."""
    if lumapi is None:
        raise SimulationError("INIT", "lumapi not available")

    hide_gui = config.HIDE_GUI  # GUI is controlled solely by HIDE_GUI, independent of DEBUG
    charge_data_path = config.CHARGE_DATA_FILE
    result = {}

    charge = None
    try:
        try:
            _stage("CHARGE: opening session")
            charge = lumapi.DEVICE(hide=hide_gui)
            charge.load(config.CHARGE_SIM_FILE)
        except Exception as e:
            raise SimulationError("CHARGE_SETUP", f"open/load CHARGE: {e}", e)

        try:
            _stage("CHARGE: setting geometry & doping")
            set_charge_parameters(charge, params, charge_data_path)
        except Exception as e:
            raise SimulationError("CHARGE_SETUP", f"set CHARGE params: {e}", e)

        charge_time = 0.0
        if config.RUN_SIMULATION:
            try:
                t0 = time.time()
                run_charge_simulation(charge)
                charge_time = time.time() - t0
            except Exception as e:
                raise SimulationError("CHARGE_RUN", f"CHARGE run: {e}", e)

        try:
            _stage("CHARGE: extracting carrier data")
            result.update(extract_raw_charge_data(charge))
            result['charge_time'] = charge_time
        except Exception as e:
            raise SimulationError("CHARGE_EXTRACT", f"extract CHARGE data: {e}", e)
    finally:
        if charge is not None:
            try:
                charge.close()
            except Exception:
                pass

    fde = None
    try:
        try:
            _stage("FDE: opening session")
            fde = lumapi.MODE(hide=hide_gui)
            fde.load(config.FDE_SIM_FILE)
        except Exception as e:
            raise SimulationError("FDE_SETUP", f"open/load FDE: {e}", e)

        try:
            _stage("FDE: setting geometry & wavelength")
            set_fde_parameters(fde, params)
        except Exception as e:
            raise SimulationError("FDE_SETUP", f"set FDE params: {e}", e)

        try:
            _stage("FDE: importing CHARGE data")
            import_charge_data(fde, charge_data_path)
        except Exception as e:
            raise SimulationError("FDE_SETUP", f"import CHARGE→FDE: {e}", e)

        fde_time = 0.0
        if config.RUN_SIMULATION:
            try:
                t0 = time.time()
                run_fde_sweep(fde)
                fde_time = time.time() - t0
            except Exception as e:
                raise SimulationError("FDE_RUN", f"FDE sweep: {e}", e)

        try:
            _stage("FDE: extracting neff")
            result.update(extract_raw_optical_data(fde))
            result['fde_time'] = fde_time
        except Exception as e:
            raise SimulationError("FDE_EXTRACT", f"extract FDE data: {e}", e)
    finally:
        if fde is not None:
            try:
                fde.close()
            except Exception:
                pass

    raw_df = pd.DataFrame({
        'V': result['V_drain'].flatten(),
        'n': result['n'].flatten(),
        'p': result['p'].flatten(),
        'neff_re': np.real(result['neff']).flatten(),
        'neff_im': np.imag(result['neff']).flatten(),
    })
    # Optional terminal current (forward r_d) — only added when CHARGE provided it.
    if 'I' in result and result['I'] is not None and len(result['I']) == len(raw_df):
        raw_df['I'] = np.asarray(result['I']).flatten()

    run_dir = os.path.join(config.RAW_OUTPUT_DIR, f"{config.RUN_TIMESTAMP}_result")
    os.makedirs(run_dir, exist_ok=True)
    raw_csv_path = os.path.join(run_dir, f"{config.RUN_TIMESTAMP}_sim_{sim_id}.csv")
    raw_df.to_csv(raw_csv_path, index=False)

    timing = {'charge_time': result['charge_time'], 'fde_time': result['fde_time']}
    return raw_df, raw_csv_path, timing
