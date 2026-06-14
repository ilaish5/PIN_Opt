# system/eye_lib.py
# Helper library for the per-sim_id eye-diagram tool (run_specific_eye.py).
#
# Pure math / I-O helpers that do NOT touch the optimization pipeline:
#   - small-signal device transfer H_device (book eq 13)
#   - RC peaking equalizer design for a target bandwidth (book eqs 46-49)
#   - corrected equalizer transfer H_eq (spec EYE_TOOL_SPEC.md sec 3.4 -- the
#     book's printed eq (20) is wrong; this is the consistent form)
#   - Touchstone (.s2p) writer for the equalizer S21
#   - find_3dB and eye-folding helpers
#
# Everything here takes the device parameters (R_F, C_F, R_S, f_3dB) as inputs,
# so it is independent of how Stage A extracts/normalizes them.

import numpy as np

R_DRV_DEFAULT = 50.0  # driver source resistance [ohm] (book: R_drv = 50)


# ---------------------------------------------------------------------------
# Small-signal transfer functions
# ---------------------------------------------------------------------------

def H_device(f, R_S, R_F, C_F, R_drv=R_DRV_DEFAULT):
    """Baseline electrical transfer driver->junction (voltage divider).

    V_junction / V_source with Z_diode = R_F / (1 + j w R_F C_F) in series with
    R_S behind the driver R_drv. Pole at f_3dB = 1/(2 pi (R_S+R_drv) C_F).
    (Same form as the legacy build_eye_rc.py::H_base, generalized.)
    """
    s = 1j * 2 * np.pi * np.asarray(f, dtype=float)
    R_dc = R_drv + R_S
    return R_F / (R_dc * (1 + s * R_F * C_F) + R_F)


def H_eq(f, R_eq, C_eq, eta):
    """Corrected equalizer transfer (EYE_TOOL_SPEC.md sec 3.4).

        H_eq(w) = (1 + j w R_eq C_eq) / (eta + j w R_eq C_eq)

    H_eq(0) = 1/eta  (book eq 21),  H_eq(inf) = 1  (book eq 22).
    NOTE: the book's printed eq (20) gives H_eq(0)=1 and is wrong; this is the
    form that matches eqs 19/21/22 and Fig. 17.
    """
    s = 1j * 2 * np.pi * np.asarray(f, dtype=float)
    RC = R_eq * C_eq
    return (1 + s * RC) / (eta + s * RC)


def f_3dB_device(R_S, C_F, R_drv=R_DRV_DEFAULT):
    """Book eq (18)/(45): f_3dB = 1 / (2 pi (R_S + R_drv) C_F)."""
    return 1.0 / (2 * np.pi * (R_S + R_drv) * C_F)


# ---------------------------------------------------------------------------
# Self-consistent small-signal extraction from a single SSAC sweep
# ---------------------------------------------------------------------------

def extract_small_signal(f, Z_reported, norm, L, R_drv=R_DRV_DEFAULT, n_avg=2):
    """Read the full small-signal picture off ONE SSAC impedance sweep.

    Applies the single consistent 2D->device length normalization to the WHOLE
    impedance, Z_device = Z_reported * (norm / L), then reads everything off the
    same Y_device = 1 / Z_device. No book values, no per-quantity rescaling.

    The PIN junction has TWO capacitances, so C(f) = Im(Y)/w is read at both ends:
      - C_diff = low-f  plateau -> forward diffusion cap (sets the injection BW)
      - C_dep  = high-f plateau -> depletion/junction cap
    and likewise R_F (low-f Re(Z) - R_S) and R_S (high-f Re(Z)).

    Returns a dict of scalars (R_S, R_F, C_diff, C_dep, tau, f_3dB_diff,
    f_3dB_dep) plus the device-scaled arrays (f, Z, Y, C) for the Bode plot.
    f_3dB_diff is the physical forward-injection modulation bandwidth.
    """
    f = np.asarray(f, dtype=float)
    Z = np.asarray(Z_reported, dtype=complex) * (norm / L)
    Y = 1.0 / Z
    w = 2 * np.pi * f
    C = np.imag(Y) / w
    R_S = float(np.real(Z[-1]))                 # high-f: cap shorts R_F -> R_S
    R_F = float(np.real(Z[0])) - R_S            # low-f plateau minus R_S
    C_diff = float(np.mean(C[:n_avg]))          # low-f cap
    C_dep = float(np.mean(C[-n_avg:]))          # high-f cap
    return {
        "R_S": R_S, "R_F": R_F, "C_diff": C_diff, "C_dep": C_dep,
        "tau": R_F * C_diff,
        "f_3dB_diff": 1.0 / (2 * np.pi * (R_S + R_drv) * C_diff),
        "f_3dB_dep": 1.0 / (2 * np.pi * (R_S + R_drv) * C_dep),
        "f": f, "Z": Z, "Y": Y, "C": C,
    }


