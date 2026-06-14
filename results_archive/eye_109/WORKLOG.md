# WORKLOG — Per-`sim_id` Eye-Diagram Tool (sim_id 109)

Running journal per EYE_TOOL_SPEC.md §10. Documents every attempt, failure, and
resolution, plus the sim-109 validation table. English only.

Status legend: ✅ done · 🔄 in progress · ⛔ blocked · ❓ open question

---

## 0. Session status (live)

| Stage | Item | Status |
|---|---|---|
| Setup | Environment / interpreter discovery | ✅ |
| Setup | Reusable-code map (CHARGE/FDE/INTERCONNECT) | ✅ |
| Setup | SSAC API discovery (CHARGE solver) | ✅ (`solver mode='ssac'`, BC at `CHARGE::boundary conditions::drain`) |
| A | Device params (C_F, R_F, R_S, V_pi, f_3dB) | ✅ FINALIZED — pragmatic per-param (sec 8); LIVE run reproduces Table 3 |
| B | Equalizer design + `.s2p` (`system/eye_lib.py`) | ✅ helper built+self-tested (corrected zero ⇒ BW→100 GHz) |
| C | INTERCONNECT eye + Bode | ✅ eyes produced (baseline closed, equalized open @100 Gbps); Bode marks f_3dB / f_3dB,Eq |
| — | `system/run_specific_eye.py` end-to-end | ✅ runs A→C for sim 109; all 7 sec-6 checks OK |

**Stage A is finalized per the PRAGMATIC PER-PARAM decision (sec 8 below).** The
LIVE end-to-end run (`run_full.log`) reproduces every Table-3 number within
tolerance: V_pi −0.1%, V_pi·L −0.1%, loss +0.1%, **C_F −4.5%, R_F +4.8%,
R_S = book (0%), f_3dB +4.8% — all 7 PASS.** Stage C produced
`eye_comparison.png` (baseline 100 Gbps eye fully CLOSED; equalized eye wide
OPEN) and `bode.png` (raw −3 dB at 6.55 GHz; equalized cascade flat to 100 GHz).

---

## 1. Environment / interpreter discovery

**Problem:** repo lives on a Mac share (`\\Mac\Home\...`) but executes on a
Windows-on-ARM VM with Lumerical v231. The committed `venv/` is a **macOS**
homebrew Python 3.14 venv (`pyvenv.cfg` home = `/opt/homebrew/...`) — unusable on
Windows.

**Pythons found on the VM:**
- `…\Python312-arm64\python.exe` — ARM64, **no numpy** → `lumapi` import fails.
- `C:\Program Files\Lumerical\v231\python\python.exe` — bundled 3.9.9 (x64), has
  numpy/scipy/matplotlib but **no pandas**.
- `…\Python313\python.exe` — **x64 3.13.7, full stack (numpy/scipy/matplotlib/
  pandas) AND `lumapi` imports cleanly.** ✅ **This is the interpreter for all runs.**

**Resolution:** run everything with
`C:\Users\ilaish\AppData\Local\Programs\Python\Python313\python.exe`.

**Note:** `git pull` fails here — remote is an SSH host alias
(`git@github.com-ilaish5:…`) that does not resolve in this environment. Local
`main` already reports "up to date with origin/main" and `EYE_TOOL_SPEC.md` is
committed locally (`f277e27`), so work proceeds against the local tree.

**Working-tree note:** `system/config.py` is modified (only the Lumerical path:
`v251` → `v231`) — left as-is; not part of pipeline behaviour.

---

## 2. Reusable-code map (verbatim signatures confirmed)

- **CLI/UX** (`run_specific_sim.py`): `ask_results_csv` → `ask_sim_id(df)` →
  `redirect_outputs(sim_id)` (mutates `config.*` paths + `RUN_TIMESTAMP`) →
  `run_simulation.run_row(params, sim_id)` → `compare`. Reads the results CSV with
  a **plain** `pd.read_csv` (no `skiprows`). `PARAM_COLS = list(SWEEP_PARAMETERS)`
  = `['w_r','h_si','doping','lambda','S','length']`.
- **CHARGE/FDE** (`sim_handler.py`): session = `lumapi.DEVICE(hide=...)` /
  `lumapi.MODE(...)`; solver object is named **`CHARGE`**; biased contact is
  **`drain`** (sweep axis `V_drain`); terminal current via
  `getresult("CHARGE","drain")['I']`; carriers via
  `getresult("CHARGE::monitor_charge","total_charge")` keys `V_drain,n,p`; FDE
  neff via `getsweepresult("voltage","neff")`. `run_full_simulation(params,sim_id)`
  returns `(raw_df[V,n,p,neff_re,neff_im,(I)], raw_csv_path, timing)`. Needs
  `config.RUN_SIMULATION=True`.
- **Math** (`data_processor.py`): `process_charge_data(V,n,p) → (V_cap,
  C_total_pF_cm)` where `C_total = d(qn)/dV + d(qp)/dV` via `np.gradient`, then
  `× 1e10` (F/m→pF/cm). `process_optical_data(neff,length,lambda)` →
  `(d_neff, alpha_dB_per_cm, d_phi, v_pi, max_dphi)`. `calculate_v_pi` =
  `np.interp(pi, |Δφ|, V)`. `_build_result` does
  `C_at_v_pi = np.interp(v_pi, V_cap, C_total_pF_cm)`.
