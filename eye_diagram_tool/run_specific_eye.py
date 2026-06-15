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

HERE = os.path.dirname(os.path.abspath(__file__))   # eye_diagram_tool/
ROOT = os.path.dirname(HERE)                          # PS_Opt_V2/
# eye_lib lives here; config/sim_handler/data_processor live in system/.
for _p in (HERE, os.path.join(ROOT, "system")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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

# Stage A is a SELF-CONSISTENT, fully sim-computed small-signal extraction: ONE
# SSAC sweep at the forward operating bias, ONE length normalization applied to the
# whole impedance (Z_device = Z_reported * norm/L), everything read off the same
# Y_device (see eye_lib.extract_small_signal and WORKLOG sec 10). No book values
# are forced into the computation -- R_S, R_F, C_diff, C_dep, f_3dB are all per-sim.
#
# The PIN junction has two caps and the small-signal picture is strongly
# bias-dependent, so the forward operating bias matters. It is anchored at 0.70 V:
# that is where the computed R_F (~10-11 kohm) reproduces the book's own operating
# point (book R_F = 10.55 kohm), so the OTHER quantities are reported at the same
# physical bias. Overridable via --op-bias; the full bias sweep is printed so the
# sensitivity is explicit.
FORWARD_OP_BIAS = 0.70          # [V] forward operating point (computed R_F ~ 10 kohm)
NORM_LENGTH = 0.01              # [m] CHARGE 2D norm length (getnamed("CHARGE","norm length"))

SSAC_PERTURBATION = 0.001       # [V]
SSAC_F_START, SSAC_F_STOP, SSAC_PTS_PER_DEC = 1.0, 2e11, 2.0   # 1 Hz: below diff pole
# Medium mesh -> ~50 s SSAC solve (vs ~25 min on the production auto-refined mesh).
SSAC_MESH = {"max refine steps": 60.0, "min edge length": 5e-9, "max edge length": 5e-7}

# Book Table-2/3 values -- used ONLY for the computed-vs-book comparison printout,
# never fed into the computation.
BOOK = {"R_S": 23.31, "R_F": 10.55e3, "C_F": 0.3471e-12, "f_3dB": 6.25e9}

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


def run_charge_fde(params, sim_id, out_dir, op_bias=FORWARD_OP_BIAS):
    """Run the standard CHARGE+FDE pipeline and return V_pi, V_pi*L, loss, C(V),
    and R_F (forward branch dV/dI at op_bias -- a cross-check for the SSAC R_F)."""
    # Redirect the pipeline's raw output into the eye_<sim_id> dir. NOTE: the CHARGE
    # .mat handoff (import_charge_data uses basename, resolved in the FDE session's
    # working dir = Lumerical_Files) must stay there, so it is NOT redirected. The
    # new heavy step (SSAC) already runs on local disk.
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
            raw_df["V"].values, raw_df["I"].values, float(params["length"]), op_bias)
    return {
        "v_pi_V": float(v_pi), "v_pi_l_Vmm": v_pi_l,
        "loss_at_v_pi_dB_per_cm": loss_at_vpi,
        "C_at_v_pi_pF_per_cm": C_at_vpi,
        "max_dphi_rad": float(max_dphi),
        "R_F": R_F, "rd_V": Vs_rd, "rd_R": Rs_rd,
        "V_cap": V_cap, "C_total_pF_cm": C_total_pF_cm,
        "raw_csv": raw_csv, "timing": timing,
    }


def extract_ssac_circuit(params, op_bias=FORWARD_OP_BIAS):
    """Run ONE CHARGE SSAC sweep ramped to the forward operating bias and extract
    the full self-consistent small-signal picture (eye_lib.extract_small_signal).

    Ramps 0 -> op_bias by continuation and sweeps 1 Hz .. 200 GHz so both the
    low-f diffusion corner and the high-f depletion behaviour are captured. Returns
    the picture dict at op_bias (R_S, R_F, C_diff, C_dep, tau, f_3dB_diff/dep + the
    device-scaled f/Z/Y/C arrays) plus `bias_table`: the same picture at every ramp
    bias, to expose the strong bias dependence.
    """
    if lumapi is None:
        raise RuntimeError("lumapi not available")
    L = float(params["length"])
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
        npts = max(int(round(op_bias / 0.1)) + 1, 3)
        dev.setnamed(bc, "sweep type", "range")
        dev.setnamed(bc, "range start", 0.0)
        dev.setnamed(bc, "range stop", op_bias)
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
    dI = np.asarray(ac["dI"]).reshape(len(Vb), f.size)

    bias_table = []
    for i in range(len(Vb)):
        Z_rep = SSAC_PERTURBATION / dI[i]           # reported (per norm-length)
        p = eye_lib.extract_small_signal(f, Z_rep, NORM_LENGTH, L)
        p["V"] = float(Vb[i])
        bias_table.append(p)
    # the operating-bias picture is the last ramp point (== op_bias)
    pic = bias_table[-1]
    pic["bias_table"] = bias_table
    return pic


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