# ---------------------------------------------------------------------------
# Equalizer design (book eqs 46-49, zero-pole invariant eq 19)
# ---------------------------------------------------------------------------

def design_equalizer(R_F, C_F, f_3dB, R_S=0.0, target_bw=100e9,
                     mode="corrected", R_drv=R_DRV_DEFAULT):
    """Size the RC peaking equalizer for a target equalized bandwidth.

        eta = target_bw / f_3dB,  IL_dB = 20*log10(eta),  C_eq = C_F / eta

    `mode` sets where the equalizer zero sits (the only difference between modes;
    the .s2p depends only on R_eq*C_eq and eta):

    - "corrected" (default): zero at the loaded device pole f_3dB
      (R_eq*C_eq = (R_S+R_drv)*C_F) -> pole at eta*f_3dB, so BW extends to
      eta*f_3dB. This is the form that actually works.
    - "book": the book's eqs 18/19/48/49 (R_eq=R_F*eta, zero at the ~43.5 MHz
      diffusion corner). Does NOT extend BW (WORKLOG sec 6b); kept for comparison.

    Returns the components + zero/pole frequencies. Does not cap the target.
    """
    eta = float(target_bw) / float(f_3dB)
    C_eq = C_F / eta
    if mode == "book":
        RC = R_F * C_F                 # zero at diffusion corner 1/(2pi R_F C_F)
    elif mode == "corrected":
        RC = (R_S + R_drv) * C_F       # zero at loaded pole f_3dB
    else:
        raise ValueError(f"unknown mode {mode!r} (use 'corrected' or 'book')")
    R_eq = RC / C_eq
    f_zero = 1.0 / (2 * np.pi * RC)
    f_pole = eta / (2 * np.pi * RC)
    return {
        "mode": mode,
        "eta": eta,
        "R_eq": R_eq,
        "C_eq": C_eq,
        "IL_dB": 20.0 * np.log10(eta),
        "f_zero": f_zero,            # corrected: == f_3dB
        "f_pole": f_pole,            # corrected: == eta*f_3dB
        "f_3dB_eq": eta * f_3dB,     # target equalized bandwidth (book eq 47)
        "target_bw": float(target_bw),
    }


# ---------------------------------------------------------------------------
# Touchstone (.s2p) writer
# ---------------------------------------------------------------------------

def write_equalizer_touchstone(path, R_eq, C_eq, eta, sample_rate, n_points=800,
                               z0=50.0):
    """Write a 2-port Touchstone (RI, R z0) whose S21 = corrected H_eq(f).

    S11 = S22 = S12 = 0; only S21 carries the equalizer transfer. Frequency grid
    prepends a 1 Hz point then geomspace(1e3, sample_rate, n_points) (mirrors the
    legacy build_eye_rc.py grid). Header: '# Hz S RI R {z0}'.
    Row order per Touchstone 2-port: f  S11re S11im  S21re S21im  S12re S12im  S22re S22im.
    Returns abs(S21[0]) (the DC magnitude, ~1/eta).
    """
    f = np.concatenate([[1.0], np.geomspace(1e3, sample_rate, n_points)])
    s21 = H_eq(f, R_eq, C_eq, eta)
    with open(path, "w") as fh:
        fh.write("! RC peaking equalizer  S21(f) = (1 + jwR_eqC_eq)/(eta + jwR_eqC_eq)\n")
        fh.write(f"! corrected H_eq per EYE_TOOL_SPEC sec 3.4  (eta={eta:.6g}, "
                 f"R_eq={R_eq:.6g} ohm, C_eq={C_eq:.6g} F)\n")
        fh.write(f"# Hz S RI R {z0:g}\n")
        for fr, h in zip(f, s21):
            fh.write(f"{fr:.8e} 0 0 {h.real:.8e} {h.imag:.8e} 0 0 0 0\n")
    return float(abs(s21[0]))


