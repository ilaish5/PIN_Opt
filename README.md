# PS_Opt_V2 — PIN Diode Phase Shifter Optimization

Optimizes silicon PIN-diode phase shifters by orchestrating Lumerical CHARGE + FDE simulations and feeding results into a Bayesian optimizer. Two competing objectives are minimized: drive voltage-length product `V_pi*L` (V·mm) and optical loss (dB/cm).

---

## Workflow

1. **LHS** — Latin Hypercube samples written to `simulation csv/params.csv`.
2. **Initial sims** — Each row run through CHARGE → FDE, results appended to `result.csv`.
3. **BO loop** — GP trained once on all prior rows, then iterates `suggest → simulate → register`.
   - Parameters normalized to `[0,1]` (isotropic Matern kernel)
   - Costs registered as `-log(cost)` (compresses ~8000× spread to ~12×)
4. **Final results** — Persisted under `simulation csv/`.

```
main.py ──► LHS.py ──► run_simulation.py ──► sim_handler.py (lumapi)
                              │                       │
                              │                       ▼
                              │              data_processor.py
                              │                       │
                              ▼                       ▼
                            BO.py  ◄────────────  cost.py
```

`sim_handler.py` is the only module that touches `lumapi`. CHARGE writes `Lumerical_Files/charge_data.mat`, then FDE consumes it.

---

## Requirements

- Python 3.8+
- Lumerical DEVICE (CHARGE) and MODE (FDE)
- Lumerical template files (see below)

```bash
pip install -r requirements.txt
```

### Lumerical template files

Two large files are required in `Lumerical_Files/`:

| File | Size |
|------|------|
| `PIN_Ref_paper_Charge.ldev` | 347 MB |
| `PIN_Ref_phase_shifter.lms` | 15 MB |

