# Task Spec — Per-`sim_id` Eye-Diagram Tool (CHARGE → FDE → INTERCONNECT)

> Audience: a Claude Code session running **on the Windows VM with Lumerical
> installed** (CHARGE/DEVICE, MODE/FDE, INTERCONNECT + `lumapi`). You can run the
> Lumerical API directly, so build the tool **incrementally and self-test each
> stage** against the known reference (`sim_id 109`) before moving on.

---

## 0. Goal

Build a script that takes a **`sim_id`** and produces its **eye diagrams
(baseline + equalized) and a Bode plot**, driving the link at **100 Gbps**.

Hard requirement: the result must depend **only on the 6 simulation input
parameters** of that `sim_id` (geometry + doping + wavelength). Every resistance
and capacitance must be **derived from a fresh CHARGE/FDE run using the project
book's formulas** — never read precomputed circuit values from a CSV, and never
reuse another design's component values.

If any book formula looks wrong, **stop and report it** (see §3.4 for one already
found).

---

## 1. The tool

- **Location:** `system/run_specific_eye.py` (sibling of `system/run_specific_sim.py`; mirror its CLI/UX).
- **Input:** prompt for a results CSV path + a `sim_id` (exactly like `run_specific_sim.py`), read the 6 params: `w_r, h_si, doping, lambda, S, length`.
- **Outputs** → `results_archive/eye_<sim_id>/`:
  - `eye_baseline.png`, `eye_equalized.png` (or a combined figure)
  - `bode.png` (raw device vs equalized, mark `f_3dB`)
  - `rc_equalizer_S21.s2p` (generated for this design)
  - `circuit_params.json` (the extracted `C_F, R_F, R_S, V_pi, f_3dB`, plus equalizer `eta, R_Eq, C_Eq`)
  - the raw CHARGE/FDE sweep (as `run_specific_sim.py` already writes)
- **English only** in code/comments/output (repo + remote convention).
- **Do not modify** the optimization pipeline behaviour (`main.py`, `BO.py`, `cost.py`). Reuse `sim_handler`, `run_simulation`, `data_processor` read-only where possible; add new code in the new file or a new helper.

---

## 2. Pipeline (three stages — test each before the next)

### Stage A — extract device parameters (CHARGE + FDE)
From a fresh run of the design's params:
- **`C_F`** — diffusion capacitance. Book eq (15): `C_F = dQ/dV`. The pipeline
  already computes `C_total_pF_cm = d(q·n)/dV + d(q·p)/dV` (`data_processor.process_charge_data`).
  Take its value **at `V_pi`** and convert to an absolute capacitance for length `L`:
  `C_F[F] = C_at_v_pi[pF/cm] × (L[cm]) × 1e-12`.  (Confirm the cm↔m bookkeeping against the sim-109 target below.)
- **`R_F`** — junction differential resistance. Book definition: `R_F = dV/dI` at
  the operating bias. Use the swept terminal current `I` (now extracted by
  `sim_handler.extract_charge_current`) and evaluate `dV/dI` at `V_pi`.
- **`R_S`** — series access resistance. Book method = real part of the impedance
  at high frequency from an **SSAC** analysis (see §5). Implement SSAC; also
  compute the **DC high-bias asymptote of `dV/dI`** as an independent cross-check.
- **`V_pi`** — from FDE: `data_processor.calculate_v_pi` (interp of |Δφ|(V) at π).
- **`f_3dB`** — book eq (18)/(45): `f_3dB = 1 / (2π (R_S + R_drv) C_F)`, with `R_drv = 50 Ω`.

> **UNITS CAVEAT (critical):** CHARGE here appears to report current **per unit
> length** (A/m). The per-device differential resistance is therefore
> `R = (dV/dI_from_CHARGE) / L`. This was validated empirically: dividing by
> `L = 0.752 mm` makes `R_F` cross `10.55 kΩ` near `V_pi` for sim 109 (without
> dividing it would be ~7.9 Ω, far from the book). The same `/L` applies to `R_S`
> from SSAC (`Z` would be Ω·m). **Verify the convention** by checking the CHARGE
> solver's norm/2D-length setting AND by reproducing Table 3 (§6).