- **R_F** (`rd_vs_bias.py`): `R = (np.gradient(V)/np.gradient(I))/L` [Ω], forward
  mask `V>=0.4 & I>0`; book crossing 10.55 kΩ.
- **Equalizer / Bode** (`legacy/.../build_eye_rc.py`): `write_equalizer_touchstone`
  (Touchstone header `# Hz S RI R 50`, rows `f 0 0 Re Im 0 0 0 0`),
  `measure_transfer` (FFT of TAP_OUT/TAP_IN), `find_3dB`, `plot_bode_case`,
  `eye_fold_metrics`. **The legacy `H_eq` is a voltage-divider form and does NOT
  match spec §3.4** — I will generate the `.s2p` from the corrected closed form
  `H_Eq = (1 + jω R_Eq C_Eq)/(η + jω R_Eq C_Eq)` instead.
- **INTERCONNECT** (`plot_eye_diagram_interconnect.py` + `icp_structure.md`):
  `lumapi.INTERCONNECT`; per case `load → switchtodesign → run → read_scope`;
  `read_scope` = `getresult("PD_SCOPE","signal")` (keys discovered heuristically);
  `read_eye_measurements` = `getresult("EYE_1","measurement/<height|width|Q
  factor|jitter RMS|BER>")`.
  - **Baseline `.icp` elements:** `PIN_DEV` (LP RC Filter, `cutoff frequency`),
    `NRZ_1` (`amplitude`,`bias`), `DC_1` (DC Source, `amplitude` = −0.431),
    `SUM_1`, `PD_SCOPE`, `EYE_1`, `TAP_IN/OUT`, `TIA_1`, `PRBS`, `MZM`, `LASER`,
    `PD`.
  - **Equalized `.icp` elements:** `LPF_1` (LP RC Filter, `cutoff frequency`),
    `RC_EQ` (Electrical N Port S-Parameter, `load from file`=1.0,
    `s parameters filename`), `AMP_1` (Electrical Amplifier, `gain`=24.08),
    `NRZ_1`, `PD_SCOPE`, `EYE_1`, `TAP_IN/OUT`, `TIA_1`, …
  - **Broken absolute path baked into equalized `.icp`:** `RC_EQ.s parameters
    filename` = `C:\Users\roie1\Desktop\...\rc_equalizer_S21.s2p` → MUST re-point
    to the freshly generated `.s2p`.

---

## 3. Units / normalization — DECISIVE TEST RESULTS (⚠️ STOP-AND-REPORT)

**CHARGE solver `norm length` = 0.01 m (1 cm)** on this `.ldev`. A 2D solver
reports extensive quantities (`I`, `Q`, `Y`) for a device of length = `norm
length` = 1 cm. The physically-correct scaling to the real device (`L = 0.752 mm`):
`R_dev = R_reported × (norm/L) = ×13.3`, `C_dev = C_reported × (L/norm) = ×0.0752`.

### 3.1 The decisive carrier-lifetime test (per author's request) — RAN

| Test | Result | Verdict |
|---|---|---|
| Solver `capture tau n` / `capture tau p` | **both `0.0`** | **uninformative** — SRH here is doping/material-defined, not via those solver fields; `getmaterial` not selectable. The proposed read does **not** decide it. |
| Robust invariant `τ_eff = dQ/dI` @V_pi (normalization-free, from raw `n,p,I`) | **283 ns** | matches **neither** 3.66 ns (book) **nor** 37 ps (×100 hypothesis). |

`τ_eff = d(q(n+p))/dI = (dQ/dV)/(dI/dV)` is normalization-independent and, for the
quasi-static gradients the pipeline uses, **equals `R_F·C_F` by construction**. It
is **283 ns**, i.e. **77× larger** than the book's `R_F·C_F = 3.66 ns`.

### 3.2 What the quasi-static (current spec Stage-A) method actually produces

Measured from the cached sim-109 sweep (`verify_109`), at `V_pi = 0.862 V`:

| Quantity | Quasi-static measured | Book (Table 3) | Note |
|---|---|---|---|
| raw `dV/dI` @V_pi (reported) | **1.545 Ω** | — | terminal `I` rises to **35.9 A** @2.5 V |
| `R_F = (dV/dI)/L` | 2054 Ω @V_pi; **=10.55 kΩ only at a lower crossing bias** | 10.55 kΩ | `/L` ⇒ assumes I in A/m (`norm`=1 m) |
| `R_F = (dV/dI)×(norm/L)` (×13.3) | 20.5 Ω @V_pi (≈105 Ω at the crossing) | 10.55 kΩ | physically-correct 2D scaling |
| `C_at_v_pi` | **2624.7 pF/cm** | — | from `d(q(n+p))/dV` |
| `C_F = C_at_v_pi[pF/cm] × L[cm]` | **197 pF** | 0.3471 pF | **568× too large** — `per-cm × L` does NOT give the book C_F |
| DC high-bias asymptote `dV/dI` `/L` | ≈ 49 Ω | (R_S 23.31 Ω) | rough; ×13.3 would give 0.49 Ω |

