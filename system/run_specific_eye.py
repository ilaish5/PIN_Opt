# system/run_specific_eye.py
#
# Per-sim_id eye-diagram tool (CHARGE -> FDE -> INTERCONNECT).
#
#   Stage A  extract the small-signal circuit (V_pi, C_F, R_F, R_S, f_3dB) from a
#            fresh CHARGE+FDE+SSAC run of the design's 6 input parameters.
#   Stage B  design a 100 GHz RC peaking equalizer and write its Touchstone .s2p.
#   Stage C  drive the prebuilt INTERCONNECT .icp circuits and plot the eyes + Bode.
#
# Outputs -> results_archive/eye_<sim_id>/. Mirrors run_specific_sim.py's CLI.
# Reuses sim_handler / data_processor / eye_lib; leaves the optimization pipeline
# (main.py / BO.py / cost.py) untouched. English only.

import os
import sys
import json
import argparse

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config
import sim_handler
import data_processor
import eye_lib

sys.path.append(config.LUMERICAL_API_PATH)
try:
    import lumapi
except ImportError:
    lumapi = None

# --- constants -------------------------------------------------------------
PARAM_COLS = list(config.SWEEP_PARAMETERS.keys())   # w_r,h_si,doping,lambda,S,length
ARCHIVE_DIR = os.path.join(ROOT, "results_archive")
DEFAULT_CSV = config.RESULTS_CSV_FILE
R_DRV = eye_lib.R_DRV_DEFAULT                        # 50 ohm driver

# Stage A extraction policy (pragmatic per-param). The book's Table-3 triple can't
# be reproduced from one self-consistent extraction -- it mixes operating points and
# normalizations -- so each parameter uses its own best method (details in WORKLOG
# sec 8):
#   C_F   = SSAC high-frequency reactance (depletion cap; no length scaling)
#   R_F   = (dV/dI)/L on the forward branch, taken at FORWARD_OP_BIAS
#   R_S   = book value (SSAC can't reproduce it -- documented caveat)
#   f_3dB = 1/(2*pi*(R_S+R_drv)*C_F)
FORWARD_OP_BIAS = 0.79          # [V] book forward operating point (rd=10.55k crossing)
R_S_BOOK = 23.31                # [ohm] book Table 3 (SSAC does not reproduce it)

SSAC_RAMP_TOP = 0.5             # [V] top of the SSAC continuation ramp
SSAC_PERTURBATION = 0.001       # [V]
SSAC_F_START, SSAC_F_STOP, SSAC_PTS_PER_DEC = 1e3, 2e11, 2.0
# Medium mesh -> ~46 s SSAC solve (vs ~25 min on the production auto-refined mesh).
SSAC_MESH = {"max refine steps": 60.0, "min edge length": 5e-9, "max edge length": 5e-7}

ICP_DIR = os.path.join(config.LUMERICAL_FILES_DIR, "eye_rc_interconnect")
ICP = {
    "baseline":  os.path.join(ICP_DIR, "mzm_eye_baseline.icp"),
    "equalized": os.path.join(ICP_DIR, "mzm_eye_equalized.icp"),
}
BITRATE = 100e9                                      # PRBS + EYE set to 1e11 in the .icp


# ===========================================================================
# CLI / UX  (mirrors run_specific_sim.py)
# ===========================================================================

def ask_results_csv():
    while True:
        raw = input(f"Path to results CSV [{DEFAULT_CSV}]: ").strip().strip('"')
        path = raw or DEFAULT_CSV
        if os.path.exists(path):
            return path
        print(f"  not found: {path}")


def ask_sim_id(df):
    ids = sorted(df["sim_id"].astype(int).tolist())
    print(f"Available sim_ids: {ids[0]}..{ids[-1]} ({len(ids)} total)")
    while True:
        raw = input("Enter sim_id for eye analysis: ").strip()
        try:
            sim_id = int(raw)
        except ValueError:
            print("  please enter an integer")
            continue
        if sim_id in ids:
            return sim_id
        print(f"  sim_id {sim_id} is not in this file")


