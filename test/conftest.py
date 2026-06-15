# test/conftest.py
# Shared fixtures and mocks for pytest

import pytest
import sys
import os
import numpy as np
import pandas as pd
import tempfile
from unittest.mock import MagicMock

# Add system directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'system'))


# ============================================================================
# Sample Data Fixtures
# ============================================================================

@pytest.fixture
def sample_params():
    """Sample parameter dictionary matching SWEEP_PARAMETERS structure."""
    return {
        'w_r': 400e-9,       # 400nm rib width
        'h_si': 100e-9,      # 100nm silicon height
        'doping': 5e17,      # 5e17 cm^-3 doping
        'S': 0.4e-6,         # 400nm spacing
        'lambda': 1310e-9,   # 1310nm wavelength
        'length': 0.5e-3     # 0.5mm device length
    }


@pytest.fixture
def sample_params_bounds():
    """Sample parameter bounds from config (5D search space; lambda is fixed)."""
    return {
        'w_r': {'min': 350e-9, 'max': 500e-9, 'unit': 'm'},
        'h_si': {'min': 70e-9, 'max': 130e-9, 'unit': 'm'},
        'doping': {'min': 1e17, 'max': 1e18, 'unit': 'cm^-3'},
        'S': {'min': 0, 'max': 0.8e-6, 'unit': 'm'},
        'length': {'min': 0.1e-3, 'max': 1.0e-3, 'unit': 'm'}
    }


@pytest.fixture
def sample_voltage_array():
    """Sample voltage array for calculations (0 to 2.5V, 25 points)."""
    return np.linspace(0, 2.5, 25)


@pytest.fixture
def sample_neff_array():
    """
    Sample complex effective index array.
    Real part changes from 2.5 to 2.502 (typical plasma dispersion effect).
    Imaginary part represents optical loss (1e-5 to 5e-5).
    """
    n_points = 25
    real_part = np.linspace(2.5, 2.502, n_points)
    imag_part = np.linspace(1e-5, 5e-5, n_points)
    return real_part + 1j * imag_part


@pytest.fixture
def sample_neff_reaches_pi():
    """
    Sample neff array that will reach pi phase shift.
    Larger real part change to ensure phase shift exceeds pi.
    """
    n_points = 25
    # With length=0.5mm and wavelength=1310nm, need dneff ~ 1.3e-3 for pi shift
    real_part = np.linspace(2.5, 2.503, n_points)
    imag_part = np.linspace(1e-5, 3e-5, n_points)
    return real_part + 1j * imag_part


@pytest.fixture
def sample_neff_no_pi():
    """
    Sample neff array that will NOT reach pi phase shift.
    Small real part change.
    """
    n_points = 25
    real_part = np.linspace(2.5, 2.5005, n_points)  # Very small change
    imag_part = np.linspace(1e-5, 2e-5, n_points)
    return real_part + 1j * imag_part


@pytest.fixture
def sample_results_df():
    """Sample results DataFrame for BO tests."""
    return pd.DataFrame([
        {
            'sim_id': 1,
            'w_r': 400e-9, 'h_si': 100e-9, 'doping': 5e17,
            'S': 0.4e-6, 'lambda': 1310e-9, 'length': 0.5e-3,
            'v_pi_V': 1.5, 'v_pi_l_Vmm': 0.75, 'loss_at_v_pi_dB_per_cm': 1.8,
            'max_dphi_rad': np.pi + 0.2, 'cost': -1.5
        },
        {
            'sim_id': 2,
            'w_r': 450e-9, 'h_si': 110e-9, 'doping': 6e17,
            'S': 0.5e-6, 'lambda': 1310e-9, 'length': 0.6e-3,
            'v_pi_V': np.nan, 'v_pi_l_Vmm': 1.5, 'loss_at_v_pi_dB_per_cm': 2.0,
            'max_dphi_rad': 2.5, 'cost': 1.35
        },
        {
            'sim_id': 3,
            'w_r': 380e-9, 'h_si': 90e-9, 'doping': 4e17,
            'S': 0.3e-6, 'lambda': 1310e-9, 'length': 0.4e-3,
            'v_pi_V': 2.0, 'v_pi_l_Vmm': 0.8, 'loss_at_v_pi_dB_per_cm': 1.5,
            'max_dphi_rad': np.pi + 0.1, 'cost': -1.2
        }
    ])


