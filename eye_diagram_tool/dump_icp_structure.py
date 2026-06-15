"""Dump the element structure of an INTERCONNECT .icp project.

We want to drive the *working* prebuilt circuits (mzm_eye_baseline.icp /
mzm_eye_equalized.icp) per sim_id by loading them and updating component values
in place -- NOT by rebuilding from scratch. To set the right properties we first
need the real element names, types, and tunable property values as they exist
in the saved project (which may differ from any builder script).

This script loads an .icp, lists every root element with its model/type, and
prints the values of a set of candidate tunable properties (the ones an
eye/equalizer circuit cares about). Paste the output back so the per-sim eye
tool can target the exact names.

Run with the Lumerical python (INTERCONNECT required), from PS_Opt_V2/:
    & "C:\\Program Files\\Lumerical\\v231\\python\\python.exe" analysis/dump_icp_structure.py
    # optional: pass an explicit .icp path as argv[1]
                (default: both baseline and equalized are dumped)
"""
import sys
from pathlib import Path

LUMERICAL_API_PATH = r"C:\Program Files\Lumerical\v231\api\python"
sys.path.append(LUMERICAL_API_PATH)
import lumapi  # noqa: E402

HERE = Path(__file__).resolve().parent          # analysis/
ROOT = HERE.parent                               # PS_Opt_V2/
ICP_DIR = ROOT / "Lumerical_Files" / "eye_rc_interconnect"

# Candidate properties worth reporting for an eye/equalizer circuit. Probed per
# element; only the ones that actually exist are printed.
PROBE_PROPS = [
    "model", "type", "prefix",
    "cutoff frequency", "order",                 # LP RC filter (the PIN device)
    "load from file", "s parameters filename",   # S-parameter equalizer
    "bitrate", "amplitude", "bias", "modulation type",
    "frequency", "power",                        # laser
    "responsivity",                              # photodetector
    "gain",                                      # amplifier
]


def dump(ic, icp_path):
    ic.load(str(icp_path))
    ic.groupscope("::Root Element")
    ic.selectall()
    n = int(ic.getnumber())
    print(f"\n===== {icp_path.name}  ({n} root elements) =====")
    for i in range(1, n + 1):
        name = ic.get("name", i)
        print(f"\n[{i}] {name}")
        for prop in PROBE_PROPS:
            try:
                val = ic.getnamed(name, prop)
            except Exception:
                continue
            print(f"      {prop:<24} = {val!r}")


def main():
    if len(sys.argv) > 1:
        targets = [Path(sys.argv[1])]
    else:
        targets = [ICP_DIR / "mzm_eye_baseline.icp",
                   ICP_DIR / "mzm_eye_equalized.icp"]

    ic = lumapi.INTERCONNECT(hide=True)
    try:
        for icp in targets:
            if icp.exists():
                dump(ic, icp)
            else:
                print(f"\n(skip, not found) {icp}")
    finally:
        ic.close()


if __name__ == "__main__":
    main()
