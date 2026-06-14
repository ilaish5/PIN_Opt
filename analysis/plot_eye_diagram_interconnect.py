# plot_eye_standalone.py
# ============================================================================
# Load pre-built INTERCONNECT .icp files via the Lumerical API, run the
# transient simulation, read the PD_SCOPE waveform, and plot the eye diagrams
# for both the baseline and equalized circuits side by side.
#
# .icp files expected at:
#   ../Lumerical_Files/eye_rc_interconnect/mzm_eye_baseline.icp
#   ../Lumerical_Files/eye_rc_interconnect/mzm_eye_equalized.icp
#
# RUN (Lumerical x64 python - GUI visible):
#   & "C:\Program Files\Lumerical\v231\python\python.exe" plot_eye_standalone.py
# Headless (no GUI, no pauses):
#   & "C:\Program Files\Lumerical\v231\python\python.exe" plot_eye_standalone.py --headless
# ============================================================================

import sys, argparse, functools
from pathlib import Path
print = functools.partial(print, flush=True)

LUMERICAL_API_PATH = r"C:\Program Files\Lumerical\v231\api\python"
sys.path.append(LUMERICAL_API_PATH)
import lumapi

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent          # analysis/
ROOT = HERE.parent                               # PS_Opt_V2/
ICP_DIR = ROOT / "Lumerical_Files" / "eye_rc_interconnect"

ICP = {
    "baseline":  ICP_DIR / "mzm_eye_baseline.icp",
    "equalized": ICP_DIR / "mzm_eye_equalized.icp",
}
OUT_PNG = HERE / "eye_comparison.png"            # analysis output stays here

BITRATE = 100e9  # must match what was used in build_eye_rc.py

# ----------------------------------------------------------------------------
# SI unit formatting for time values
# ----------------------------------------------------------------------------

def fmt_time(seconds):
    """Format a time value in seconds using the closest standard SI prefix."""
    if not np.isfinite(seconds):
        return "n/a"
    prefixes = [
        (1e-15, "fs"),
        (1e-12, "ps"),
        (1e-9,  "ns"),
        (1e-6,  "\u00b5s"),
        (1e-3,  "ms"),
        (1.0,   "s"),
    ]
    abs_val = abs(seconds)
    for scale, unit in prefixes:
        if abs_val < scale * 1e3:
            return f"{seconds / scale:.2f} {unit}"
    return f"{seconds:.3g} s"


# ----------------------------------------------------------------------------
# Read waveform from an Oscilloscope element result
# ----------------------------------------------------------------------------

def read_scope(ic, name):
    """Return (t, v) numpy arrays from an Oscilloscope 'signal' result."""
    d = ic.getresult(name, "signal")
    if not isinstance(d, dict):
        raise RuntimeError(f"{name}: unexpected signal type {type(d)}")
    keys = [k for k in d if not str(k).startswith("Lumerical")]
    time_key = next((k for k in keys if "time" in k.lower()), None)
    amp_key  = next((k for k in keys if k != time_key and np.asarray(d[k]).size > 4), None)
    if time_key is None or amp_key is None:
        raise RuntimeError(f"{name}: empty scope signal (keys={list(d.keys())})")
    t = np.real(np.asarray(d[time_key]).ravel())
    v = np.real(np.asarray(d[amp_key]).ravel())
    n = min(len(t), len(v))
    return t[:n], v[:n]


# ----------------------------------------------------------------------------
# Read scalar measurements from the Eye Diagram analyzer element
# ----------------------------------------------------------------------------

EYE_ELEMENT = "EYE_1"

def read_eye_measurements(ic, name):
    """Return (eye_height, eye_width [s], Q, jitter_rms [s], ber) from the Eye Diagram element."""
    def _get(result_path):
        try:
            raw = ic.getresult(name, result_path)
            return float(np.real(np.asarray(raw).ravel()[0]))
        except Exception as e:
            print(f"    WARNING: could not read '{result_path}': {str(e).splitlines()[0]}")
            return float("nan")
    eye_height = _get("measurement/height")
    eye_width  = _get("measurement/width")
    Q          = _get("measurement/Q factor")
    jitter_rms = _get("measurement/jitter RMS")
    ber        = _get("measurement/BER")
    return eye_height, eye_width, Q, jitter_rms, ber