def read_params(src, sim_id):
    df = pd.read_csv(src)
    if "sim_id" not in df.columns:
        sys.exit(f"[ERROR] no 'sim_id' column in {src}")
    df["sim_id"] = df["sim_id"].astype(int)
    if sim_id not in set(df["sim_id"]):
        sys.exit(f"[ERROR] sim_id {sim_id} not in {src}")
    row = df[df["sim_id"] == sim_id].iloc[0]
    missing = [c for c in PARAM_COLS if c not in row or pd.isna(row[c])]
    if missing:
        sys.exit(f"[ERROR] sim_id {sim_id} is missing parameters: {missing}")
    return {c: float(row[c]) for c in PARAM_COLS}, row


def out_dir_for(sim_id):
    d = os.path.join(ARCHIVE_DIR, f"eye_{sim_id}")
    os.makedirs(d, exist_ok=True)
    return d


# ===========================================================================
# Stage A - device parameter extraction
# ===========================================================================

def extract_R_F(V, I, L_m, op_bias=FORWARD_OP_BIAS):
    """Forward-branch differential resistance R_F = (dV/dI)/L at `op_bias`.

    Mirrors analysis/rd_vs_bias.py. r_d(V) spans many decades, so it is
    log-interpolated at op_bias. Returns (R_F, Vs, Rs); (Vs, Rs) is the forward
    branch for inspection. Book R_F = 10.55 kohm sits at op_bias ~ 0.79 V.
    """
    V = np.asarray(V, dtype=float)
    I = np.asarray(I, dtype=float)
    R = (np.gradient(V) / np.gradient(I)) / L_m          # ohm
    mask = (V >= 0.4) & (I > 0) & np.isfinite(R) & (R > 0)
    order = np.argsort(V[mask])
    Vs, Rs = V[mask][order], R[mask][order]
    R_F = float(np.exp(np.interp(op_bias, Vs, np.log(Rs))))
    return R_F, Vs, Rs


def run_charge_fde(params, sim_id, out_dir):
    """Run the standard CHARGE+FDE pipeline and return V_pi, V_pi*L, loss, C(V),
    and R_F (forward branch at FORWARD_OP_BIAS)."""
    # Redirect the pipeline's raw output into the eye_<sim_id> dir.
    config.RAW_OUTPUT_DIR = os.path.join(out_dir, "raw")
    config.RUN_TIMESTAMP = f"eye_{sim_id}"
    raw_df, raw_csv, timing = sim_handler.run_full_simulation(params, sim_id=sim_id)

    V_cap, C_total_pF_cm = data_processor.process_charge_data(
        raw_df["V"].values, raw_df["n"].values, raw_df["p"].values)
    neff = raw_df["neff_re"].values + 1j * raw_df["neff_im"].values
    d_neff, alpha, d_phi, v_pi, max_dphi = data_processor.process_optical_data(
        neff, float(params["length"]), float(params["lambda"]))
    V_fde = np.linspace(0, config.V_MAX, len(d_neff))
    valid = not np.isnan(v_pi)
    loss_at_vpi = float(np.interp(v_pi, V_fde, alpha)) if valid else float(np.max(alpha))
    C_at_vpi = float(np.interp(v_pi, V_cap, C_total_pF_cm)) if valid else float("nan")
    v_pi_l = (v_pi * float(params["length"]) * 1e3) if valid else float("nan")

    # R_F from the swept terminal current on the forward branch.
    R_F, Vs_rd, Rs_rd = (float("nan"), None, None)
    if "I" in raw_df.columns:
        R_F, Vs_rd, Rs_rd = extract_R_F(
            raw_df["V"].values, raw_df["I"].values, float(params["length"]))
    return {
        "v_pi_V": float(v_pi), "v_pi_l_Vmm": v_pi_l,
        "loss_at_v_pi_dB_per_cm": loss_at_vpi,
        "C_at_v_pi_pF_per_cm": C_at_vpi,
        "max_dphi_rad": float(max_dphi),
        "R_F": R_F, "rd_V": Vs_rd, "rd_R": Rs_rd,
        "V_cap": V_cap, "C_total_pF_cm": C_total_pF_cm,
        "raw_csv": raw_csv, "timing": timing,
    }


