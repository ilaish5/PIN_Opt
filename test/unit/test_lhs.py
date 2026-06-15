# test/unit/test_lhs.py
# Unit tests for LHS.py - Latin Hypercube Sampling

import pytest
import numpy as np
import pandas as pd
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'system'))


# ============================================================================
# LHS Sample Generation Tests
# ============================================================================

class TestGenerateLhsSamples:
    """Tests for generate_lhs_samples() function."""

    @pytest.mark.unit
    def test_correct_number_of_samples(self, mock_config, monkeypatch):
        """Test that correct number of samples is generated."""
        from LHS import generate_lhs_samples

        # Set number of samples
        monkeypatch.setattr('config.LHS_N_SAMPLES', 10)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=1)

        assert len(df) == 10, "Should generate exactly 10 samples"

    @pytest.mark.unit
    def test_correct_columns(self, mock_config, monkeypatch):
        """Test that DataFrame has correct columns."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 5)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=1)

        expected_cols = ['sim_id', 'w_r', 'h_si', 'doping', 'S', 'length']
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

    @pytest.mark.unit
    def test_values_within_bounds(self, mock_config, monkeypatch):
        """Test that all generated values are within bounds."""
        from LHS import generate_lhs_samples
        import config

        monkeypatch.setattr('config.LHS_N_SAMPLES', 20)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=1)

        for param_name, bounds in config.SWEEP_PARAMETERS.items():
            min_val = bounds['min']
            max_val = bounds['max']

            assert df[param_name].min() >= min_val, \
                f"{param_name} has value below minimum"
            assert df[param_name].max() <= max_val, \
                f"{param_name} has value above maximum"

    @pytest.mark.unit
    def test_sim_id_sequence(self, mock_config, monkeypatch):
        """Test that sim_ids are sequential starting from start_sim_id."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 5)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=10)

        expected_ids = list(range(10, 15))
        assert list(df['sim_id']) == expected_ids

    @pytest.mark.unit
    def test_reproducibility_with_seed(self, mock_config, monkeypatch):
        """Test that same seed produces same samples."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 5)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 123)

        df1 = generate_lhs_samples(start_sim_id=1)

        # Reset and generate again with same seed
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 123)
        df2 = generate_lhs_samples(start_sim_id=1)

        # Compare parameter columns (not sim_id since that might differ)
        param_cols = ['w_r', 'h_si', 'doping', 'S', 'length']
        for col in param_cols:
            assert np.allclose(df1[col].values, df2[col].values), \
                f"Column {col} should be reproducible with same seed"

    @pytest.mark.unit
    def test_csv_file_created(self, mock_config, monkeypatch):
        """Test that CSV file is created."""
        from LHS import generate_lhs_samples
        import config

        monkeypatch.setattr('config.LHS_N_SAMPLES', 3)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=1)

        assert os.path.exists(config.PARAMS_CSV_FILE), "CSV file should be created"

    @pytest.mark.unit
    def test_csv_has_units_row(self, mock_config, monkeypatch):
        """Test that CSV file contains units row."""
        from LHS import generate_lhs_samples
        import config

        monkeypatch.setattr('config.LHS_N_SAMPLES', 3)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        generate_lhs_samples(start_sim_id=1)

        # Read CSV without skipping units row
        df_raw = pd.read_csv(config.PARAMS_CSV_FILE)

        # First row should be units (sim_id should be '-')
        assert df_raw.iloc[0]['sim_id'] == '-', "First row should be units row"

    @pytest.mark.unit
    def test_different_seeds_different_samples(self, mock_config, monkeypatch):
        """Test that different seeds produce different samples."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 5)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')

        monkeypatch.setattr('config.LHS_RANDOM_SEED', 111)
        df1 = generate_lhs_samples(start_sim_id=1)

        monkeypatch.setattr('config.LHS_RANDOM_SEED', 222)
        df2 = generate_lhs_samples(start_sim_id=1)

        # At least one parameter should be different
        param_cols = ['w_r', 'h_si', 'doping', 'S', 'length']
        all_same = all(np.allclose(df1[col].values, df2[col].values)
                       for col in param_cols)
        assert not all_same, "Different seeds should produce different samples"


# ============================================================================
# LHS Properties Tests
# ============================================================================

class TestLhsProperties:
    """Tests for LHS statistical properties."""

    @pytest.mark.unit
    def test_space_filling(self, mock_config, monkeypatch):
        """Test that LHS provides good space-filling properties."""
        from LHS import generate_lhs_samples

        n_samples = 20
        monkeypatch.setattr('config.LHS_N_SAMPLES', n_samples)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=1)

        # For each parameter, values should be spread across the range
        for param_name in ['w_r', 'h_si', 'doping', 'S', 'length']:
            values = df[param_name].values
            # Normalize to [0, 1]
            min_val = values.min()
            max_val = values.max()
            if max_val > min_val:
                normalized = (values - min_val) / (max_val - min_val)
                # Check that values span most of the range
                assert normalized.min() < 0.2, f"{param_name} should have low values"
                assert normalized.max() > 0.8, f"{param_name} should have high values"

    @pytest.mark.unit
    def test_no_duplicate_samples(self, mock_config, monkeypatch):
        """Test that no two samples are identical."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 10)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        df = generate_lhs_samples(start_sim_id=1)

        param_cols = ['w_r', 'h_si', 'doping', 'S', 'length']
        # Check for duplicates
        df_params = df[param_cols]
        n_unique = len(df_params.drop_duplicates())

        assert n_unique == len(df), "No duplicate samples should exist"


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestLhsErrorHandling:
    """Tests for LHS error handling."""

    @pytest.mark.unit
    def test_invalid_method_raises(self, mock_config, monkeypatch):
        """Test that invalid sampling method raises ValueError."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 5)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'invalid_method')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        with pytest.raises(ValueError, match="Method must be"):
            generate_lhs_samples(start_sim_id=1)

    @pytest.mark.unit
    def test_zero_samples(self, mock_config, monkeypatch):
        """Test behavior with zero samples requested raises error."""
        from LHS import generate_lhs_samples

        monkeypatch.setattr('config.LHS_N_SAMPLES', 0)
        monkeypatch.setattr('config.LHS_SAMPLING_METHOD', 'random')
        monkeypatch.setattr('config.LHS_RANDOM_SEED', 42)

        # Zero samples causes scipy to fail on empty array
        with pytest.raises(ValueError):
            generate_lhs_samples(start_sim_id=1)