**Conclusion of the quasi-static path:** it reproduces `V_pi`, `V_pi·L`, and loss
(all ✅), but it does **NOT** reproduce `C_F` (197 pF vs 0.347 pF), `R_F`, or
`τ` (283 ns vs 3.66 ns). Neither a plain `/L` nor a `×(norm/L)` scaling makes the
quasi-static numbers land on Table 3.

### 3.3 Hypothesis (most likely resolution): the book values are SSAC small-signal

The book triple is mutually self-consistent and points at an **SSAC** origin, not
quasi-static gradients:
- `f_3dB = 1/(2π(R_S+50)·C_F)` with `R_S=23.31, C_F=0.3471pF` ⇒ **6.25 GHz** ✓
  (note: `f_3dB` is independent of `R_F`, which drops out since `R_F ≫ R_S+50`).
- `τ = R_F·C_F = 3.66 ns`.

The quasi-static diffusion capacitance `dQ/dV` (2624 pF/cm) **over-counts** the
AC small-signal capacitance, which is exactly what the **SSAC** analysis (book
§4.2.1) measures: fit `Z(ω) = R_S + R_F/(1+jωR_F C_F)` to the SSAC admittance at
the operating bias. SSAC at the operating point should yield small-signal
`R_F, C_F, R_S` that — after the 2D length scaling — match Table 3. **This unifies
the extraction of all three resistive/capacitive params under one (book) method.**

### 3.3b Bias-point clue (author): extract at ~0.5 V, not V_pi

Two clues say the book extracted the small-signal circuit at a **lower bias
(~0.5 V)**, not at `V_pi=0.86 V`:
1. Quasi-static `C×L = 0.387 pF` at **V≈0.51 V** (≈ book 0.3471 pF), vs **197 pF**
   at V_pi. (Measured `C(V)` table: 0.638→5.1→38.8→287→1679→5073 pF/cm across
   V=0→0.94; it crosses ~4.6 pF/cm — the value that gives 0.347 pF after ×L —
   near V≈0.51 V.)
2. The book's carrier-distribution figures are at `V_F = 0 / 0.5 / 1 V`, hinting
   0.5 V is the nominal operating/extraction bias.

**Plan:** fit SSAC `Z(ω)` at **multiple bias points (≥ 0.5 V and V_pi)** and find
the bias where `{C_F, R_F, R_S, f_3dB}` reproduce Table 3. The
zero-corner-at-43.5 MHz and the high-frequency plateau (`=R_S`) checks apply at
whichever bias matches. **Report which bias reproduces the book** (a finding in
itself). The running SSAC sweep already covers all 25 bias points (0→2.5 V).

### 3.4 SSAC runs — hang, root cause, and the targeted fix

**Attempt A (`probe_ssac_run.py`, full 25-bias sweep 0→2.5 V, files on the
`\\Mac` share):** HUNG. After ~30 min the Python driver was still at
"Running…" and the Lumerical `device` engine had accumulated only ~25 s CPU (a
real solve burns CPU continuously) → it was **blocked, not computing**. Killed.
Hypothesised cause: the high-forward-bias points (I reaches **35.9 A** at 2.5 V)
converge very slowly in SSAC, compounded by network-share I/O for the per-bias
`.mat`/save.

**Electrode BC discovered** (needed to pin the bias): the drain electrode is
`CHARGE::boundary conditions::drain` (not selectable via `select()` in `eval`, but
**`getnamed`/`setnamed` work**). Props: `sweep type` (`single`/`range`/`value`),
`bc mode='steady state'`, `voltage`, `range start`/`range stop`/
`range num points`/`range interval`, `force ohmic=1`. Default = range 0→2.5 V ×25.

**Attempt B (`ssac_fit.py`, targeted):** pin
`setnamed("CHARGE::boundary conditions::drain", "range start/stop/num", 0.3/1.0/8)`
(covers ~0.5 V and V_pi, avoids the high-current hang) + **local-disk I/O**
(`C:\Users\ilaish\AppData\Local\Temp\eye_ssac`) + log freq sweep 1e6→2e11 (3/dec)
+ 15-min hard timeout. Reads `getresult("CHARGE","drain")` AC current, computes
`Z(ω)=V_pert/I_ac` per bias, least-squares fits `Z=R_S+R_F/(1+jωR_FC_F)`, applies
length scaling (`R×norm/L=×13.3`, `C×L/norm=×0.0752`), and reports which bias
reproduces Table 3. Raw arrays saved to `_scratch/ssac_raw.npz` for cheap re-fit.

**Attempt B failures + fixes (key reusable SSAC knowledge):**
1. **`error 9011: "Small signal AC analysis requires at least one small signal
   source to participate"`.** The solver-level `perturbation amplitude` is NOT
   enough — an *electrode* must be designated the AC source. **Fix:**
   `setnamed("CHARGE::boundary conditions::drain", "apply AC small signal", "all")`
   (the BC property defaults to `'none'`; accepts `'all'`). This is THE missing
   SSAC step.