def extract_ssac_cap(params, ramp_top=SSAC_RAMP_TOP):
    """Run CHARGE SSAC (0 -> ramp_top continuation ramp) and read C_F from the
    high-frequency reactance Im(Y)/w (the depletion cap).

    A single-pole RC fit is avoided because the device is two-cap and the fit
    diverges; the high-f admittance is cleanly capacitive (WORKLOG sec 3.5/3.6).
    Returns {C_F [F], R_S_ssac [ohm] (high-f Re(Z), reported for the caveat only),
    op_bias [V], table}. C_F uses NO length scaling.
    """
    if lumapi is None:
        raise RuntimeError("lumapi not available")
    local = os.path.join(os.environ.get("TEMP", "."), "eye_ssac")
    os.makedirs(local, exist_ok=True)

    dev = lumapi.DEVICE(hide=config.HIDE_GUI)
    try:
        dev.load(config.CHARGE_SIM_FILE)
        sim_handler.set_charge_parameters(dev, params, os.path.join(local, "ssac.mat"))
        dev.switchtolayout()
        for k, v in SSAC_MESH.items():
            dev.setnamed("CHARGE", k, v)
        bc = "CHARGE::boundary conditions::drain"
        # Ramp in ~0.1 V steps (continuation); a single hard jump is ~100x slower.
        npts = max(int(round(ramp_top / 0.1)) + 1, 3)
        dev.setnamed(bc, "sweep type", "range")
        dev.setnamed(bc, "range start", 0.0)
        dev.setnamed(bc, "range stop", ramp_top)
        dev.setnamed(bc, "range num points", float(npts))
        # SSAC needs >=1 small-signal source: designate the drain electrode.
        dev.setnamed(bc, "apply AC small signal", "all")
        dev.setnamed("CHARGE", "solver mode", "ssac")
        dev.setnamed("CHARGE", "perturbation amplitude", SSAC_PERTURBATION)
        dev.setnamed("CHARGE", "frequency spacing", "log")
        dev.setnamed("CHARGE", "log start frequency", SSAC_F_START)
        dev.setnamed("CHARGE", "log stop frequency", SSAC_F_STOP)
        dev.setnamed("CHARGE", "num frequency points per dec", SSAC_PTS_PER_DEC)
        dev.save(os.path.join(local, "ssac.ldev"))
        dev.mesh()
        dev.run()
        # SSAC results live under 'ac_drain' (not the DC 'drain' result); the
        # complex small-signal current is the 'dI' attribute (WORKLOG sec 3.5).
        ac = dev.getresult("CHARGE", "ac_drain")
    finally:
        try:
            dev.close()
        except Exception:
            pass

    f = np.asarray(ac["f"]).ravel().astype(float)
    Vb = np.real(np.asarray(ac["V_drain"])).ravel()
    dI = np.asarray(ac["dI"])                      # complex, (n_bias,1,1,n_freq)
    dI = dI.reshape(dI.shape[0], f.size)
    w = 2 * np.pi * f
    n_hf = min(3, f.size)                           # average the top few freqs
    table = []
    for i in range(dI.shape[0]):
        Y = dI[i] / SSAC_PERTURBATION               # admittance Y = dI/dV_pert
        Z = 1.0 / Y
        C_hf = float(np.mean(np.imag(Y[-n_hf:]) / w[-n_hf:]))   # F
        table.append({"V": float(Vb[i]) if i < len(Vb) else float("nan"),
                      "C_hf_pF": C_hf * 1e12,
                      "ReZ_hf": float(np.real(Z[-1]))})
    top = table[-1]
    return {
        "op_bias": top["V"],
        "C_F": top["C_hf_pF"] * 1e-12,
        "R_S_ssac": top["ReZ_hf"],
        "table": table,
    }


# ===========================================================================
# Stage C - INTERCONNECT eye + Bode  (driving the prebuilt .icp)
# ===========================================================================