# ---------------------------------------------------------------------------
# Bode / metric helpers
# ---------------------------------------------------------------------------

def find_3dB(f, H):
    """-3 dB frequency [Hz] of |H| relative to |H(f[0])|; inf if never falls."""
    f = np.asarray(f, dtype=float)
    mag = 20 * np.log10(np.abs(H) + 1e-30)
    tgt = mag[0] - 3.0
    below = np.where(mag < tgt)[0]
    if len(below) == 0:
        return float("inf")
    i = below[0]
    if i == 0:
        return float(f[0])
    f1, f2 = np.log10(f[i - 1]), np.log10(f[i])
    return float(10 ** (f1 + (tgt - mag[i - 1]) * (f2 - f1) / (mag[i] - mag[i - 1])))


def fold_eye(t, v, bitrate, n_ui=2):
    """Fold a waveform into n_ui-wide windows for an eye-density plot.

    Returns (t_ps, windows) where t_ps is the per-window time axis in ps and
    windows is a 2D array (n_windows, span). Mirrors plot_eye_diagram_interconnect.
    """
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    dt = t[1] - t[0]
    span = n_ui * int(round((1.0 / bitrate) / dt))
    m = (len(v) // span) * span
    win = v[:m].reshape(-1, span)
    t_ps = np.arange(span) * dt * 1e12
    return t_ps, win


if __name__ == "__main__":
    # Self-test against the book design (Table 3 device + IL=12 dB book equalizer
    # and the 100 Gbps design).
    R_F, C_F, R_S = 10.55e3, 0.3471e-12, 23.31
    f3 = f_3dB_device(R_S, C_F)
    print(f"f_3dB (eq 18) = {f3/1e9:.3f} GHz  (book ~6.25)")

    f = np.geomspace(1e5, 1e12, 6000)
    print("\n-- book mode, IL=12 dB design (eta=3.98) --")
    d = design_equalizer(R_F, C_F, f3, R_S=R_S, target_bw=3.98 * f3, mode="book")
    print(f"  eta={d['eta']:.3f}  IL={d['IL_dB']:.2f} dB  R_eq={d['R_eq']/1e3:.2f} kohm  "
          f"C_eq={d['C_eq']*1e15:.2f} fF  zero={d['f_zero']/1e6:.1f} MHz")
    print(f"  (book: eta=3.98, IL=12 dB, R_eq~41.98 kohm, C_eq~87.2 fF, zero~43.5 MHz)")
    casc = H_eq(f, d["R_eq"], d["C_eq"], d["eta"]) * H_device(f, R_S, R_F, C_F)
    print(f"  cascade -3dB-from-peak = {find_3dB(f, casc/np.max(np.abs(casc)))/1e9:.2f} GHz (no real BW extension)")

    for tbw in (100e9,):
        print(f"\n-- corrected mode, 100 Gbps (target_bw={tbw/1e9:.0f} GHz) --")
        d = design_equalizer(R_F, C_F, f3, R_S=R_S, target_bw=tbw, mode="corrected")
        print(f"  eta={d['eta']:.3f}  IL={d['IL_dB']:.2f} dB  R_eq={d['R_eq']/1e3:.3f} kohm  "
              f"C_eq={d['C_eq']*1e15:.2f} fF")
        print(f"  zero={d['f_zero']/1e9:.3f} GHz (== f_3dB)  pole={d['f_pole']/1e9:.2f} GHz (== eta*f_3dB)")
        casc = H_eq(f, d["R_eq"], d["C_eq"], d["eta"]) * H_device(f, R_S, R_F, C_F)
        print(f"  cascade -3dB-from-peak = {find_3dB(f, casc/np.max(np.abs(casc)))/1e9:.2f} GHz "
              f"(should approach eta*f_3dB={d['f_3dB_eq']/1e9:.0f} GHz)")

    import tempfile, os
    p = os.path.join(tempfile.gettempdir(), "_eqtest.s2p")
    dc = write_equalizer_touchstone(p, d["R_eq"], d["C_eq"], d["eta"],
                                    sample_rate=100e9 * 64)
    print(f"\n  touchstone DC |S21| = {dc:.4f}  (expect 1/eta = {1/d['eta']:.4f})")
    with open(p) as fh:
        head = [next(fh) for _ in range(4)]
    print("  header:\n   " + "   ".join(head))