Download from the [Releases page](https://github.com/ilaiyomsh/PS_Opt_V2/releases) and place into `Lumerical_Files/`, or pull via Git LFS (`git lfs install && git lfs pull`).

---

## Quick start

1. Edit `system/config.py` and set `LUMERICAL_API_PATH` to your Lumerical Python API path:
   - Windows: `C:\Program Files\Lumerical\v231\api\python`
   - Linux: `/opt/lumerical/v231/api/python`
   - macOS: `/Applications/Lumerical/v231/api/python`

2. Run:
   ```bash
   source venv/bin/activate
   cd system
   python main.py
   ```

---

## Input parameters

| Parameter | Symbol | Range | Unit |
|-----------|--------|-------|------|
| Rib width | `w_r` | 350 – 550 | nm |
| Silicon height | `h_si` | 70 – 130 | nm (10 nm grid, discrete) |
| Doping | `doping` | 1e17 – 1e21 | cm⁻³ |
| Spacing | `S` | 0 – 800 | nm |
| Wavelength | `lambda` | 1260 – 1360 | nm |
| Length | `length` | 0.1 – 1.0 | mm |

Bounds live in `SWEEP_PARAMETERS` in `system/config.py`. Discrete parameters are listed in `DISCRETE_PARAMETERS` and snapped to a fixed grid both in LHS and in BO suggestions.

---

## Output files (`simulation csv/`)

| File | Description |
|------|-------------|
| `params.csv` | LHS-generated inputs (row 2 is units; skip when reading) |
| `result.csv` | Minimal columns per `MINIMAL_RESULT_COLUMNS`, appended after each sim |
| `result_full.csv` | Full results (timing, ranges, geometry) |
| `errors.csv` | Failure log with stage, error type, traceback, params |
| `raw/` | Per-`sim_id` sweep dumps |

Resume support: `main.py` skips any `sim_id` already in `result.csv`.

---

## Cost function

**Valid simulations (`Δφ_max ≥ π`):**
```
cost = w_loss · (α / T_loss)² + w_vpil · (V_pi·L / T_vpil)²
```
Defaults: `w_loss = 0.3`, `w_vpil = 0.7`, `T_loss = 2.0 dB/cm`, `T_vpil = 1.0 V·mm`.

**Failed simulations (`Δφ_max < π`):**
```
cost = C_BASE + β · (π - Δφ_max)²
```
with `C_BASE = 35.0` and `β = 9·C_BASE/π² ≈ 31.83`.

`calculate_cost` returns the **negative** cost (BayesOpt maximizes); `run_simulation._build_result` re-negates before storing.

---

## Key data-processing formulas

- **Capacitance**: `C = d(q·n)/dV + d(q·p)/dV`, converted F/m → pF/cm by ×1e10.
- **Optical loss**: `α [dB/cm] = 2·k₀·Im(n_eff) · (10/ln 10) · 10⁻²`.
- **Phase shift**: `Δφ = 2π·Δn_eff·L / λ`.
- **V_π**: linear interpolation of `|Δφ|(V)` at `π`; `V_π·L` reported in V·mm.

All values at `V_π` are interpolated from the simulated sweeps. See `system/data_processor.py` for the implementations.

---

## Configuration knobs (`system/config.py`)

| Flag | Default | Purpose |
|------|---------|---------|
| `LUMERICAL_API_PATH` | — | **Required**; platform-specific |
| `RUN_SIMULATION` | `True` | `False` runs orchestration without invoking Lumerical |
| `SKIP_LHS` | `False` | Reuse existing `params.csv` |
| `SKIP_INITIAL_SIMS` | `False` | Jump straight to BO with existing `result.csv` |
| `HIDE_GUI` | `True` | Hide Lumerical GUI |
| `DEBUG`, `SHOW_PLOTS` | `False` | Interactive/visualization |
| `LHS_N_SAMPLES` | `50` | Number of initial samples |
| `LHS_SAMPLING_METHOD` | `'random'` | `'random' \| 'maximin' \| 'optimum'` (smt) |
| `MAX_ITERATIONS` | `100` | BO iterations |
| `BO_KAPPA` | `4.0` | UCB exploration weight |
| `BO_KAPPA_DECAY` | `1.0` | Multiplier per iteration (`1.0` disables) |
| `DELAY_BETWEEN_RUNS` | `0` | Cooling delay (seconds) between sims |
| `FOM_WEIGHTS`, `TARGETS` | see above | Cost-function tuning |

---

## Project structure

```
PS_Opt_V2/
├── system/                    # Python source
│   ├── main.py                # Entry point
│   ├── config.py
│   ├── LHS.py
│   ├── BO.py                  # GP + UCB; params [0,1], -log(cost) target
│   ├── cost.py                # Piecewise quadratic
│   ├── run_simulation.py      # Per-row orchestration, CSV I/O
│   ├── sim_handler.py         # Lumerical API
│   └── data_processor.py      # Optical/electrical post-processing
│
├── Lumerical_Files/           # Templates (Git LFS / Releases)
├── simulation csv/            # Inputs/outputs
├── analysis/                  # Post-optimization analysis of the best design (Sim 109)
│   ├── plots.ipynb            # Project-book figures from result.csv
│   ├── RC_design_Loss.m       # RC equalizer design (loss → bandwidth trade-off)
│   ├── rc_equalizer_S21.s2p   # Equalizer S21 response (Touchstone)
│   ├── plot_eye_diagram_interconnect.py  # Eye diagrams via INTERCONNECT API
│   └── eye_rc_interconnect/   # Baseline + equalized .icp projects (Git LFS)
├── results_archive/
│   └── best_run_109/          # Best BO run summary (result.csv, result_full.csv)
├── test/                      # Pytest suite
├── requirements.txt
└── README.md
```

---

## Tests

```bash
pytest -m "not lumerical"          # default — skips Lumerical-dependent tests
pytest -m unit                     # unit tests only
pytest -m "not lumerical" --cov=system --cov-report=term-missing
```

Lumerical-marked tests require a working install and a valid `LUMERICAL_API_PATH`.

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `lumapi not found` | Check `LUMERICAL_API_PATH` |
| `Lumerical file not found` | Verify `.lms`/`.ldev` in `Lumerical_Files/` |
| `Module not found` | `pip install -r requirements.txt` |
| Simulation crashes mid-run | Increase `DELAY_BETWEEN_RUNS` |
| CSV column mismatch | Delete old `result.csv` and start fresh |