def _read_scope(ic, name):
    d = ic.getresult(name, "signal")
    keys = [k for k in d if not str(k).startswith("Lumerical")]
    tk = next((k for k in keys if "time" in k.lower()), None)
    ak = next((k for k in keys if k != tk and np.asarray(d[k]).size > 4), None)
    t = np.real(np.asarray(d[tk]).ravel())
    v = np.real(np.asarray(d[ak]).ravel())
    n = min(len(t), len(v))
    return t[:n], v[:n]


def _set_ic(ic, name, prop, val):
    """setnamed, falling back to setexpression for numeric props that carry a
    bound expression in the .icp (which would otherwise reject setnamed)."""
    try:
        ic.setnamed(name, prop, val)
        return
    except Exception as e:
        if "expression" in str(e) and isinstance(val, (int, float)) and not isinstance(val, bool):
            ic.setexpression(name, prop, repr(float(val)))
            return
        raise


def drive_interconnect(circuit_params, s2p_path, out_dir):
    """Load both prebuilt .icp circuits, set element values per design, run, and
    return {case: (t, v)} scope traces. Re-points RC_EQ to the freshly built .s2p.
    """
    if lumapi is None:
        raise RuntimeError("lumapi not available")
    f3 = circuit_params["f_3dB"]
    v_pi = circuit_params["V_pi"]
    il_db = circuit_params["IL_dB"]
    dc_bias = -v_pi / 2.0                  # MZM quadrature (book: ~ -V_pi/2)
    eyes = {}
    ic = lumapi.INTERCONNECT(hide=config.HIDE_GUI)
    try:
        for case in ("baseline", "equalized"):
            ic.load(ICP[case])
            ic.switchtodesign()
            if case == "baseline":
                _set_ic(ic, "PIN_DEV", "cutoff frequency", f3)
                _set_ic(ic, "NRZ_1", "amplitude", v_pi)
                _set_ic(ic, "DC_1", "amplitude", dc_bias)
            else:
                _set_ic(ic, "LPF_1", "cutoff frequency", f3)
                _set_ic(ic, "NRZ_1", "amplitude", v_pi)
                _set_ic(ic, "RC_EQ", "load from file", 1.0)
                _set_ic(ic, "RC_EQ", "s parameters filename", s2p_path)
                _set_ic(ic, "AMP_1", "gain", il_db)
            ic.run()
            eyes[case] = _read_scope(ic, "PD_SCOPE")
    finally:
        try:
            ic.close()
        except Exception:
            pass
    return eyes


# ===========================================================================
# Plotting
# ===========================================================================