### Stage B — design the equalizer for 100 Gbps
Book equations (§3.2). Given the device (`R_F, C_F, f_3dB`) and a target:
- `eta = 10^(IL_dB / 20)` (eq 46), `R_Eq = R_F · eta` (eq 48), `C_Eq = C_F / eta` (eq 49).
- Zero-pole cancellation invariant (eq 19): `R_Eq · C_Eq = R_F · C_F` (use as a self-check).
- Equalized bandwidth `f_3dB,Eq = eta · f_3dB` (eq 47).
- Generate the equalizer **Touchstone `.s2p`** from the corrected transfer
  function (§3.4) over a frequency grid (reuse/adapt `legacy/eye_rc_analysis/eye_rc_interconnect/build_eye_rc.py::write_equalizer_touchstone` + `H_eq`, but with the **corrected** `H_Eq`).
- **100 Gbps target (decided):** design the equalizer so the equalized
  bandwidth reaches the **full bit rate: `f_3dB,Eq = 100 GHz`**. Therefore size
  `η` **per design** from the extracted device bandwidth:
  `η = f_3dB,Eq / f_3dB = 100 GHz / f_3dB`. For sim 109 (`f_3dB ≈ 6.25 GHz`) this
  gives `η ≈ 16`, `IL = 20·log10(η) ≈ 24 dB`, `R_Eq = R_F·16 ≈ 169 kΩ`,
  `C_Eq = C_F/16 ≈ 21.7 fF`. This is aggressive: the insertion loss is large and
  must be compensated by the downstream `AMP_1`/`TIA_1` gain (set `AMP_1.gain ≈ IL_dB`).
  Keep `--target-bw` overridable (default 100 GHz) but **do not** silently cap or
  reduce the target. **Print a warning** that the raw (un-equalized) eye at
  100 Gbps will be essentially closed and that the equalized eye carries this IL.

### Stage C — INTERCONNECT eye + Bode
Load the **working prebuilt `.icp`** (do NOT rebuild from the legacy builder — it
was wrong) and update component values in place (§4). Then run the transient and
read the scope to plot the eye; compute the electrical transfer for the Bode.
Reuse `analysis/plot_eye_diagram_interconnect.py` (load → run → read PD_SCOPE →
plot eye) and the Bode logic from the legacy `build_eye_rc.py`
(`measure_transfer` / analytic `H_base`,`H_eq`).

---

## 3. Authoritative formulas (project book)

`R_drv = 50 Ω` throughout.

### 3.1 Device small-signal circuit
- (13) `Z(ω) = R_S + R_F / (1 + jω R_F C_F)`
- (15) `C_F = dQ/dV`     (16) `C_F = τ/R_F`     (17) `τ_diode = R_F C_F`
- (18)/(45) `f_3dB = 1 / (2π (R_S + R_drv) C_F)`  ⇒ ≈ 6.25 GHz for sim 109

### 3.2 Equalizer design (zero-pole cancellation)
- (19) `R_Eq C_Eq = R_F C_F`
- (46) `IL_dB = 20·log10(1/η)` ⇒ `η = 10^(IL_dB/20)`   (η = 3.98 at IL = 12 dB)
- (47) `f_3dB,Eq = η · f_3dB`   (≈ 24.9 GHz for the book design)
- (48) `R_Eq = R_F · η`         (49) `C_Eq = C_F / η`

### 3.3 Equalizer frequency response (Bode / noise)
- (21) `H_Eq(0) = 1/η`    (22) `H_Eq(∞) → 1`    (24) noise ratio `= η²`

