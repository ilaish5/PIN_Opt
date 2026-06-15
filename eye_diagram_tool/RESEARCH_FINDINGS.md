# Which capacitance governs forward-injection bandwidth? — literature verdict

**Question:** For a forward-biased PIN (carrier-injection) silicon MZM / phase
shifter, does the small-signal modulation bandwidth depend on the junction
**depletion** capacitance or the forward **diffusion** (charge-storage) capacitance?

**Verdict (high confidence; deep-research, 23/25 claims confirmed by 3-vote
adversarial verification):**

> In forward-bias carrier injection, the modulation bandwidth is governed by the
> **DIFFUSION capacitance and the minority-carrier recombination lifetime τ**, NOT
> the depletion capacitance. Intrinsic (un-equalized) forward-injection bandwidth is
> **~hundreds of MHz to ~1 GHz**. The depletion capacitance / RC limit applies only
> in **reverse-bias depletion-mode** devices (which reach tens of GHz). Forward-
> injection devices reach ~12–20 Gb/s only with **pre-emphasis / RC peaking /
> pre-distortion**.

## What this means for our reference document
- The reference used `C_F = 0.347 pF` → `f_3dB = 6.25 GHz`. That `C` is the
  **depletion/junction capacitance** (the diode is ~off at the extraction bias).
- The physically correct capacitance for the forward operating point is the
  **diffusion capacitance** `C_diff = g_m·τ = τ/r_d` (~3–4 pF in our SSAC), giving
  `f_3dB ≈ 0.6–0.8 GHz`.
- Same formula `f_3dB = 1/(2π(R_S+R_drv)C)`, **wrong capacitance** plugged in
  (depletion instead of diffusion) → ~8–10× bandwidth overestimate. This is a
  *regime* error, not a normalization error.

## Our SSAC simulation (confirms the literature)
| design | R_S | R_F | C_diff | C_dep | f_3dB,diff | f_3dB,dep |
|---|---|---|---|---|---|---|
| sim 109 | 10.3 Ω | 11.36 kΩ | 3.40 pF | 0.024 pF | **0.78 GHz** | 97–108 GHz |
| sim 63  | 11.85 Ω | 5.65 kΩ | 4.20 pF | 0.024 pF | **0.61 GHz** | 109 GHz |

Both land in the literature's ~0.6–0.8 GHz forward-injection range. Values differ
per design (physics, not forced book values).

## Standard small-signal model
`Z(ω) = R_S + R_F ∥ (1/jω(C_dep + C_diff))`, with `C_diff = g_m·τ = τ/r_d` arising
specifically under forward bias (minority-carrier charge storage). At the forward
operating point `C_diff ≫ C_dep`, so the diffusion cap dominates the bandwidth.

## Sources (peer-reviewed; prioritized)
- **Q. Xu, S. Manipatruni, B. Schmidt, J. Shakya, M. Lipson**, "12.5 Gbit/s
  carrier-injection-based silicon micro-ring silicon modulators," *Opt. Express*
  **15**(2), 430 (2007). https://opg.optica.org/oe/abstract.cfm?uri=OE-15-2-430
- **A. Liu et al. (Intel)**, *Opt. Express* **15**(2), 660 (2007).
  https://opg.optica.org/oe/fulltext.cfm?uri=oe-15-2-660
- **G. T. Reed, G. Mashanovich, F. Y. Gardes, D. J. Thomson**, "Silicon optical
  modulators," *Nature Photonics* **4**, 518 (2010).
  https://www.nature.com/articles/nphoton.2010.179
- **D. Marris-Morini et al.**, *Opt. Express* **16**(1), 334 (2008).
  https://opg.optica.org/oe/fulltext.cfm?uri=oe-16-1-334
- **Wu et al.**, *Opt. Express* **23**(12), 15545 (2015).
  https://opg.optica.org/oe/fulltext.cfm?uri=oe-23-12-15545
- **Mu et al. (2023)**, PMC10456945. https://pmc.ncbi.nlm.nih.gov/articles/PMC10456945/
- **S. Manipatruni, Q. Xu, M. Lipson**, pre-emphasis / high-speed carrier injection
  (IEEE doc 4382517; PubMed 19532260).
- Diffusion-capacitance definition `C_diff = g_m·τ`: standard device physics
  (e.g., Wikipedia "Diffusion capacitance", secondary).

*Caveats:* RC- and lifetime-framings of the limit are equivalent. Some forward
demonstrations are micro-rings rather than MZMs. Two supporting claims (forward/
reverse cap ratio ~100×; ~10 pF forward cap) were down-weighted on source strength,
not physics. The core physics is settled.
