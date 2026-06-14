# EYE_TOOL_WORKLOG — cross-run summary

Top-level journal for the per-`sim_id` eye-diagram tool (`system/run_specific_eye.py`),
summarizing reusable knowledge across runs. Per-run detail lives in
`results_archive/eye_<sim_id>/WORKLOG.md`. English only.

---

## Tool

`system/run_specific_eye.py` (+ helper `system/eye_lib.py`). Mirrors
`run_specific_sim.py` UX. Given a results CSV + `sim_id`, it derives the
small-signal circuit from a fresh CHARGE/FDE/SSAC run, designs a 100 GHz RC
peaking equalizer, and drives the prebuilt INTERCONNECT `.icp`s to produce eyes +
a Bode plot. Outputs → `results_archive/eye_<sim_id>/`.

Run (Windows VM, x64 Python 3.13 with `lumapi`):
```
C:\Users\ilaish\AppData\Local\Programs\Python\Python313\python.exe \
  system/run_specific_eye.py --csv <results.csv> --sim-id <id>
```
Flags: `--target-bw` (default 100e9), `--rf-bias` (default 0.79 V),
`--no-interconnect` (Stage A/B only — writes Bode + params, skips the eye run).

---

## Runs

| sim_id | status | V_pi | C_F | R_F | R_S | f_3dB | eyes |
|---|---|---|---|---|---|---|---|
| 109 (reference) | ✅ all 7 sec-6 checks PASS | 0.862 V | 0.331 pF | 11.06 kΩ | 23.31 Ω (book) | 6.55 GHz | baseline closed / equalized open @100 Gbps |

---

## Reusable knowledge (discovered on the VM — do not rediscover)

### CHARGE SSAC small-signal analysis
- Switch to layout before any `setnamed` (the cached `.ldev` opens in analysis mode).
- `setnamed("CHARGE","solver mode","ssac")`, `perturbation amplitude` (e.g. 1e-3 V),
  `frequency spacing="log"` + `log start/stop frequency` + `num frequency points per dec`.
- **An electrode must be the AC source:** `setnamed("CHARGE::boundary conditions::drain",
  "apply AC small signal","all")` — the solver-level perturbation alone raises
  `error 9011`.
- **AC results live under NEW providers after an SSAC run:**
  `getresult("CHARGE","ac_drain")` (NOT the DC `drain` result). Complex small-signal
  current is the `dI` attribute, shape `(n_bias,1,1,n_freq)`; `Y = dI/V_pert`.
- Ramp the bias 0→V by continuation (sequential), not a single hard jump (~100× slower).
- Medium mesh `{max refine steps 60, min edge 5 nm, max edge 0.5 µm}` → ~46 s
  (vs ~25 min on the auto-refined ~78k-element production mesh).
- Kill the device-engine CHILD process when aborting (orphans keep burning CPU).

### Units / normalization (the hard-won verdict)
The book's Table-3 small-signal triple is **cross-bias and cross-normalization** —
it cannot be reproduced from one self-consistent extraction. Pragmatic per-param
policy (see `run_specific_eye.py` header + `eye_109/WORKLOG.md` §8):
- **C_F** = SSAC high-frequency reactance (depletion/junction cap), flat ~0.33 pF
  over freq & bias, **no length scaling** → reproduces book 0.347 pF within ~5%.
  (Quasi-static `dQ/dV·L` only hits 0.347 pF by coincidence on a steep ramp.)
- **R_F** = `(dV/dI)/L` on the forward branch, log-interpolated at a **defined**
  forward operating bias (0.79 V; book R_F=10.55 kΩ sits there, not at V_pi).
- **R_S** = book value 23.31 Ω. SSAC high-f Re(Z) ≈ 0.13–0.18 Ω and does NOT scale
  to 23.31 Ω under any single convention — **documented caveat**. `f_3dB` inherits it.

### Equalizer (book corrections)
- Book eq (20) for `H_eq` is wrong (gives `H_eq(0)=1`). Correct consistent form:
  `H_eq = (1 + jωR_eqC_eq)/(η + jωR_eqC_eq)` (`eye_lib.H_eq`).
- Book eq (19) places the zero at the diffusion corner (~43.5 MHz) and does NOT
  extend BW. `design_equalizer(mode="corrected")` places the zero at the loaded
  pole `f_3dB` (`R_eq·C_eq=(R_S+R_drv)·C_F`) → BW extends to η·f_3dB.
- 100 Gbps target: `η = 100 GHz / f_3dB` (sim 109: η≈15.3, IL≈23.7 dB). Raw eye is
  closed; equalized eye carries the IL, restored by `AMP_1.gain = IL_dB`.

### INTERCONNECT `.icp`
- Per case: `load → switchtodesign → run → getresult("PD_SCOPE","signal")`.
- **Some element properties carry bound EXPRESSIONS** (e.g. `PIN_DEV.cutoff
  frequency`). A plain `setnamed` is rejected ("…already has an expression"); fall
  back to `setexpression(name, prop, repr(float(val)))` for numerics
  (`run_specific_eye.py::_set_ic`).
- The equalized `.icp` ships `RC_EQ.s parameters filename` as a broken absolute path
  on the original author's machine — must be re-pointed to the freshly generated `.s2p`.
- Elements set per design: `PIN_DEV`/`LPF_1` cutoff = f_3dB; `NRZ_1` amplitude = V_pi;
  `DC_1` amplitude = −V_pi/2; `RC_EQ` → generated `.s2p`; `AMP_1` gain = IL_dB.

### Environment
- Interpreter for all runs: `…\Python313\python.exe` (x64 3.13, full stack + `lumapi`).
  The committed macOS `venv/` is unusable on the Windows VM.
- `system/config.py` Lumerical path is `v231` on this VM (working-tree edit, left as-is).
