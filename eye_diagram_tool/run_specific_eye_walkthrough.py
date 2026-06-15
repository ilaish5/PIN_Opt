# system/run_specific_eye_walkthrough.py
#
# Interactive, step-by-step WALKTHROUGH of the per-sim_id eye pipeline. A human
# watches the whole CHARGE -> FDE -> SSAC -> equalizer -> INTERCONNECT flow unfold
# one Enter-gated step at a time, with Formula / Substitute / Result for every
# computed value.
#
# This is a PRESENTATION LAYER only -- it reuses the exact same functions, numbers
# and methods as the validated run_specific_eye.py + eye_lib.py (no new physics).
# The CHARGE and FDE halves are split into two gated steps using the same
# sim_handler primitives that run_full_simulation calls, in the same order.
#
# Usage:
#   python run_specific_eye_walkthrough.py --csv <results.csv> --sim-id 109
#   python run_specific_eye_walkthrough.py --csv ... --sim-id 109 --no-pause   # no gating
#
# English only.

import os
import sys
import time
import argparse

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))   # eye_diagram_tool/
ROOT = os.path.dirname(HERE)                          # PS_Opt_V2/
# eye_lib + run_specific_eye live here; config/sim_handler/data_processor in system/.
for _p in (HERE, os.path.join(ROOT, "system")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config
import sim_handler
import data_processor
import eye_lib
import run_specific_eye as rse           # reuse all validated run functions

sys.path.append(config.LUMERICAL_API_PATH)
try:
    import lumapi
except ImportError:
    lumapi = None

SEP = "=" * 74


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

def _gate(n, title, no_pause, run_hint=None):
    """Show 'STEP n -- title' and wait for Enter (unless --no-pause)."""
    prompt = f"\n[Enter] STEP {n} -- {title}"
    if run_hint:
        prompt += f"   ({run_hint})"
    if no_pause:
        print(f"\nSTEP {n} -- {title}")
    else:
        try:
            input(prompt)
        except EOFError:
            print(f"\nSTEP {n} -- {title}")
    print("-" * 74)


def step(n, title, formula, substitute, result, no_pause):
    """A COMPUTED step: gate, then print Formula / Substitute / Result."""
    _gate(n, title, no_pause)
    print(f"  Formula:    {formula}")
    print(f"  Substitute: {substitute}")
    print(f"  Result:     {result}")


def summary(*lines):
    for ln in lines:
        print(f"  {ln}")


# ---------------------------------------------------------------------------
# CHARGE / FDE split (mirrors sim_handler.run_full_simulation, same primitives)
# ---------------------------------------------------------------------------

def _run_charge(params, hide):
    """CHARGE half of run_full_simulation: load -> set -> run -> extract -> close."""
    dev = lumapi.DEVICE(hide=hide)
    try:
        dev.load(config.CHARGE_SIM_FILE)
        sim_handler.set_charge_parameters(dev, params, config.CHARGE_DATA_FILE)
        t0 = time.time()
        sim_handler.run_charge_simulation(dev)
        dt = time.time() - t0
        data = sim_handler.extract_raw_charge_data(dev)   # V_drain, n, p, (I)
    finally:
        try:
            dev.close()
        except Exception:
            pass
    return data, dt


def _run_fde(params, hide):
    """FDE half: load -> set -> import CHARGE .mat -> sweep -> extract -> close."""
    fde = lumapi.MODE(hide=hide)
    try:
        fde.load(config.FDE_SIM_FILE)
        sim_handler.set_fde_parameters(fde, params)
        sim_handler.import_charge_data(fde, config.CHARGE_DATA_FILE)
        t0 = time.time()
        sim_handler.run_fde_sweep(fde)
        dt = time.time() - t0
        data = sim_handler.extract_raw_optical_data(fde)  # neff
    finally:
        try:
            fde.close()
        except Exception:
            pass
    return data, dt


# ---------------------------------------------------------------------------
# Walkthrough
# ---------------------------------------------------------------------------

def walkthrough(params, sim_id, out_dir, args):
    no_pause = args.no_pause
    L = float(params["length"])
    hide = config.HIDE_GUI and not config.DEBUG
    print(f"\n{SEP}\n WALKTHROUGH -- per-sim_id eye pipeline (sim_id {sim_id})\n{SEP}")
    print("Same numbers/methods as run_specific_eye.py; this is a presentation layer.")

    # ----- STEP 1: parameters -----
    _gate(1, "Read sim_id and the 6 input parameters", no_pause)
    for c in rse.PARAM_COLS:
        print(f"    {c:<8} = {params[c]:.6g}")
    print(f"    output dir = {out_dir}")

    # ----- STEP 2: CHARGE -----
    _gate(2, "Run CHARGE (carrier / current solve)", no_pause,
          run_hint="Press Enter to run CHARGE")
    print("  ... running CHARGE ...", flush=True)
    cdata, charge_t = _run_charge(params, hide)
    V = np.asarray(cdata["V_drain"]).flatten()
    has_I = "I" in cdata and cdata["I"] is not None
    summary(f"CHARGE solved in {charge_t:.1f} s",
            f"bias sweep: {len(V)} points, V = {V.min():.2f} .. {V.max():.2f} V")
    if has_I:
        I = np.asarray(cdata["I"]).flatten()
        summary(f"terminal current I(V): {I.min():.2e} .. {I.max():.2e} A (per norm-length)")

    # ----- STEP 3: FDE -----
    _gate(3, "Run FDE (optical mode / neff sweep)", no_pause,
          run_hint="Press Enter to run FDE")
    print("  ... running FDE ...", flush=True)
    odata, fde_t = _run_fde(params, hide)
    neff = np.squeeze(odata["neff"])
    summary(f"FDE swept in {fde_t:.1f} s",
            f"neff: {len(np.atleast_1d(neff))} points, "
            f"Re(neff) = {np.real(neff).min():.4f} .. {np.real(neff).max():.4f}")

    # assemble the raw frame exactly like run_full_simulation
    raw_df = pd.DataFrame({
        "V": V, "n": np.asarray(cdata["n"]).flatten(), "p": np.asarray(cdata["p"]).flatten(),
        "neff_re": np.real(neff).flatten(), "neff_im": np.imag(neff).flatten()})
    if has_I:
        raw_df["I"] = np.asarray(cdata["I"]).flatten()

    # ----- STEP 4: V_pi, V_pi*L, loss -----
    V_cap, C_total = data_processor.process_charge_data(
        raw_df["V"].values, raw_df["n"].values, raw_df["p"].values)
    neff_c = raw_df["neff_re"].values + 1j * raw_df["neff_im"].values
    d_neff, alpha, d_phi, v_pi, max_dphi = data_processor.process_optical_data(
        neff_c, L, float(params["lambda"]))
    V_fde = np.linspace(0, config.V_MAX, len(d_neff))
    loss = float(np.interp(v_pi, V_fde, alpha))
    v_pi_l = v_pi * L * 1e3
    lam_nm = float(params["lambda"]) * 1e9
    step(4, "V_pi  (half-wave voltage)",
         "V_pi = interp of |dphi|(V) at dphi = pi   (dphi from FDE neff)",
         f"|dphi| reaches pi at V = {v_pi:.4f} V  (lambda = {lam_nm:.0f} nm)",
         f"V_pi = {v_pi:.4f} V", no_pause)
    step(4, "V_pi * L  (figure of merit)",
         "V_pi*L = V_pi * L",
         f"{v_pi:.4f} V * {L*1e3:.3f} mm",
         f"V_pi*L = {v_pi_l:.4f} V*mm", no_pause)
    step(4, "Optical loss at V_pi",
         "loss = interp of alpha(V) at V = V_pi   (alpha from Im(neff))",
         f"alpha(V = {v_pi:.3f} V)",
         f"loss = {loss:.2f} dB/cm", no_pause)

    # ----- STEP 5: forward-bias SSAC -----
    _gate(5, "Run forward-bias SSAC (small-signal Z(w))", no_pause,
          run_hint=f"Press Enter to run SSAC, ramp 0 -> {args.op_bias:.2f} V")
    print(f"  ... running SSAC (ramp to {args.op_bias:.2f} V, "
          f"{rse.SSAC_F_START:.0g} Hz .. {rse.SSAC_F_STOP:.0g} Hz) ...", flush=True)
    t0 = time.time()
    pic = rse.extract_ssac_circuit(params, op_bias=args.op_bias)
    f = pic["f"]
    summary(f"SSAC solved in {time.time()-t0:.1f} s",
            f"op bias = {pic['V']:.2f} V, {len(pic['bias_table'])} ramp points",
            f"frequency grid: {f.size} points, {f.min():.0f} Hz .. {f.max():.2e} Hz")

    # ----- STEP 6: length normalization -----
    factor = rse.NORM_LENGTH / L
    step(6, "Length normalization (2D -> device)",
         "Z_device(w) = Z_reported(w) * (norm / L)",
         f"norm = {rse.NORM_LENGTH} m,  L = {L:.3e} m  ->  norm/L = {rse.NORM_LENGTH}/{L:.3e}",
         f"scale factor = {factor:.2f}  (R x{factor:.2f}, C /{factor:.2f})", no_pause)

    # device-scaled arrays straight from the validated extractor
    Z, Y, C = pic["Z"], pic["Y"], pic["C"]
    R_S, R_F = pic["R_S"], pic["R_F"]
    C_diff, C_dep = pic["C_diff"], pic["C_dep"]
    w = 2 * np.pi * f
    Z_rep_hi = R_S / factor                         # reported value before scaling

    # ----- STEP 7: R_S -----
    step(7, "Series resistance R_S",
         "R_S = Re(Z_device) at f_max,   Z_device = Z_reported * (norm/L)",
         f"R_S = {Z_rep_hi:.4g} ohm * (norm/L) = {Z_rep_hi:.4g} * {factor:.2f}",
         f"R_S = {R_S:.2f} ohm", no_pause)

    # ----- STEP 8: R_F -----
    ReZ_lo = float(np.real(Z[0]))
    step(8, "Junction differential resistance R_F",
         "R_F = Re(Z_device) at low f  -  R_S",
         f"R_F = {ReZ_lo/1e3:.3f} kohm - {R_S:.2f} ohm",
         f"R_F = {R_F/1e3:.3f} kohm", no_pause)

    # ----- STEP 9: C_diff, C_dep -----
    ImY_lo, ImY_hi = float(np.imag(Y[0])), float(np.imag(Y[-1]))
    step(9, "Diffusion capacitance C_diff (low f)",
         "C_diff = Im(Y_device) / w   at low f   (forward injection cap)",
         f"{ImY_lo:.3e} S / (2*pi*{f[0]:.0f} Hz)",
         f"C_diff = {C_diff*1e12:.4f} pF", no_pause)
    step(9, "Depletion capacitance C_dep (high f)",
         "C_dep = Im(Y_device) / w   at high f   (junction cap)",
         f"{ImY_hi:.3e} S / (2*pi*{f[-1]:.2e} Hz)",
         f"C_dep = {C_dep*1e12:.5f} pF", no_pause)

    # ----- STEP 10: tau -----
    step(10, "Effective carrier time constant tau",
         "tau = R_F * C_diff",
         f"{R_F/1e3:.3f} kohm * {C_diff*1e12:.4f} pF",
         f"tau = {pic['tau']*1e9:.2f} ns", no_pause)

    # ----- STEP 11: bandwidths -----
    Rdc = R_S + rse.R_DRV
    step(11, "Forward-injection modulation BW f_3dB,diff",
         "f_3dB,diff = 1 / (2*pi*(R_S + R_drv)*C_diff)   <- PHYSICAL modulation BW",
         f"1 / (2*pi*({R_S:.2f}+{rse.R_DRV:.0f})*{C_diff*1e12:.4f}pF)",
         f"f_3dB,diff = {pic['f_3dB_diff']/1e9:.4f} GHz", no_pause)
    step(11, "Depletion-limited BW f_3dB,dep (reverse-bias only)",
         "f_3dB,dep = 1 / (2*pi*(R_S + R_drv)*C_dep)",
         f"1 / (2*pi*({R_S:.2f}+{rse.R_DRV:.0f})*{C_dep*1e12:.5f}pF)",
         f"f_3dB,dep = {pic['f_3dB_dep']/1e9:.2f} GHz", no_pause)

    # ----- STEP 12: equalizer -----
    f_3dB = pic["f_3dB_diff"]
    d = eye_lib.design_equalizer(R_F, C_diff, f_3dB, R_S=R_S,
                                 target_bw=args.target_bw, mode="corrected")
    eta = d["eta"]
    step(12, "Equalizer peaking factor eta",
         "eta = target_bw / f_3dB,diff",
         f"{args.target_bw/1e9:.0f} GHz / {f_3dB/1e9:.4f} GHz",
         f"eta = {eta:.2f}", no_pause)
    step(12, "Equalizer resistance R_eq",
         "R_eq = (R_S + R_drv) * eta",
         f"({R_S:.2f}+{rse.R_DRV:.0f}) ohm * {eta:.2f}",
         f"R_eq = {d['R_eq']:.1f} ohm", no_pause)
    step(12, "Equalizer capacitance C_eq",
         "C_eq = C_diff / eta",
         f"{C_diff*1e12:.4f} pF / {eta:.2f}",
         f"C_eq = {d['C_eq']*1e15:.2f} fF", no_pause)
    step(12, "Equalizer insertion loss IL",
         "IL = 20 * log10(eta)",
         f"20 * log10({eta:.2f})",
         f"IL = {d['IL_dB']:.2f} dB   (equalized BW -> {d['f_3dB_eq']/1e9:.0f} GHz)", no_pause)

    s2p = os.path.join(out_dir, "rc_equalizer_S21.s2p")
    eye_lib.write_equalizer_touchstone(s2p, d["R_eq"], d["C_eq"], eta,
                                       sample_rate=rse.BITRATE * 64)

    # circuit params for Stage C + plots (same shape as run_specific_eye)
    cp = {"V_pi": float(v_pi), "op_bias_V": pic["V"], "R_S": R_S, "R_F": R_F,
          "C_diff": C_diff, "C_dep": C_dep, "tau_ns": pic["tau"] * 1e9,
          "f_3dB": f_3dB, "f_3dB_diff": pic["f_3dB_diff"], "f_3dB_dep": pic["f_3dB_dep"],
          "eta": eta, "R_eq": d["R_eq"], "C_eq": d["C_eq"], "IL_dB": d["IL_dB"],
          "f_3dB_eq": d["f_3dB_eq"]}

    # ----- STEP 13: INTERCONNECT eye + Bode -----
    _gate(13, "Build & run INTERCONNECT, save eye + Bode", no_pause,
          run_hint="Press Enter to run INTERCONNECT")
    rse.plot_bode({**cp, "C_F": C_diff}, os.path.join(out_dir, "bode.png"))
    rse.plot_zy_bode(pic, os.path.join(out_dir, "zy_bode.png"))
    if args.no_interconnect:
        summary("INTERCONNECT skipped (--no-interconnect); bode.png + zy_bode.png written")
    else:
        print("  ... running INTERCONNECT (baseline + equalized transients) ...", flush=True)
        eyes = rse.drive_interconnect(cp, s2p, out_dir)
        rse.plot_eyes(eyes, os.path.join(out_dir, "eye_comparison.png"))
        summary("eye_comparison.png written (baseline dead / equalized open @ 100 Gbps)")
    summary("bode.png, zy_bode.png, rc_equalizer_S21.s2p written")

    print(f"\n{SEP}\n WALKTHROUGH complete. Outputs in {out_dir}\n{SEP}")


def main():
    ap = argparse.ArgumentParser(description="Interactive walkthrough of the eye pipeline")
    ap.add_argument("--csv", default=None, help="results CSV path")
    ap.add_argument("--sim-id", type=int, default=None)
    ap.add_argument("--target-bw", type=float, default=100e9,
                    help="equalized target bandwidth [Hz] (default 100 GHz)")
    ap.add_argument("--op-bias", type=float, default=rse.FORWARD_OP_BIAS,
                    help="forward operating bias for the SSAC extraction [V] (default 0.70)")
    ap.add_argument("--no-pause", action="store_true",
                    help="do not wait for Enter between steps (non-interactive re-run)")
    ap.add_argument("--no-interconnect", action="store_true",
                    help="skip the INTERCONNECT eye run (still writes Bode + Z/Y Bode)")
    args = ap.parse_args()

    if lumapi is None:
        sys.exit("[ERROR] lumapi not available")
    src = args.csv or rse.ask_results_csv()
    df = pd.read_csv(src)
    df["sim_id"] = df["sim_id"].astype(int)
    sim_id = args.sim_id if args.sim_id is not None else rse.ask_sim_id(df)
    params, _ = rse.read_params(src, sim_id)
    out_dir = rse.out_dir_for(sim_id)
    walkthrough(params, sim_id, out_dir, args)


if __name__ == "__main__":
    main()