# ============================================================================
# Temporary File Fixtures
# ============================================================================

@pytest.fixture
def temp_csv_dir(tmp_path):
    """Create a temporary directory for CSV files."""
    csv_dir = tmp_path / "simulation csv"
    csv_dir.mkdir()
    return csv_dir


@pytest.fixture
def temp_results_csv(temp_csv_dir, sample_results_df):
    """Create a temporary results CSV file."""
    filepath = temp_csv_dir / "result.csv"
    sample_results_df.to_csv(filepath, index=False)
    return str(filepath)


@pytest.fixture
def temp_params_csv(temp_csv_dir, sample_params):
    """Create a temporary params CSV file."""
    filepath = temp_csv_dir / "params.csv"

    # Create units row
    units = {'sim_id': '-', 'w_r': 'm', 'h_si': 'm', 'doping': 'cm^-3',
             'S': 'm', 'lambda': 'm', 'length': 'm'}

    # Create data rows
    data = [{'sim_id': 1, **sample_params}]

    df = pd.DataFrame([units] + data)
    df.to_csv(filepath, index=False)
    return str(filepath)


# ============================================================================
# Mock Lumerical Fixtures
# ============================================================================

@pytest.fixture
def mock_lumapi():
    """Mock lumapi module."""
    mock = MagicMock()

    # Mock DEVICE class
    mock.DEVICE.return_value = MagicMock()
    mock.DEVICE.return_value.close = MagicMock()

    # Mock MODE class
    mock.MODE.return_value = MagicMock()
    mock.MODE.return_value.close = MagicMock()

    return mock


@pytest.fixture
def mock_charge_session(sample_voltage_array):
    """Mock Lumerical CHARGE session with sample data."""
    session = MagicMock()

    # Mock charge data result
    n_points = len(sample_voltage_array)
    charge_data = {
        'V_drain': sample_voltage_array.reshape(-1, 1),
        'n': np.linspace(1e10, 1e12, n_points).reshape(-1, 1),  # electrons
        'p': np.linspace(1e10, 1e12, n_points).reshape(-1, 1),  # holes
    }
    session.getresult.return_value = charge_data

    return session


@pytest.fixture
def mock_fde_session(sample_neff_reaches_pi):
    """Mock Lumerical FDE/MODE session with sample data."""
    session = MagicMock()

    # Mock sweep result
    sweep_result = {
        'neff': sample_neff_reaches_pi.reshape(-1, 1)
    }
    session.getsweepresult.return_value = sweep_result

    return session


# ============================================================================
# Config Override Fixtures
# ============================================================================

@pytest.fixture
def mock_config(temp_csv_dir, monkeypatch):
    """Override config values for testing."""
    import config as cfg

    monkeypatch.setattr(cfg, 'SIMULATION_CSV_DIR', str(temp_csv_dir))
    monkeypatch.setattr(cfg, 'PARAMS_CSV_FILE', str(temp_csv_dir / "params.csv"))
    monkeypatch.setattr(cfg, 'RESULTS_CSV_FILE', str(temp_csv_dir / "result.csv"))
    monkeypatch.setattr(cfg, 'RESULTS_FULL_CSV_FILE', str(temp_csv_dir / "result_full.csv"))
    monkeypatch.setattr(cfg, 'ERRORS_CSV_FILE', str(temp_csv_dir / "errors.csv"))
    monkeypatch.setattr(cfg, 'DEBUG', False)
    monkeypatch.setattr(cfg, 'SHOW_PLOTS', False)

    return cfg
