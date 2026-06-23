# system/config.py
# Configuration file for PS_Opt_V2 system
# Contains all global variables, paths, parameters, and constants

import os
import numpy as np

# --- File Paths ---
# Get the base directory (PS_Opt_V2) - two levels up from this file
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Lumerical API paths
LUMERICAL_API_PATH = "C:\\Program Files\\Lumerical\\v251\\api\\python"  # Lumerical Python API path
LUMAPI_PATH = 'lumapi.py'  # Lumerical API module name

# Project file paths (relative to PS_Opt_V2 directory)
LUMERICAL_FILES_DIR = os.path.join(_BASE_DIR, "Lumerical_Files")
FDE_SIM_FILE = os.path.join(LUMERICAL_FILES_DIR, "PIN_Ref_phase_shifter.lms")  # FDE simulation file path
CHARGE_DATA_FILE = os.path.join(LUMERICAL_FILES_DIR, "charge_data.mat")  # CHARGE data file path
CHARGE_SIM_FILE = os.path.join(LUMERICAL_FILES_DIR, "PIN_Ref_paper_Charge.ldev")  # CHARGE simulation file path

# CSV file paths (relative to PS_Opt_V2 directory)
SIMULATION_CSV_DIR = os.path.join(_BASE_DIR, "simulation csv")  # Directory for all CSV files and results
# Input parameters CSV file
# NOTE: The file contains a units row (row 2) that should be skipped when reading.
# Use: pd.read_csv(PARAMS_CSV_FILE, skiprows=[1]) to skip the units row
PARAMS_CSV_FILE = os.path.join(SIMULATION_CSV_DIR, "params.csv")
RESULTS_CSV_FILE = os.path.join(SIMULATION_CSV_DIR, "result.csv")  # Minimal results CSV
RESULTS_FULL_CSV_FILE = os.path.join(SIMULATION_CSV_DIR, "result_full.csv")  # Full results CSV
ERRORS_CSV_FILE = os.path.join(SIMULATION_CSV_DIR, "errors.csv")  # Errors CSV file
RAW_OUTPUT_DIR = os.path.join(SIMULATION_CSV_DIR, "raw")  # Raw per-simulation sweep data
RUN_TIMESTAMP = None  # Set at runtime by main.py

# Columns for minimal result file (essential data only)
MINIMAL_RESULT_COLUMNS = [
    'sim_id',
    'w_r', 'h_si', 'doping', 'S', 'length',  # Input params (5D search space)
    'lambda',                                # Fixed wavelength (recorded constant, not optimized)
    'v_pi_V', 'v_pi_l_Vmm', 'loss_at_v_pi_dB_per_cm', 'C_at_v_pi_pF_per_cm',  # Key outputs
    'max_dphi_rad', 'cost', 'kappa'  # Phase shift, BO metric & kappa
]

# --- Simulation Control Flags ---
HIDE_GUI = True         # Hide Lumerical GUI
DEBUG = False           # Step-by-step analysis mode
SHOW_PLOTS = False      # Display plots after extraction
RUN_SIMULATION = True   # Run actual Lumerical simulations (False = setup only, for testing)
SKIP_LHS = False       # Generate fresh LHS samples (full clean run)
SKIP_INITIAL_SIMS = False  # Run LHS + initial sims, then BO (full clean run)

# --- Cooling Delay ---
DELAY_BETWEEN_RUNS = 0  # seconds between runs (0 = no delay)

# --- LHS Parameters ---
LHS_N_SAMPLES = 50  # Number of LHS samples (N_init = 10d = 50, book §3.3)

LHS_SAMPLING_METHOD = 'optimum'  # 'random', 'maximin', or 'optimum' (smt library)
LHS_RANDOM_SEED = None          # None = random seed

