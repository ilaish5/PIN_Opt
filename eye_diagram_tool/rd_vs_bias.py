"""Forward-bias differential resistance r_d(V_F) from a CHARGE I-V sweep.

Offline sanity check for the small-signal R_F in the equivalent circuit
(book Table 3, R_F = 10.55 kohm). Reads a per-sim raw CSV produced by
sim_handler (columns include 'V' and the swept terminal current 'I'),
computes r_d = (dV/dI) / L, and plots it vs forward bias.

Note on units: CHARGE is a 2D cross-section solver, so 'I' is per unit length
[A/m]. The real device resistance is therefore (dV/dI) / L, with L the phase
shifter length. The current at the operating point is I_2D * L.

Usage:
    python rd_vs_bias.py [raw_csv] [length_m]
Defaults to the verified global optimum, sim_id 109 (L = 0.752 mm).
"""
import sys
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Defaults: the verified global optimum (sim_id 109).
DEFAULT_CSV = os.path.join(
    ROOT, "results_archive", "verify_109", "raw",
    "verify_109_result", "verify_109_sim_109.csv")
DEFAULT_L = 0.752e-3      # phase shifter length [m] (sim_id 109)
R_F_BOOK = 10.55e3        # book Table 3 [ohm]
V_PI = 0.649 / 0.752      # V_piL / L -> ~0.863 V

CSV = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
L = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_L
OUT = os.path.join(HERE, "rd_vs_bias_109.png")


def main():
    df = pd.read_csv(CSV)
    if "I" not in df.columns:
        sys.exit(f"No 'I' column in {CSV} — re-run the sim with terminal-current "
                 f"extraction enabled (sim_handler.extract_charge_current).")
    V = df["V"].to_numpy()        # volts
    I2D = df["I"].to_numpy()      # A/m (2D, per unit length)

    # r_d = dV/dI per unit length [ohm*m], then divide by L for the real device.
    R = (np.gradient(V) / np.gradient(I2D)) / L     # ohm

    # Physical forward branch: rising, positive current, finite positive R.
    mask = (V >= 0.4) & (I2D > 0) & np.isfinite(R) & (R > 0)
    order = np.argsort(V[mask])
    Vs, Rs = V[mask][order], R[mask][order]

    # Bias where r_d crosses the book value (interp in log R, which falls with V).
    cross_V = None
    for i in range(len(Vs) - 1):
        a, b = Rs[i], Rs[i + 1]
        if (a - R_F_BOOK) * (b - R_F_BOOK) <= 0 and a != b:
            t = (np.log(R_F_BOOK) - np.log(a)) / (np.log(b) - np.log(a))
            cross_V = Vs[i] + t * (Vs[i + 1] - Vs[i])
            break

    print(f"L = {L*1e3:.3f} mm,  V_pi = {V_PI:.3f} V")
    if cross_V is not None:
        I_cross = np.interp(cross_V, V, I2D) * L
        print(f"r_d = 10.55 kohm  at  V_F = {cross_V:.3f} V "
              f"(I = {I_cross*1e6:.2f} uA)")

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.semilogy(Vs, Rs, "o-", color="#1B3B6F", lw=2, ms=5,
                label=r"$r_d = (dV/dI)\,/\,L$  (from CHARGE)")
    ax.axhline(R_F_BOOK, color="#F4A300", lw=2, ls="--",
               label=r"Book $R_F = 10.55\,\mathrm{k\Omega}$")
    ax.axvline(V_PI, color="#7209B7", lw=1.6, ls=":",
               label=r"$V_\pi \approx 0.863\,$V")
    if cross_V is not None:
        ax.plot([cross_V], [R_F_BOOK], "*", color="#F4A300", ms=20,
                markeredgecolor="#1B3B6F", zorder=5)
        ax.annotate(f"  crossing\n  V = {cross_V:.3f} V",
                    (cross_V, R_F_BOOK), textcoords="offset points",
                    xytext=(12, 10), fontsize=10, color="#1B3B6F")
    ax.set_xlabel(r"Forward bias  $V_F$  [V]", fontsize=12)
    ax.set_ylabel(r"Differential resistance  $r_d$  [$\Omega$]", fontsize=12)
    ax.set_title("PIN forward-bias differential resistance vs. bias  (sim_id 109)",
                 fontsize=13, color="#1B3B6F")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=10, loc="upper right")
    fig.tight_layout()
    fig.savefig(OUT, dpi=130)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