### 3.4 ⚠️ KNOWN BOOK ERROR — equalizer transfer eq (20)
The book prints:
`H_Eq(ω) = (1 + jω R_Eq C_Eq) / (1 + jω (R_drv+R_S+R_Eq) C_Eq)`
Evaluated at ω=0 this gives **1**, contradicting eq (21) `H_Eq(0)=1/η`, and with
`R_Eq ≫ R_drv+R_S` it is essentially flat ≈1 — it does **not** reproduce the
−12 dB→0 dB shelf in the book's Bode (Fig. 17).
**Use this consistent form instead** (matches eqs 19/21/22 and Fig. 17):
```
H_Eq(ω) = (1 + jω R_Eq C_Eq) / (η + jω R_Eq C_Eq)
```
`H_Eq(0)=1/η` ✓, `H_Eq(∞)=1` ✓. Generate the `.s2p` from this. (Flag in your
report whether the VM-measured INTERCONNECT response confirms this form.)

---

## 4. `.icp` element map (from `analysis/icp_structure.md`, already dumped on the VM)

Both circuits run at **100 Gbps** (PRBS + Eye already set to 1e11). Set per `sim_id`:

| Element | Type | Property to set | Set to |
|---|---|---|---|
| `PIN_DEV` (baseline) / `LPF_1` (equalized) | LP RC Filter | `cutoff frequency` | `f_3dB` (Stage A) |
| `RC_EQ` (equalized only) | Electrical N Port S-Parameter | `s parameters filename` + `load from file`=1 | path to the **generated** `.s2p` (Stage B) |
| `NRZ_1` | NRZ Pulse Generator | `amplitude` | `V_pi` |
| `DC_1` (baseline) | DC Source | `amplitude` | bias for MZM quadrature (≈ −V_pi/2; confirm sign vs current −0.431) |
| `AMP_1` (equalized) | Electrical Amplifier | `gain` | compensate equalizer IL = `20·log10(η)` (was 24.08 dB for η≈... confirm) |

> ⚠️ The equalized `.icp` ships with `RC_EQ.s parameters filename` =
> `C:\Users\roie1\Desktop\...\rc_equalizer_S21.s2p` — an **absolute path on the
> original author's machine** that is broken on this VM. You **must** re-point it
> to the freshly generated `.s2p`.

Use `getnamed`/`setnamed` with the names above. Re-dump with
`analysis/dump_icp_structure.py` if anything mismatches.

---

## 5. `R_S` via SSAC — how to find the exact API

Use the **`lumapi-docs` skill** (`.claude/skills/lumapi-docs`) to look up the
exact CHARGE SSAC calls in `lomapi_python/docs.json` / `lumapi.py`:
- search for: `ssac`, `solver mode`, `small signal`, `frequency`, contact current results.
- CHARGE supports `solver mode = "ssac"` with an SSAC perturbation amplitude and a
  frequency (or frequency sweep); applied at the last bias point.

Method (book §4.2.1): run SSAC at the operating bias, sweep/evaluate at a **high
frequency (≈100 GHz)** where `C_F` shorts `R_F`, so `Z(f_high) → R_S`. Extract
`R_S = Re(Z(f_high))` (then `/L`, see units caveat). Cross-check against the DC
high-bias asymptote of `dV/dI`. **Report both** and whether they agree, and
whether they match the sim-109 reference.

If SSAC turns out infeasible on this `.ldev`, fall back to the DC high-bias
asymptote and clearly flag the deviation from the book method.

---

## 6. Validation / acceptance tests

Reference design **`sim_id 109`** (params: `w_r=478nm, h_si=70nm,
doping=9.95e20 cm⁻³, lambda=1310nm, S=510nm, length=0.752mm`). It must reproduce
**Table 3 + Table 2** within tolerance:

| Quantity | Target | Tol |
|---|---|---|
| `V_pi` | 0.863 V | ±2% |
| `V_pi·L` | 0.649 V·mm | ±2% |
| loss @ V_pi | 15.2 dB/cm | ±2% |
| `C_F` | 0.3471 pF | ±5% |
| `R_F` | 10.55 kΩ | ±15% (noisy; coarse sweep) |
| `R_S` | 23.31 Ω | ±20% (SSAC) |
| `f_3dB` | ≈6.25 GHz | ±10% |