def plot_eyes(eyes, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, case in zip(axes, ("baseline", "equalized")):
        t, v = eyes[case]
        t_ps, win = eye_lib.fold_eye(t, v, BITRATE, n_ui=2)
        ax.hist2d(np.tile(t_ps, win.shape[0]), win.ravel(),
                  bins=[win.shape[1], 160], cmap="turbo", cmin=1)
        ax.set(xlabel="time [ps]", ylabel="PD signal [a.u.]",
               title=f"{case} eye @ {BITRATE/1e9:.0f} Gbps")
    fig.suptitle("INTERCONNECT optical eye (PIN-detected)", y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_bode(cp, out_path):
    f = np.geomspace(1e6, 2e11, 2000)
    Hdev = eye_lib.H_device(f, cp["R_S"], cp["R_F"], cp["C_F"])
    Heq = eye_lib.H_eq(f, cp["R_eq"], cp["C_eq"], cp["eta"])
    Hcasc = Hdev * Heq
    DC0 = abs(Hdev[0])
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.semilogx(f / 1e9, 20 * np.log10(np.abs(Hdev) / DC0), "C0-", lw=2, label="raw device")
    ax.semilogx(f / 1e9, 20 * np.log10(np.abs(Hcasc) / DC0), "C1-", lw=2, label="equalized (device x eq)")
    ax.axhline(-3, color="k", ls=":", alpha=0.6, label="-3 dB")
    ax.axvline(cp["f_3dB"] / 1e9, color="C0", ls="--", alpha=0.7,
               label=f"f_3dB = {cp['f_3dB']/1e9:.2f} GHz")
    ax.axvline(cp["f_3dB_eq"] / 1e9, color="C1", ls="--", alpha=0.7,
               label=f"f_3dB,Eq = {cp['f_3dB_eq']/1e9:.0f} GHz")
    ax.set(xlabel="Frequency [GHz]", ylabel="|H/H_dev(0)| [dB]",
           title="Electrical transfer - raw device vs equalized")
    ax.set_ylim(-30, 30)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ===========================================================================
# Validation against the sim-109 reference (EYE_TOOL_SPEC.md sec 6, Table 2/3)
# ===========================================================================

# (target, +/- tolerance fraction). Self-check printout only -- never fed back
# into the computation.
SIM109_TARGETS = {
    "V_pi":      (0.863,    0.02),
    "V_pi*L":    (0.649,    0.02),
    "loss":      (15.2,     0.02),
    "C_F":       (0.3471,   0.05),
    "R_F":       (10.55,    0.15),
    "R_S":       (23.31,    0.20),
    "f_3dB":     (6.25,     0.10),
}


def print_validation_table(got, sim_id):
    """Print the sec-6 got/target/delta/pass table for sim 109. `got` keys match
    SIM109_TARGETS, in the target units (V, V*mm, dB/cm, pF, kohm, ohm, GHz).
    Returns True if all pass, None if not sim 109.
    """
    if int(sim_id) != 109:
        print("  (validation table is defined for the sim-109 reference only)")
        return None
    print("\n  -- sim-109 validation (EYE_TOOL_SPEC sec 6) --")
    print(f"  {'qty':<8}{'target':>10}{'tol':>7}{'got':>12}{'delta':>9}  pass")
    all_ok = True
    for k, (tgt, tol) in SIM109_TARGETS.items():
        g = got.get(k, float("nan"))
        d = (g - tgt) / tgt if tgt else float("nan")
        ok = abs(d) <= tol
        all_ok = all_ok and ok
        print(f"  {k:<8}{tgt:>10.4g}{tol*100:>6.0f}%{g:>12.4g}{d*100:>8.1f}%  "
              f"{'OK' if ok else 'FAIL'}")
    return all_ok


# ===========================================================================
# main
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="Per-sim_id eye-diagram tool")
    ap.add_argument("--csv", default=None, help="results CSV path")
    ap.add_argument("--sim-id", type=int, default=None)
    ap.add_argument("--target-bw", type=float, default=100e9,
                    help="equalized target bandwidth [Hz] (default 100 GHz)")
    ap.add_argument("--rf-bias", type=float, default=FORWARD_OP_BIAS,
                    help="forward operating bias for R_F=(dV/dI)/L [V] (default 0.79)")
    ap.add_argument("--no-interconnect", action="store_true",
                    help="Stage A/B only (skip the INTERCONNECT eye/Bode run)")
    args = ap.parse_args()

    src = args.csv or ask_results_csv()
    df = pd.read_csv(src)
    df["sim_id"] = df["sim_id"].astype(int)
    sim_id = args.sim_id if args.sim_id is not None else ask_sim_id(df)
    params, _ = read_params(src, sim_id)
    out_dir = out_dir_for(sim_id)

    print(f"\n=== Eye analysis sim_id {sim_id} (source: {src}) ===")
    for c in PARAM_COLS:
        print(f"  {c:<10} = {params[c]:.6g}")
    print(f"Output dir: {out_dir}\n")

    # --- Stage A (pragmatic per-param; see policy block at top of file) ---
    print("[Stage A] CHARGE+FDE (V_pi, loss, R_F) ...")
    a = run_charge_fde(params, sim_id, out_dir)
    R_F = a["R_F"]                                   # (dV/dI)/L @ FORWARD_OP_BIAS
    print(f"  V_pi = {a['v_pi_V']:.4f} V   V_pi*L = {a['v_pi_l_Vmm']:.4f} V*mm   "
          f"loss = {a['loss_at_v_pi_dB_per_cm']:.2f} dB/cm")
    print(f"  R_F  = {R_F/1e3:.2f} kohm  ((dV/dI)/L @ {args.rf_bias:.2f} V)")

    print("[Stage A] SSAC depletion cap (C_F) ...")
    ssac = extract_ssac_cap(params)
    C_F = ssac["C_F"]                                # high-f depletion cap, no /L
    R_S = R_S_BOOK                                   # book; SSAC does not reproduce
    f_3dB = eye_lib.f_3dB_device(R_S, C_F)
    print(f"  C_F  = {C_F*1e12:.4f} pF  (SSAC high-f reactance, no length scaling)")
    print(f"  R_S  = {R_S:.2f} ohm  (BOOK value; SSAC high-f Re(Z) = "
          f"{ssac['R_S_ssac']:.3f} ohm does NOT reproduce it -- documented caveat)")
    print(f"  f_3dB = {f_3dB/1e9:.3f} GHz  (= 1/(2*pi*(R_S+{R_DRV:.0f})*C_F))")

    ok = print_validation_table({
        "V_pi": a["v_pi_V"], "V_pi*L": a["v_pi_l_Vmm"],
        "loss": a["loss_at_v_pi_dB_per_cm"], "C_F": C_F * 1e12,
        "R_F": R_F / 1e3, "R_S": R_S, "f_3dB": f_3dB / 1e9,
    }, sim_id)
    if ok is False:
        print("  WARNING: one or more sim-109 checks FAILED (see table above).")

    # --- Stage B ---
    print("[Stage B] equalizer design + Touchstone ...")
    d = eye_lib.design_equalizer(R_F, C_F, f_3dB, R_S=R_S,
                                 target_bw=args.target_bw, mode="corrected")
    s2p = os.path.join(out_dir, "rc_equalizer_S21.s2p")
    eye_lib.write_equalizer_touchstone(s2p, d["R_eq"], d["C_eq"], d["eta"],
                                       sample_rate=BITRATE * 64)
    print(f"  eta={d['eta']:.2f}  IL={d['IL_dB']:.2f} dB  R_eq={d['R_eq']:.1f} ohm  "
          f"C_eq={d['C_eq']*1e15:.2f} fF  f_3dB,Eq={d['f_3dB_eq']/1e9:.0f} GHz")
    print(f"  !! raw eye at {BITRATE/1e9:.0f} Gbps is essentially CLOSED; the "
          f"equalized eye carries IL={d['IL_dB']:.1f} dB (compensated by AMP_1).")

    cp = {"V_pi": a["v_pi_V"], "R_S": R_S, "R_F": R_F, "C_F": C_F, "f_3dB": f_3dB,
          "eta": d["eta"], "R_eq": d["R_eq"], "C_eq": d["C_eq"], "IL_dB": d["IL_dB"],
          "f_3dB_eq": d["f_3dB_eq"], "rf_bias": args.rf_bias,
          "v_pi_l_Vmm": a["v_pi_l_Vmm"], "loss_at_v_pi_dB_per_cm": a["loss_at_v_pi_dB_per_cm"],
          # provenance / caveats (each param's extraction method):
          "_extraction": {
              "C_F": "SSAC high-frequency reactance (depletion cap), no length scaling",
              "R_F": f"(dV/dI)/L on forward branch, log-interp at {args.rf_bias:.2f} V",
              "R_S": "book Table-3 value 23.31 ohm; SSAC high-f Re(Z) does NOT reproduce it",
              "f_3dB": "1/(2*pi*(R_S+R_drv)*C_F), book eq 18/45",
          },
          "R_S_ssac_ohm": ssac["R_S_ssac"], "ssac_ramp_top_V": ssac["op_bias"]}

    # always write the Bode (analytic) and the extracted params
    plot_bode(cp, os.path.join(out_dir, "bode.png"))
    with open(os.path.join(out_dir, "circuit_params.json"), "w") as fh:
        json.dump({k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
                   for k, v in cp.items()}, fh, indent=2)

    # --- Stage C ---
    if args.no_interconnect:
        print("\n[Stage C] skipped (--no-interconnect). Bode + params written.")
    else:
        print("[Stage C] INTERCONNECT eye + Bode ...")
        eyes = drive_interconnect(cp, s2p, out_dir)
        plot_eyes(eyes, os.path.join(out_dir, "eye_comparison.png"))
    print(f"\nDone. Outputs in {out_dir}")


if __name__ == "__main__":
    main()
