# eye_diagram_tool/ — INTERCONNECT eye-diagram + small-signal tooling

Consolidated code + knowledge for the PIN phase-shifter eye-diagram / RC-equalizer
work. Two tracks live here:

## Track 1 — FIXED book-value eye (stable deliverable, on remote)

`../analysis/plot_eye_diagram_interconnect.py` (kept in `analysis/`, matching
`origin/main`) — loads the **prebuilt INTERCONNECT `.icp`** circuits (in
`../Lumerical_Files/eye_rc_interconnect/`, which already encode the book's Table-3
R/C via the LP-filter cutoff + the equalizer `.s2p`), runs the transient, and plots
the baseline + equalized eyes. Reproduces the book design
(raw `f_3dB ≈ 6.25 GHz` → equalized `≈ 24.9 GHz`). The `.icp`, `.s2p`, this script,
and `EYE_TOOL_SPEC.md` are committed/pushed on `origin/main`.

## Track 2 — DYNAMIC SSAC self-consistent extraction (WIP, LOCAL ONLY — set aside)

Computes the small-signal circuit per `sim_id` from a fresh CHARGE+FDE+SSAC run,
with **no book values forced**:
- `run_specific_eye.py` — Stage A (CHARGE→FDE→SSAC) → Stage B (equalizer) → Stage C (INTERCONNECT eye).
- `run_specific_eye_walkthrough.py` — interactive, step-by-step (Enter-gated, prints formula + substitution).
- `eye_lib.py` — `extract_small_signal`, `H_device`, `H_eq`, `design_equalizer`, Touchstone writer, eye-fold/Bode helpers.

> ⚠️ **Key finding (see `RESEARCH_FINDINGS.md`):** the SSAC extraction shows the real
> forward-injection modulation bandwidth is **~0.6–0.8 GHz** (limited by the forward
> *diffusion* capacitance ~3–4 pF), **not 6.25 GHz**. The book's `C_F = 0.347 pF` /
> `6.25 GHz` are the *depletion*-capacitance values — the wrong regime for forward
> carrier injection. This is committed **locally only** (not pushed); deal with later.

These three scripts import the optimization pipeline (`config`, `sim_handler`,
`data_processor`) from `../system/` — they add `../system` to `sys.path` at startup,
so they run from this folder. They require Lumerical (CHARGE/FDE/INTERCONNECT).

## Knowledge / docs
- `EYE_TOOL_SPEC.md` — the build spec (book formulas, .icp element map, SSAC method, the eq-19/eq-20 equalizer corrections).
- `EYE_TOOL_WORKLOG.md` — cross-run worklog (per-design 109/63 table, the diffusion-vs-depletion conclusion, units/normalization).
- `RESEARCH_FINDINGS.md` — literature verdict on which capacitance governs forward-injection bandwidth, with citations.
- `icp_structure.md` — dumped element/property map of the working `.icp` files.

## Utilities
- `dump_icp_structure.py` — list elements + tunable properties of an `.icp`.
- `check_icp_s2p_reference.py` — check whether an `.icp` keeps a live `.s2p` path.
- `rd_vs_bias.py` — forward-bias differential resistance `r_d = (dV/dI)/L` vs bias.

## Assets NOT moved here (referenced by path)
- INTERCONNECT models + equalizer S21: `../Lumerical_Files/eye_rc_interconnect/*.icp`, `*.s2p`.
- Per-`sim_id` SSAC outputs (eyes, Bode, `zy_bode.png`, `circuit_params.json`): `../results_archive/eye_<id>/`.
- Discovery scratch (probes, `.npz`): `./ssac_scratch/`.