# Optimization/sampling space — 5 parameters (h_r = WAFER_THICKNESS - h_si).
# Wavelength is NOT part of this space; it is fixed at 1310 nm (see FIXED_PARAMETERS).
SWEEP_PARAMETERS = {
    'w_r':     {'min': 350e-9,  'max': 550e-9,  'unit': 'm'},    # Waveguide width (350nm - 550nm)
    'h_si':    {'min': 70e-9,   'max': 130e-9,  'unit': 'm'},    # Silicon height (70nm - 130nm)
    'doping':  {'min': 1e17,    'max': 1e21,    'unit': 'cm^-3'},  # Doping concentration
    'S':       {'min': 0,       'max': 0.8e-6,  'unit': 'm'},    # Junction offset (0nm - 800nm)
    'length':  {'min': 0.1e-3,  'max': 1.0e-3,  'unit': 'm'}     # Device length (0.1mm - 1.0mm)
}

# --- Fixed (non-optimized) Parameters ---
# Constants injected into every simulation but NOT sampled by LHS or optimized by BO.
# The O-band design wavelength is pinned to 1310 nm.
FIXED_PARAMETERS = {
    'lambda': 1310e-9,  # Wavelength (m) — fixed at 1310 nm (O-Band)
}

# --- Discrete Parameter Configuration ---
# Restrict parameters to discrete values (e.g., foundry-specific etching depths)
# Format: parameter_name: {'enabled': bool, 'values': array (sorted, SI units), 'method': 'nearest'}
# Note: Discrete grids must be within corresponding SWEEP_PARAMETERS bounds
DISCRETE_PARAMETERS = {
    'h_si': {
        'enabled': True,  # Set to False to disable discrete snapping for h_si
        'values': np.arange(70e-9, 131e-9, 10e-9),  # [70nm, 80nm, 90nm, ..., 130nm] - within bounds [70nm, 130nm]
        'method': 'nearest'  # Snapping method: 'nearest' (only option currently supported)
    },
    # Add more parameters here as needed (e.g., 'w_r', etc.)
    # Note: 'lambda' is fixed (see FIXED_PARAMETERS), not snapped here.
}


# --- Physical Constants ---
WAFER_THICKNESS = 220e-9  # Standard SOI wafer thickness (m)
ELEMENTARY_CHARGE = 1.60217663e-19  # Elementary charge (C)
V_MAX = 2.5  # Maximum voltage for simulations (V)

# --- Lumerical Template Fixed Values ---
DOPING_X_MIN = -5e-6  # source_nwell x_min (m)
DOPING_X_MAX = 5e-6   # drain_pwell x_max (m)

# --- Bayesian Optimization ---
MAX_ITERATIONS = 100   # BO iterations
BO_KAPPA = 4.0        # UCB kappa (low=exploit, high=explore)
BO_KAPPA_DECAY = 0.98  # Multiply kappa by this each iteration (1.0 = no decay)
# --- Cost Function (Eq. 34; constants Eq. 35-39) ---
FOM_WEIGHTS = {'loss': 0.5, 'vpil': 0.5}  # dB/cm, V*mm
TARGETS = {'loss': 20.0, 'vpil': 0.8}      # Normalization targets

# Piecewise Penalty Constants for failed phase shifts (Eq. 35-39).
# C_BASE is the worst legitimate (Branch A) cost, obtained at the switching
# voltage V_MAX and the maximum allowed optical loss alpha_max (book §3.3.2, Eq. 35).
WORST_CASE_VPIL = V_MAX * (SWEEP_PARAMETERS['length']['max'] * 1e3)  # V_MAX * L_max (V*mm)
ALPHA_MAX = 3.0 * TARGETS['loss']                                    # Hard optical limit (dB/cm)
MAX_VALID_COST = (FOM_WEIGHTS['loss'] * (ALPHA_MAX / TARGETS['loss'])**2
                 + FOM_WEIGHTS['vpil'] * (WORST_CASE_VPIL / TARGETS['vpil'])**2)  # Theoretical worst Branch A cost
C_BASE = MAX_VALID_COST                  # Failed-device baseline (Eq. 35)
BETA_ELEC = (9.0 * C_BASE) / (np.pi**2)  # Quadratic electrical penalty coefficient (Eq. 37)
BETA_OPT  = (9.0 * C_BASE) / ALPHA_MAX   # Linear optical penalty coefficient (Eq. 39)