def plot_zy_bode(pic, out_path):
    """Z(w) and Y(w) Bode (mag + phase) + C(f), showing the device's TWO-cap
    nature: the low-f diffusion corner and the high-f depletion plateau."""
    f = pic["f"] / 1e9
    Z, Y, C = pic["Z"], pic["Y"], pic["C"]
    fd, fp = pic["f_3dB_diff"] / 1e9, pic["f_3dB_dep"] / 1e9
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))

    def corners(a):
        a.axvline(fd, color="C1", ls="--", alpha=0.7, label=f"f_3dB,diff = {fd*1e3:.0f} MHz")
        a.axvline(fp, color="C2", ls="--", alpha=0.7, label=f"f_3dB,dep = {fp:.0f} GHz")
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=8)

    ax[0, 0].loglog(f, np.abs(Z), "C0-", lw=2)
    ax[0, 0].axhline(pic["R_S"], color="k", ls=":", alpha=0.6, label=f"R_S = {pic['R_S']:.1f} ohm")
    ax[0, 0].axhline(pic["R_S"] + pic["R_F"], color="0.5", ls=":", alpha=0.6,
                     label=f"R_S+R_F = {(pic['R_S']+pic['R_F'])/1e3:.1f} kohm")
    ax[0, 0].set(xlabel="f [GHz]", ylabel="|Z| [ohm]", title="Impedance magnitude")
    corners(ax[0, 0])

    ax[0, 1].semilogx(f, np.angle(Z, deg=True), "C0-", lw=2)
    ax[0, 1].set(xlabel="f [GHz]", ylabel="phase(Z) [deg]", title="Impedance phase")
    corners(ax[0, 1])

    ax[1, 0].loglog(f, np.abs(Y), "C3-", lw=2)
    ax[1, 0].set(xlabel="f [GHz]", ylabel="|Y| [S]", title="Admittance magnitude")
    corners(ax[1, 0])

    ax[1, 1].loglog(f, C * 1e12, "C3-", lw=2)
    ax[1, 1].axhline(pic["C_diff"] * 1e12, color="C1", ls=":", alpha=0.7,
                     label=f"C_diff = {pic['C_diff']*1e12:.3g} pF")
    ax[1, 1].axhline(pic["C_dep"] * 1e12, color="C2", ls=":", alpha=0.7,
                     label=f"C_dep = {pic['C_dep']*1e12:.3g} pF")
    ax[1, 1].set(xlabel="f [GHz]", ylabel="C = Im(Y)/w [pF]",
                 title="Capacitance vs freq (two-cap signature)")
    corners(ax[1, 1])

    fig.suptitle(f"Self-consistent small-signal Z/Y  (forward bias {pic['V']:.2f} V, "
                 f"length-scaled)", y=1.0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def print_bias_sweep(bias_table):
    """Print the bias-dependent small-signal picture (exposes the strong bias
    dependence of R_F, C_diff and the modulation BW)."""
    print("  -- bias-dependent picture (length-scaled) --")
    print(f"  {'V':>5}{'R_S[ohm]':>10}{'R_F[k]':>9}{'C_diff[pF]':>12}"
          f"{'C_dep[pF]':>11}{'tau[ns]':>9}{'f_diff[GHz]':>12}")
    for p in bias_table:
        print(f"  {p['V']:>5.2f}{p['R_S']:>10.2f}{p['R_F']/1e3:>9.3f}"
              f"{p['C_diff']*1e12:>12.4f}{p['C_dep']*1e12:>11.5f}"
              f"{p['tau']*1e9:>9.2f}{p['f_3dB_diff']/1e9:>12.4f}")


def print_computed_vs_book(cp):
    """Print the computed (per-sim) vs book delta table."""
    rows = [("R_S [ohm]",  cp["R_S"],       BOOK["R_S"]),
            ("R_F [kohm]",  cp["R_F"]/1e3,   BOOK["R_F"]/1e3),
            ("C_diff [pF]", cp["C_diff"]*1e12, BOOK["C_F"]*1e12),
            ("f_3dB [GHz]", cp["f_3dB"]/1e9, BOOK["f_3dB"]/1e9)]
    print("  -- computed (per-sim, SSAC) vs book --")
    print(f"  {'quantity':<12}{'computed':>12}{'book':>12}{'ratio':>9}")
    for name, comp, book in rows:
        print(f"  {name:<12}{comp:>12.4g}{book:>12.4g}{comp/book:>8.2f}x")


# ===========================================================================
# main
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="Per-sim_id eye-diagram tool")
    ap.add_argument("--csv", default=None, help="results CSV path")
    ap.add_argument("--sim-id", type=int, default=None)
    ap.add_argument("--target-bw", type=float, default=100e9,
                    help="equalized target bandwidth [Hz] (default 100 GHz)")
    ap.add_argument("--op-bias", type=float, default=FORWARD_OP_BIAS,
                    help="forward operating bias for the SSAC extraction [V] (default 0.70)")
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

    # --- Stage A: self-consistent, fully sim-computed small-signal extraction ---
    print(f"[Stage A] CHARGE+FDE (V_pi, loss; dV/dI cross-check @ {args.op_bias:.2f} V) ...")
    a = run_charge_fde(params, sim_id, out_dir, op_bias=args.op_bias)
    print(f"  V_pi = {a['v_pi_V']:.4f} V   V_pi*L = {a['v_pi_l_Vmm']:.4f} V*mm   "
          f"loss = {a['loss_at_v_pi_dB_per_cm']:.2f} dB/cm")

    print(f"[Stage A] SSAC small-signal sweep (forward bias -> {args.op_bias:.2f} V) ...")
    pic = extract_ssac_circuit(params, op_bias=args.op_bias)
    print_bias_sweep(pic["bias_table"])
    R_S, R_F, C_diff, C_dep = pic["R_S"], pic["R_F"], pic["C_diff"], pic["C_dep"]
    f_3dB = pic["f_3dB_diff"]                         # physical forward-injection BW
    print(f"\n  @ op bias {pic['V']:.2f} V (all length-scaled x norm/L, no book values):")
    print(f"    R_S    = {R_S:.2f} ohm        (high-f Re Z; book 23.31 -- external R)")
    print(f"    R_F    = {R_F/1e3:.3f} kohm     (low-f Re Z - R_S; dV/dI cross-check "
          f"{a['R_F']/1e3:.2f} kohm)")
    print(f"    C_diff = {C_diff*1e12:.4f} pF    (forward diffusion cap, low-f)")
    print(f"    C_dep  = {C_dep*1e12:.5f} pF   (depletion/junction cap, high-f)")
    print(f"    tau    = {pic['tau']*1e9:.2f} ns      (R_F*C_diff)")
    print(f"    f_3dB,diff = {f_3dB/1e9:.4f} GHz   <- PHYSICAL modulation BW "
          f"(forward injection, C_diff-limited)")
    print(f"    f_3dB,dep  = {pic['f_3dB_dep']/1e9:.2f} GHz    (depletion-limited; "
          f"only relevant in reverse bias)")
    print_computed_vs_book({"R_S": R_S, "R_F": R_F, "C_diff": C_diff, "f_3dB": f_3dB})

    # --- Stage B: equalizer keyed off the COMPUTED forward-injection BW ---
    print("[Stage B] equalizer design + Touchstone (keyed off f_3dB,diff) ...")
    d = eye_lib.design_equalizer(R_F, C_diff, f_3dB, R_S=R_S,
                                 target_bw=args.target_bw, mode="corrected")
    s2p = os.path.join(out_dir, "rc_equalizer_S21.s2p")
    eye_lib.write_equalizer_touchstone(s2p, d["R_eq"], d["C_eq"], d["eta"],
                                       sample_rate=BITRATE * 64)
    print(f"  eta={d['eta']:.2f}  IL={d['IL_dB']:.2f} dB  R_eq={d['R_eq']:.1f} ohm  "
          f"C_eq={d['C_eq']*1e15:.2f} fF  f_3dB,Eq={d['f_3dB_eq']/1e9:.0f} GHz")
    print(f"  !! the REAL device BW is only {f_3dB/1e9:.2f} GHz, so 100 Gbps needs "
          f"IL={d['IL_dB']:.0f} dB of equalization (compensated by AMP_1).")

    cp = {"V_pi": a["v_pi_V"], "op_bias_V": pic["V"],
          "R_S": R_S, "R_F": R_F, "C_diff": C_diff, "C_dep": C_dep,
          "tau_ns": pic["tau"] * 1e9, "f_3dB": f_3dB,
          "f_3dB_diff": pic["f_3dB_diff"], "f_3dB_dep": pic["f_3dB_dep"],
          "R_F_dvdi": a["R_F"],
          "eta": d["eta"], "R_eq": d["R_eq"], "C_eq": d["C_eq"], "IL_dB": d["IL_dB"],
          "f_3dB_eq": d["f_3dB_eq"],
          "v_pi_l_Vmm": a["v_pi_l_Vmm"], "loss_at_v_pi_dB_per_cm": a["loss_at_v_pi_dB_per_cm"],
          "book": BOOK,
          "_method": ("self-consistent SSAC: Z_device = Z_reported*(norm/L), all "
                      "small-signal params read off Y_device=1/Z at the forward op "
                      "bias; f_3dB = f_3dB,diff (forward-injection modulation BW); "
                      "no book values forced.")}

    # always write the two Bodes (analytic) and the extracted params
    plot_bode({**cp, "C_F": C_diff}, os.path.join(out_dir, "bode.png"))
    plot_zy_bode(pic, os.path.join(out_dir, "zy_bode.png"))
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
