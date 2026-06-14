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

## Runs (self-consistent extraction — all values per-sim, no book forced)

Stage A is a fully sim-computed small-signal extraction (one forward-bias SSAC
sweep, one length normalization, everything off the same Y_device). See
`results_archive/eye_109/WORKLOG.md` sec 10. Op bias 0.70 V.

| sim_id | V_pi | R_S | R_F | C_diff | C_dep | τ | f_3dB,diff | f_3dB,dep | eyes |
|---|---|---|---|---|---|---|---|---|---|
| 109 | 0.862 V | 10.33 Ω | 11.36 kΩ | 3.40 pF | 0.0243 pF | 38.7 ns | 0.775 GHz | 108 GHz | baseline dead / equalized open @100 Gbps |
| 63  | 0.863 V | 11.85 Ω | 5.65 kΩ | 4.20 pF | 0.0236 pF | 23.7 ns | 0.613 GHz | 109 GHz | baseline dead / equalized open @100 Gbps |

The values **differ per design** (R_S, R_F, C_diff, f_3dB all change) — physics, not
the old forced `R_S = 23.31 Ω`. Computed-vs-book: R_S ~half book (book includes
external contact R outside the 2D model); R_F matches book at this bias for 109;
C_diff ~10× book and f_3dB,diff ~8–10× lower (the book's 6.25 GHz/0.347 pF are
cross-bias values). The real forward-injection BW is ~0.6–0.8 GHz, so 100 Gbps
needs ~42–44 dB of equalization.

> Historical note: an earlier "pragmatic per-param" Stage A reproduced the book
> Table-3 numbers by forcing `R_S = 23.31 Ω` and reading C_F as the depletion cap.
> That is retired — it hid the per-design physics. See eye_109/WORKLOG.md sec 8 (old)
> vs sec 10 (current).

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

### Units / normalization (the self-consistent verdict)
ONE consistent 2D→device length normalization is applied to the WHOLE impedance:
`Z_device(ω) = Z_reported(ω)·(norm/L)` (norm = 0.01 m = 1 cm; L = device length).
Then R_S, R_F, C_diff, C_dep are all read off the same `Y_device = 1/Z_device`
(`eye_lib.extract_small_signal`). R scales up by norm/L (×13.3 for L=0.752 mm), C
scales down by L/norm, so `τ = R_F·C_diff` is scaling-invariant. **No book values
are forced.** The result differs per design (see Runs table).

The book's Table-3 triple is **cross-bias** — its `R_F=10.55 kΩ` is at ~0.70 V but
its `C_F=0.347 pF`/`f_3dB=6.25 GHz` correspond to a *lower* bias (~0.60 V). At one
consistent bias the diffusion cap is ~10× larger (real f_3dB,diff ~0.6–0.8 GHz).
Book `R_S=23.31 Ω` > sim ~10–12 Ω → the book includes external contact/metal R that
the 2D CHARGE model does not.

(Retired earlier policy: forcing `R_S=23.31 Ω` (book) and reading C_F as the
unscaled depletion cap to hit Table 3 — it hid the per-design physics.)

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
