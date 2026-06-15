#!/usr/bin/env python3
"""
run_specific_sim.py — Re-run ANY recorded simulation through the real CHARGE+FDE
pipeline and check that it reproduces the V_pi*L and loss on record.

It is fully interactive: it asks for
    1) a path to a results CSV file  (any run, e.g. one under results_archive/)
    2) a sim_id from that file
then reads that sim's 6 input parameters, applies them to the existing
Lumerical templates via the existing system code (set_charge/set_fde_parameters),
runs CHARGE -> FDE, and compares the fresh result against the recorded one.

All output (result.csv, result_full.csv, errors.csv, raw sweep) is written into
results_archive/verify_<sim_id>/ — the source file and the canonical
'simulation csv/result.csv' are never touched.

Run on the Windows VM (Lumerical required), from the PS_Opt_V2 directory:
    python system/run_specific_sim.py
"""

import os
import sys

# This script lives in system/. Make its own dir importable so the flat
# imports below (config, run_simulation, ...) resolve from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))     # .../PS_Opt_V2/system
sys.path.insert(0, HERE)
BASE_DIR = os.path.dirname(HERE)                       # .../PS_Opt_V2

import pandas as pd  # noqa: E402

import config            # noqa: E402
import run_simulation    # noqa: E402

PARAM_COLS = list(config.SWEEP_PARAMETERS.keys())  # w_r, h_si, doping, S, length (lambda fixed)
ARCHIVE_DIR = os.path.join(BASE_DIR, "results_archive")
DEFAULT_CSV = config.RESULTS_CSV_FILE              # offered as the Enter-default
TOLERANCE = 0.01                                   # pass if within 1% of the record


def ask_results_csv():
    """Prompt for a results-file path (Enter = canonical result.csv)."""
    while True:
        raw = input(f"Path to results CSV [{DEFAULT_CSV}]: ").strip().strip('"')
        path = raw or DEFAULT_CSV
        if os.path.exists(path):
            return path
        print(f"  not found: {path}")


def ask_sim_id(df):
    """Prompt for a sim_id that exists in the loaded file."""
    ids = sorted(df["sim_id"].astype(int).tolist())
    print(f"Available sim_ids: {ids[0]}..{ids[-1]} ({len(ids)} total)")
    while True:
        raw = input("Enter sim_id to verify: ").strip()
        try:
            sim_id = int(raw)
        except ValueError:
            print("  please enter an integer")
            continue
        if sim_id in ids:
            return sim_id
        print(f"  sim_id {sim_id} is not in this file")


def redirect_outputs(sim_id):
    """Point every output path at results_archive/verify_<sim_id>/ and start clean."""
    out_dir = os.path.join(ARCHIVE_DIR, f"verify_{sim_id}")
    os.makedirs(out_dir, exist_ok=True)

    config.RESULTS_CSV_FILE = os.path.join(out_dir, "result.csv")
    config.RESULTS_FULL_CSV_FILE = os.path.join(out_dir, "result_full.csv")
    config.ERRORS_CSV_FILE = os.path.join(out_dir, "errors.csv")
    config.RAW_OUTPUT_DIR = os.path.join(out_dir, "raw")
    config.RUN_TIMESTAMP = f"verify_{sim_id}"  # used by sim_handler for the raw subfolder

    for f in (config.RESULTS_CSV_FILE, config.RESULTS_FULL_CSV_FILE, config.ERRORS_CSV_FILE):
        if os.path.exists(f):
            os.remove(f)
    return out_dir


def compare(label, got, ref):
    rel = abs(got - ref) / abs(ref) if ref else float("inf")
    ok = rel <= TOLERANCE
    print(f"  {label:<18} got={got:.4g}   ref={ref:.4g}   Δ={rel*100:.2f}%   [{'PASS' if ok else 'FAIL'}]")
    return ok


def main():
    src = ask_results_csv()
    df = pd.read_csv(src)
    if "sim_id" not in df.columns:
        sys.exit(f"[ERROR] no 'sim_id' column in {src}")
    df["sim_id"] = df["sim_id"].astype(int)

    sim_id = ask_sim_id(df)
    row = df[df["sim_id"] == sim_id].iloc[0]

    missing = [c for c in PARAM_COLS if c not in row or pd.isna(row[c])]
    if missing:
        sys.exit(f"[ERROR] sim_id {sim_id} is missing parameters: {missing}")
    params = {c: float(row[c]) for c in PARAM_COLS}

    out_dir = redirect_outputs(sim_id)

    print(f"\n=== Verifying sim_id {sim_id}  (source: {src}) ===")
    print("Parameters:")
    for c in PARAM_COLS:
        print(f"  {c:<10} = {params[c]:.6g}")
    print(f"Output dir: {out_dir}\n")

    result = run_simulation.run_row(params, sim_id=sim_id)
    if result is None:
        sys.exit(f"[ERROR] sim {sim_id} failed — see {config.ERRORS_CSV_FILE}")

    print("\nResults vs. record:")
    ok = True
    if "v_pi_l_Vmm" in row and not pd.isna(row["v_pi_l_Vmm"]):
        ok &= compare("v_pi_l (V*mm)", result["v_pi_l_Vmm"], float(row["v_pi_l_Vmm"]))
    if "loss_at_v_pi_dB_per_cm" in row and not pd.isna(row["loss_at_v_pi_dB_per_cm"]):
        ok &= compare("loss (dB/cm)", result["loss_at_v_pi_dB_per_cm"], float(row["loss_at_v_pi_dB_per_cm"]))

    print(f"\n=== {'PASS — reproduced within tolerance' if ok else 'FAIL — see deltas above'} ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