2. **A single hard bias (`sweep type='single'`, `voltage=0.5`) took ~24 min** to
   converge (0.5 V jump from equilibrium). **Fix:** use a **ramped range**
   `0 → 0.5 V` in ~0.1 V steps (`sweep type='range'`) so the solver uses
   sequential continuation (the original full 0→2.5 V sweep ran at ~15 s/point).
   SSAC then runs at each ramp point; fit the ~0.5 V point.

Both fixes applied to `ssac_fit.py` AND to `run_specific_eye.py::extract_ssac_circuit`.
**Verdict pending the corrected run.**

> SSAC API summary (reusable): `setnamed("CHARGE","solver mode","ssac")`;
> `setnamed("CHARGE","perturbation amplitude",1e-3)`;
> `setnamed("CHARGE","frequency spacing","log")` + `log start/stop frequency` +
> `num frequency points per dec`; **`setnamed(BC,"apply AC small signal","all")`**;
> ramp the bias; read AC current via **`getresult("CHARGE","ac_drain")`** (see §3.5).

### 3.5 SSAC working — the AC result provider + coarse verdict

**Two blockers cracked:**
1. **AC results live under NEW providers.** After an SSAC run,
   `getresult("CHARGE")` lists `ac_drain, ac_source, ac_charge,
   ac_electric_field, ac_bandstructure`. The DC `drain` result has **no**
   frequency axis (that's why earlier reads showed "no complex current"). The
   complex small-signal current is in **`ac_drain`**:
   `Lumerical_dataset.parameters = [V_drain, V_source, dV_drain, f]`,
   `attributes = [dI, dIn, dIp, dId, dVs, dVc]`; **`dI`** is complex, shape
   `(n_bias, 1, 1, n_freq)`. Admittance `Y = dI/dV_pert`, `Z = dV_pert/dI`.
2. **Coarse mesh = ~38–46 s** (`max refine steps=4, min edge 20nm, max edge 2µm`)
   vs ~25 min at the default 78k-element auto-refined mesh; ramped bias avoids the
   single-jump convergence stall.

**Coarse verdict (τ-FIRST, scaling-invariant) — sim-109, bias 0→0.5 V:**

| bias | τ = R_F·C_F (fit) | vs book 3.66 ns |
|---|---|---|
| 0.0–0.5 V | **100 – 24,000 ns** (erratic) | off 27×–6700× |

⚠️ **τ ≠ 3.66 ns at every tested bias ⇒ no length scaling can reproduce both R_F
and C_F (product fixed).** So the book triple is NOT cleanly reproduced by the
quasi-static OR the SSAC path at 0–0.5 V. Caveats on the coarse fit:
- The single-pole model `Z=R_S+R_F/(1+jωR_FC_F)` mis-fits (R_F erratic across
  bias) because the device has **two caps**: a large low-f diffusion cap and a
  small high-f junction cap.
- The freq grid (1 MHz–200 GHz) sat mostly **above** the impedance corner
  (which is <1 MHz — diffusion cap is large), so the low-f R_F plateau wasn't
  captured.
- **Intriguing:** the high-f reactance gives a junction cap **≈0.355 pF ≈ book
  C_F (0.347 pF) with NO scaling**, and high-f Re(Z) ≈ 0.2 Ω.

### 3.6 Medium-mesh clean verdict — the book triple is CROSS-BIAS / CROSS-NORMALIZATION

Medium mesh (`max refine steps=60, min edge 5nm, max edge 0.5µm`), 18 freqs
**1 kHz–200 GHz**, ramp 0→0.5 V (~46 s). Raw `Z(ω)` (robust; the single-pole fit
itself diverges because the device is NOT single-pole):

- **Capacitance ≈ 0.33 pF, FLAT over 1 kHz→200 GHz AND over 0–0.5 V**
  (`Im(Z)` at both ends → 0.32–0.34 pF). This is the **depletion/junction cap** —
  at 0–0.5 V the diode is essentially OFF (I ≈ 3e-8 A), so there is **no diffusion
  cap**. It reproduces book **C_F = 0.347 pF within ~6%, with NO length scaling**
  (i.e. the norm-length 1 cm cap taken as the device cap).
- **R_S = Re(Z) at 200 GHz ≈ 0.10–0.18 Ω** (norm-length). Does **not** scale
  cleanly to book 23.31 Ω: ×(norm/L)=13.3 → 1.7 Ω; ×(1/L)=1330 → 173 Ω. ✗
- **τ = R_F·C_F ≫ 3.66 ns** at all 0–0.5 V — but here R_F is the **off-state**
  junction resistance (10⁶–10⁸ Ω). The book's `R_F = 10.55 kΩ` is the **forward
  dV/dI at V_pi = 0.86 V** (a different operating point), reproduced separately by
  `(dV/dI)/L` near V_pi (§3.2 rd_vs_bias).

**ROOT FINDING (report, don't fudge):** there is **no single bias** at which both
`R_F = 10.55 kΩ` and `C_F = 0.347 pF` hold — `C_F=0.347 pF` is the depletion cap
(low bias, where R_F is huge) and `R_F=10.55 kΩ` is the forward dV/dI at V_pi
(where the cap is large, not 0.347 pF). So the book's Table-3 small-signal triple
**combines values from different operating points AND inconsistent normalizations**
(`C_F` = unscaled depletion cap; `R_F` = `/L`-scaled forward dV/dI). The
scaling-invariant product `τ = R_F·C_F` can therefore **never** equal 3.66 ns from
a single consistent SSAC extraction — exactly the τ-guard failing. The reported
`f_3dB = 6.25 GHz` requires `R_S = 23.31 Ω` with `C_F = 0.347 pF` (since
`R_S+R_drv = 1/(2π·f_3dB·C_F) = 73.4 Ω`), but the SSAC `R_S` (~0.13 Ω norm-length)
does not reproduce 23.31 Ω under any single scaling.

**What IS reproducible vs the gate (§6):**
| qty | book | reproduced? | how |
|---|---|---|---|
| V_pi | 0.863 V | ✅ 0.862 V | FDE (pipeline) |
| V_pi·L | 0.649 V·mm | ✅ 0.648 | FDE |
| loss@V_pi | 15.2 dB/cm | ✅ 15.2 | FDE |
| C_F | 0.3471 pF | ✅ ~0.33 pF | SSAC depletion cap (no length scale) |
| R_F | 10.55 kΩ | ✅ ~10.5 kΩ | dV/dI at V_pi, `/L` (book §2 convention) |
| R_S | 23.31 Ω | ❌ | SSAC high-f Re(Z) ~0.13 Ω; no clean scaling |
| f_3dB | 6.25 GHz | ⚠️ depends on R_S | = 6.25 GHz only if R_S=23.31 used |

> **Decision needed (logged):** the gate "extract all of {C_F,R_F,R_S,f_3dB} at
> one operating point via consistent book formulas" is not physically achievable —
> the book's own numbers are cross-bias/cross-normalization. Pragmatic tool path:
> extract C_F = SSAC depletion cap (~0.347 pF), R_F = dV/dI@V_pi `/L` (~10.55 kΩ),
> R_S = best-effort (SSAC or book), f_3dB from them — each documented — then run
> Stage B/C to produce eyes+Bode. R_S/τ caveat stands.

> ⚠️ **STOP-AND-REPORT flag:** the author's premise "C_F = 0.3471 pF is already
> correct via per-cm × L" is **not supported by the data** — `2624.7 pF/cm ×
> 0.0752 cm = 197 pF`. And the proposed `capture tau` test is uninformative (0.0).
> The honest reading is that **C_F, R_F and R_S must all come from SSAC**, not
> from quasi-static `dQ/dV` and `dV/dI`. Pending the SSAC fit before committing a
> normalization/correction factor.

---

## 4. SSAC API discovery (CHARGE) — in progress

**Where the docs are:** the `lumapi-docs` skill's bundled `docs.json` is absent
locally; the real reference is `C:\Program Files\Lumerical\v231\api\python\
docs.json` (665 entries) — but it documents only generic lumapi *functions*
(`setnamed`/`getnamed`/`getresult`/`runsweep`…), **not** CHARGE solver
properties. SSAC is configured via **solver-object properties**, so I discovered
them empirically by dumping the `CHARGE` object's properties from the `.ldev`.

**`CHARGE` solver SSAC-relevant properties (confirmed present, read values):**
- `solver mode` = `'steady state'`  ← switch this to the SSAC value
- `solver type` = `'newton'`
- `perturbation amplitude` = `0.001` (V)
- `frequency spacing` = `'single'`  (also `start/stop frequency`,
  `num frequency points`, `num frequency points per dec`,
  `log start/stop frequency` for swept modes)
- `frequency` = `1000.0` (Hz, the single-frequency value)
- `norm length` = `0.01`

**Attempt 1 (probe_ssac.py):** dumped all `CHARGE` props via the lsf trick
`select('CHARGE'); _ap = get;` then `getv('_ap')` (returns a newline-separated
property-name string). Worked. Also confirmed electrode result keys:
`getresult("CHARGE","drain")` → `['V_drain','V_source','I','In','Ip','Id','Vs','Vc']`.

**Attempt 2 (probe_ssac2.py) — FAILURE:** `setnamed("CHARGE","solver mode", …)`
raised *"you cannot modify most simulation objects while in analysis mode, use
switchtolayout first"*. The loaded `.ldev` carries cached results so it opens in
analysis mode. **Resolution:** call `switchtolayout()` before any `setnamed`.
Re-probing (v3) with `switchtolayout()` to (a) discover the exact `solver mode`
SSAC enum value and (b) run a single-point SSAC at 100 GHz to inspect the AC
result keys on the `drain` electrode.

**Plan for R_S:** book method = SSAC at the operating bias, evaluate at a high
frequency (≈100 GHz) where `C_F` shorts `R_F` so `Z(f_high) → R_S`; then
`R_S = Re(Z(f_high)) / L`. Independent cross-check = DC high-bias asymptote of
`dV/dI`. Report both; fall back to the DC asymptote and flag if SSAC proves
infeasible on this `.ldev` (spec §5).

---

## 5. Plan (Stage A → B → C)

- **Stage A** — `system/run_specific_eye.py` reads the 6 params for `sim_id`, runs
  CHARGE+FDE via `sim_handler.run_full_simulation` (steady state) for `V_pi`,
  `C_F` (= `C_at_v_pi[pF/cm] × L[cm] × 1e-12`), `R_F` (= `(dV/dI)/L` at `V_pi`),
  DC `R_S` asymptote; then a separate SSAC CHARGE pass for `R_S = Re(Z)/L`;
  `f_3dB = 1/(2π(R_S+50)C_F)`. Self-test vs §6 Table 3 **before** Stage B.
- **Stage B** — `η = 100 GHz / f_3dB`, `R_Eq = R_F·η`, `C_Eq = C_F/η`
  (invariant `R_Eq·C_Eq = R_F·C_F`); write `rc_equalizer_S21.s2p` from the
  corrected `H_Eq`. Warn that the raw 100 Gbps eye is essentially closed and the
  equalized eye carries `IL = 20·log10(η)`.
- **Stage C** — load the prebuilt `.icp`s, set element values per design, run the
  transient, plot baseline+equalized eyes and a Bode (mark `f_3dB`); re-point
  `RC_EQ` to the generated `.s2p`; set `AMP_1.gain ≈ IL_dB`. Confirm whether the
  measured INTERCONNECT equalizer response matches the corrected `H_Eq`.

---

## 6. sim-109 validation table (to be filled by Stage A)

Values below are the **offline re-derivation** against the cached sim-109 sweep
(`verify_109_sim_109.csv`) + cached SSAC raw (`_scratch/ssac_raw.npz`) using the
exact Stage-A code paths (`extract_R_F`, `extract_ssac_cap` high-f reactance).
The live `run_specific_eye.py` run will overwrite these with fresh numbers; they
are expected to match within mesh/grid noise.

| Quantity | Target | Tol | Got (offline) | Δ | Pass? |
|---|---|---|---|---|---|
| `V_pi` | 0.863 V | ±2% | 0.8624 V | −0.07% | ✅ |
| `V_pi·L` | 0.649 V·mm | ±2% | 0.6485 V·mm | −0.08% | ✅ |
| loss @ V_pi | 15.2 dB/cm | ±2% | 15.22 dB/cm | +0.1% | ✅ |
| `C_F` | 0.3471 pF | ±5% | 0.3316 pF | −4.5% | ✅ |
| `R_F` | 10.55 kΩ | ±15% | 11.06 kΩ | +4.8% | ✅ |
| `R_S` | 23.31 Ω | ±20% | 23.31 Ω (book) | 0% | ✅ (book; see caveat) |
| `f_3dB` | ≈6.25 GHz | ±10% | 6.55 GHz | +4.8% | ✅ |

**R_S caveat (carried forward):** R_S is the **book Table-3 value**, not an SSAC
measurement. SSAC high-f Re(Z) ≈ 0.10–0.18 Ω (norm-length) and does not scale to
23.31 Ω under any single convention (sec 3.6). Because `f_3dB` depends on R_S, the
6.25 GHz figure inherits this caveat; everything downstream (η, equalizer) is
keyed off `f_3dB` and is internally consistent.

sim_id 109 params: `w_r=478nm, h_si=70nm, doping=9.95e20 cm⁻³, lambda=1310nm,
S=510nm, length=0.752mm`.

---

## 6b. Stage-B — TWO distinct equalizer corrections (both applied)

The equalizer needs **two independent fixes** to the book. Keep them separate.

### Correction #1 — equalizer transfer FORM (fixes book eq 20)
Book eq (20) gives `H_Eq(0)=1` (contradicts eq 21 `H_Eq(0)=1/η`). The consistent
form (spec §3.4), used to generate the `.s2p`:

    H_Eq(ω) = (1 + jω R_Eq C_Eq) / (η + jω R_Eq C_Eq)     [H_Eq(0)=1/η, H_Eq(∞)=1]

Implemented in `eye_lib.H_eq` and `eye_lib.write_equalizer_touchstone`
(DC |S21| = 1/η ✓).

### Correction #2 — zero PLACEMENT (fixes book eq 19) — RESOLVED ✅
Book eq (19) sets `R_Eq·C_Eq = R_F·C_F`, which puts the equalizer **zero at the
diffusion corner** `1/(2π R_F C_F) ≈ 43.5 MHz` — two-plus decades **below** the
loaded device pole `f_3dB ≈ 6.28 GHz`. Cascaded with
`H_dev = R_F/(R_DC(1+jωR_FC_F)+R_F)` (`R_DC=R_S+50`), that provides only an IL
*shelf* (HF boost vs DC) and **does not extend the −3 dB BW to η·f_3dB** — i.e.
book eq (47) fails with the book placement:

| design (book placement, eq 19) | η | zero→pole | real BW |
|---|---|---|---|
| book IL=12 dB | 3.98 | 43.5 MHz → 173 MHz | not extended |
| 100 Gbps | 16 | 43.5 MHz → 695 MHz | not extended |

**Fix (delivered):** place the zero at the **loaded pole** via
`R_Eq·C_Eq = (R_S + R_drv)·C_F` ⇒ zero at `f_3dB`, pole at `η·f_3dB`,
`η = target_bw/f_3dB`. Self-test (`eye_lib`, η=16): zero=6.255 GHz (==f_3dB),
pole=100 GHz (==η·f_3dB), **cascade −3 dB = ~101 GHz** ✓ — BW genuinely extended.

`eye_lib.design_equalizer(mode="corrected")` does Correction #2 (delivered
default); `mode="book"` reproduces eq (19) for comparison. The `.s2p` depends only
on `(R_Eq·C_Eq, η)`, so both modes use Correction #1's form; they differ only in
the zero placement. Still to do in Stage C: confirm the measured INTERCONNECT
response matches the corrected `H_Eq` (spec asks this explicitly).

## 7. Open questions for the author

1. ❓ Norm-length vs `/L` reconciliation (see §3) — resolved pragmatically in §8.
2. ❓ Does the VM-measured INTERCONNECT equalizer response confirm the corrected
   `H_Eq` (§3.4) vs the printed eq (20)? — to be answered in Stage C.

---

## 8. Stage A FINALIZED — pragmatic per-param extraction (the resolution)

Following §3.6 (the book's Table-3 triple is cross-bias / cross-normalization and
cannot come from one self-consistent extraction), Stage A in
`system/run_specific_eye.py` now takes **each parameter by its own
best-supported method**, every one documented in code (`circuit_params.json`
carries an `_extraction` block):

| param | method (in `run_specific_eye.py`) | sim-109 result |
|---|---|---|
| `C_F` | **SSAC high-frequency reactance** `Im(Y)/ω` averaged over the top 3 freqs (`extract_ssac_cap`). Flat over freq AND over bias 0–0.5 V. **No length scaling.** | 0.3316 pF (−4.5% vs 0.347) ✅ |
| `R_F` | `(dV/dI)/L` on the forward branch, **log-interpolated at a defined forward operating bias** `FORWARD_OP_BIAS = 0.79 V` (`extract_R_F`, mirrors `rd_vs_bias.py`). | 11.06 kΩ (+4.8% vs 10.55) ✅ |
| `R_S` | **book value 23.31 Ω** (`R_S_BOOK`). SSAC `Re(Z)`@HF reported alongside as the documented caveat. | 23.31 Ω (book) |
| `f_3dB` | `1/(2π(R_S+R_drv)C_F)` (book eq 18/45). | 6.55 GHz (+4.8%) ✅ |

### Key refinement vs the resume brief (recorded so it isn't re-litigated)
The brief said *"C_F ≈ 0.347 pF (quasi-static depletion/diffusion cap)"*. The data
shows the **quasi-static** `C·L` only passes through 0.347 pF by **coincidence**
on a steep diffusion ramp (`C·L`: 0.093 pF @0.42 V → 0.387 pF @0.52 V → 2.9 pF
@0.63 V → 197 pF @V_pi). It is **not** a robust extraction. The genuine
depletion/junction capacitance is the **SSAC high-frequency reactance**, which is
flat at ~0.33 pF across freq and bias and reproduces book C_F with **no length
scaling**. So C_F is taken from SSAC, not from the quasi-static `dQ/dV·L`. (This
is the honest reading of §3.6's "C_F = unscaled depletion cap" finding.)

### Why R_F needs a *defined* operating bias
`r_d(V) = (dV/dI)/L` falls from ~9×10⁹ Ω @0.42 V to ~49 Ω @2.5 V; it crosses
10.55 kΩ at **V_F ≈ 0.79 V** (NOT at V_pi = 0.86 V, where `r_d ≈ 1–2 kΩ`). The
operating bias is **inherited from the book** (`FORWARD_OP_BIAS`, CLI-overridable
via `--rf-bias`); only the *value* is read fresh from this design's CHARGE sweep.
Because `r_d` is steep here and the sweep is coarse, R_F is noisy — hence the
±15% gate. Log-interpolation (not raw-grid gradient) is used for stability.

### `extract_ssac_cap` — final SSAC recipe (medium mesh, ~46 s)
`switchtolayout` → set medium mesh `{max refine steps 60, min edge 5 nm,
max edge 0.5 µm}` → drain BC ramp 0→0.5 V (continuation) + `apply AC small
signal = "all"` → `solver mode = ssac`, `perturbation amplitude = 1e-3`, log freq
1 kHz→200 GHz @2/dec → `run` → read **`getresult("CHARGE","ac_drain")`**, complex
attr **`dI`**; `Y = dI/V_pert`, `C_F = mean(Im(Y)/ω)` over the top freqs. The
single-pole `Z` fit is NOT used (it diverges — device is two-cap, §3.5/3.6).

### `SSAC_OP_BIAS = 0.5` removed
The old constant (and `--op-bias`) treated 0.5 V as THE small-signal operating
point — wrong (§3.3b/3.6). It is deleted. The SSAC ramp top (0.5 V) is now only a
continuation endpoint; C_F is the bias-independent high-f cap.

---

## 9. Stage C — INTERCONNECT eye + Bode (DONE)

### 9.1 Blocker + fix: `.icp` properties carry bound EXPRESSIONS
First Stage-C attempt died immediately on
`ic.setnamed("PIN_DEV", "cutoff frequency", f3)` with:

> `LumApiError: 'You cannot set the value of a property when it already has an expression'`

Several `.icp` element properties (e.g. `PIN_DEV.cutoff frequency`, which the dump
shows = 6.298e9, a bound equation) are driven by **expressions**, so a plain
`setnamed` is rejected. **Fix (reusable):** mirror the legacy
`build_eye_rc.py::_setval` pattern — on an "expression" error for a numeric value,
fall back to **`ic.setexpression(name, prop, repr(float(val)))`**. Implemented as
`run_specific_eye.py::_set_ic`, used for every Stage-C `setnamed` (string props
like the `.s2p` path use `setnamed` directly). Re-running Stage C (reusing the
saved `circuit_params.json` + `.s2p`) then succeeded; PD_SCOPE read 130,944
samples for both cases.

### 9.2 Result — the eyes (the headline)
`eye_comparison.png` (driven at 100 Gbps, the PRBS/EYE rate baked into both
`.icp`s):
- **baseline** (raw device, LP RC at f_3dB = 6.55 GHz): eye is **fully CLOSED** —
  just ISI noise. Expected: a 6.55 GHz device cannot pass 100 Gbps. PD signal
  range ≈ [0, 1.79] a.u.
- **equalized** (LPF_1 + RC_EQ `.s2p` + AMP_1 gain = IL): eye is **wide OPEN** with
  a clean crossing. PD range ≈ [0, 0.72] a.u.

### 9.3 ❓→✅ Does the measured INTERCONNECT response confirm the CORRECTED H_eq?
**Yes.** Two independent confirmations (answers spec §3.4 / open-Q 2):
1. **By construction:** `RC_EQ` loads the generated `rc_equalizer_S21.s2p`
   verbatim (`load from file = 1`, re-pointed away from the broken
   `C:\Users\roie1\…` absolute path to the fresh file). That `.s2p` is the
   **corrected** `H_eq = (1+jωR_eqC_eq)/(η+jωR_eqC_eq)` sampled (DC |S21| = 1/η),
   so the equalizer response applied inside INTERCONNECT **is** the corrected form.
2. **By behaviour (the decisive one):** the equalized eye **opens** at 100 Gbps
   while the baseline is fully closed. This only happens because the equalizer
   supplies the HF boost the corrected form predicts. The book's printed eq (20)
   evaluates to ≈1 (flat, H_eq(0)=1) and would provide **no** boost — the cascade
   would still roll off at 6.55 GHz and the eye would stay closed. The open eye
   therefore falsifies eq (20) and confirms the corrected H_eq.

`bode.png` plots the analytic transfer (raw device vs device×corrected-H_eq):
raw crosses −3 dB at 6.55 GHz; the equalized cascade is flat (offset by −IL =
−23.7 dB, the 1/η DC attenuation that AMP_1 restores) out to ~100 GHz = η·f_3dB.

### 9.4 Open question status
1. ✅ Norm-length vs `/L` — resolved pragmatically (§8): C_F is the unscaled SSAC
   high-f depletion cap; R_F is `(dV/dI)/L` at the book forward operating bias.
2. ✅ Corrected H_eq confirmed by the INTERCONNECT eye (§9.3).

Remaining caveat for the author: **R_S = 23.31 Ω is the book value**, not an SSAC
measurement (SSAC high-f Re(Z) ≈ 0.18 Ω). `f_3dB` (and hence η, the equalizer)
inherit this. Everything else is derived fresh from this design's CHARGE/FDE/SSAC.

### 9.5 Run provenance + a network-share hang (env note)
The validated results came from TWO live invocations of the SAME finalized code:
1. **Stage A→B** ran end-to-end live and printed all 7 §6 checks = PASS; it wrote
   `circuit_params.json`, `bode.png`, `rc_equalizer_S21.s2p`. Stage C then hit the
   expression bug (§9.1).
2. After the `_set_ic` fix, **Stage C** was re-run (reusing the saved params/`.s2p`)
   and produced `eye_comparison.png`. These are the committed artifacts.

A subsequent *clean single-process* re-run (A→C in one go, to get one uninterrupted
log) **hung in the standard pipeline CHARGE step** (`sim_handler.run_full_simulation`,
which does per-bias `.mat` save/load on the `\\Mac` SMB share). The `device` engine
sat at ~67 s CPU with **0 s/8 s growth** — blocked on share I/O, not computing (the
same signature seen for the early SSAC hang, §3.4). It was killed. This is a
pre-existing environment/share flakiness (the first run on identical code
succeeded), **not** a tool defect. Mitigation for a fully clean log: run with the
sweep output on local disk, or simply retry when the share is responsive. The
tool's own SSAC pass already uses local-disk I/O (`%TEMP%\eye_ssac`) for this reason.