# ----------------------------------------------------------------------------
# Plot
# ----------------------------------------------------------------------------

def plot_eyes(eyes, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, case in zip(axes, ("baseline", "equalized")):
        t, v, eh, ew, Q, jrms, ber = eyes[case]
        dt   = t[1] - t[0]
        span = 2 * int(round((1.0 / BITRATE) / dt))   # 2 UI wide
        m    = (len(v) // span) * span
        win  = v[:m].reshape(-1, span)
        tps  = np.arange(span) * dt * 1e12             # time axis in ps
        ax.hist2d(
            np.tile(tps, win.shape[0]),
            win.ravel(),
            bins=[span, 160],
            cmap="turbo",
            cmin=1,
        )
        # tag      = "baseline (no RC)" if case == "baseline" else "equalized (with RC)"
        # ber_str  = f"{ber:.2e}" if np.isfinite(ber) else "n/a"
        # jrms_str = fmt_time(jrms)
        # ew_str   = fmt_time(ew)
        ax.set(
            xlabel="time (ps)",
            ylabel="Normalized PD signal (a.u.)",
            # title=(
            #     f"{tag}  eye - {BITRATE/1e9:.0f} Gbps\n"
            #     f"height={eh:.3g}  width={ew_str}  Q={Q:.2f}\n"
            #     f"jitter RMS={jrms_str}  BER={ber_str}"
            # ),
            title = case.capitalize()
        )
    # fig.suptitle("Optical eye (PIN-detected) - INTERCONNECT transient", y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> eye plot saved: {out_path}")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Load .icp files, run INTERCONNECT simulation, and plot eye diagrams"
    )
    ap.add_argument("--headless", action="store_true",
                    help="run with no GUI and no pauses (default shows the GUI)")
    ap.add_argument("--out", default=str(OUT_PNG),
                    help="output PNG path (default: eye_comparison.png)")
    args = ap.parse_args()
    show_gui = not args.headless
    out_path = Path(args.out)

    for case, path in ICP.items():
        if not path.exists():
            print(f"ERROR: {path} not found.")
            sys.exit(1)

    print("=" * 70)
    print(" plot_eye_standalone.py  -  INTERCONNECT eye diagram plot")
    print("=" * 70)
    print(f"  baseline : {ICP['baseline']}")
    print(f"  equalized: {ICP['equalized']}")
    print(f"  GUI: {'on' if show_gui else 'off'}")

    eyes = {}
    ic = lumapi.INTERCONNECT(hide=not show_gui)
    try:
        for case in ("baseline", "equalized"):
            print(f"\n--- [{case}] loading {ICP[case].name} ---")
            ic.load(str(ICP[case]))

            print("    running simulation...")
            ic.switchtodesign()
            ic.run()

            t, v = read_scope(ic, "PD_SCOPE")
            eh, ew, Q, jrms, ber = read_eye_measurements(ic, EYE_ELEMENT)
            eyes[case] = (t, v, eh, ew, Q, jrms, ber)
            ber_str  = f"{ber:.2e}" if np.isfinite(ber) else "n/a"
            jrms_str = fmt_time(jrms)
            ew_str   = fmt_time(ew)
            print(f"    eye: height={eh:.4g}  width={ew_str}  Q={Q:.2f}  "
                  f"jitter_rms={jrms_str}  BER={ber_str}")

            if show_gui:
                input(
                    f"    >>> [{case}] done - double-click the EYE block to inspect. "
                    f"Press Enter to continue..."
                )
    finally:
        try:
            ic.close()
        except Exception:
            pass

    print("\n--- plotting ---")
    plot_eyes(eyes, out_path)

    print("\n" + "=" * 70)
    print(f" Done. Output: {out_path.name}")
    print("=" * 70)


if __name__ == "__main__":
    main()