Gate each stage on these before proceeding. For fast iteration you may reuse the
cached results already in `Lumerical_Files/` (`charge_data.mat`,
`PIN_Ref_phase_shifter_voltage/voltage_*.lms`) instead of re-running the heavy
sims. The equalized run at the book design (`IL=12 dB`, `η=3.98`) should give
`f_3dB,Eq ≈ 24.9 GHz`; the 100 Gbps design will be much wider with large IL.

Also verify: does the VM-measured INTERCONNECT equalizer response confirm the
**corrected** `H_Eq` (§3.4), not the printed eq (20)?

---

## 7. Code to reuse

- `system/sim_handler.py` — CHARGE/FDE setup + run (`set_charge_parameters`,
  `run_full_simulation`, `extract_charge_current`). Only module that touches `lumapi`.
- `system/run_simulation.py::run_row` — runs CHARGE→FDE, returns the result dict
  (`v_pi_V`, `v_pi_l_Vmm`, `loss...`, `C_at_v_pi_pF_per_cm`, ...) and writes the raw sweep CSV.
- `system/data_processor.py` — `process_charge_data` (C), `process_optical_data`/`calculate_v_pi`.
- `system/run_specific_sim.py` — the CLI/UX pattern to mirror.
- `analysis/plot_eye_diagram_interconnect.py` — load `.icp` → run → read PD_SCOPE → plot eye (paths already point at `Lumerical_Files/eye_rc_interconnect/`).
- `analysis/rd_vs_bias.py` — `dV/dI` extraction logic for `R_F`.
- `legacy/eye_rc_analysis/eye_rc_interconnect/build_eye_rc.py` — `write_equalizer_touchstone`, `H_eq`, `H_base`, `measure_transfer`, eye-fold metrics, Bode plotting. (Reference only; the circuit-build part was wrong — use the prebuilt `.icp`.)

---

## 8. Conventions / guardrails

- English only; new file `system/run_specific_eye.py`; outputs under `results_archive/eye_<sim_id>/`.
- `.icp`, `.s2p` are LFS-tracked (`.gitattributes`); the eye assets live in `Lumerical_Files/eye_rc_interconnect/`.
- Don't commit large per-run outputs unless asked.
- Keep the optimization pipeline untouched.
- When a book formula and a measurement disagree, **report it** rather than fudging numbers.

---

## 9. Decided parameters

- **Bit rate: 100 Gbps** (PRBS + Eye already set to 1e11; keep).
- **Equalizer target: `f_3dB,Eq = 100 GHz`** (full bit rate), `η` sized per design
  (`η = 100 GHz / f_3dB`). See Stage B. Expect a closed raw eye and a large IL on
  the equalized eye — this is the honest result, report it as-is.

---

## 10. Work log — REQUIRED

Maintain a running journal at **`results_archive/eye_<sim_id>/WORKLOG.md`** (and a
top-level `EYE_TOOL_WORKLOG.md` summarizing across runs). Document as you go — not
only the final answer:

- **Attempts:** each thing you tried (API calls, SSAC settings, `.icp` property
  names, equalizer grids), with enough detail to reproduce.
- **Failures / blockers:** the exact error or wrong result, what it
  looked like (paste the message / the off value), and your hypothesis.
- **Resolutions:** what fixed it and *why* — especially for the parts flagged as
  uncertain here: the **SSAC API + result keys**, the **A/m units / `/L`
  convention**, the **`.icp` element/property names**, and whether the measured
  INTERCONNECT equalizer response matched the **corrected** `H_Eq` (§3.4) vs the
  printed eq (20).
- **Validation:** record each sim-109 check vs the §6 table (got / target / Δ /
  pass-fail) per stage.
- **Open questions** for the author.

Write the log in English. Treat it as the primary deliverable alongside the tool:
the discovered SSAC API and units convention are reusable knowledge for the rest
of the project.
