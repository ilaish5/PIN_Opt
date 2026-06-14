"""Check whether an INTERCONNECT .icp still references an external file by path.

The equalized circuit (mzm_eye_equalized.icp) contains an S-parameter element
that was loaded from rc_equalizer_S21.s2p. When the .s2p moves, that reference
can break -- *if* the element keeps a live "load from file" path rather than
embedding the data. This script loads the .icp and prints any file-path
property found on each root element, so you can confirm the reference (or its
absence) after moving files.

Interpreting the output:
  - No path printed  -> S-parameters are embedded; moving the .s2p is harmless.
  - A path printed    -> live reference; make sure it points at the current
                         location (Lumerical_Files/eye_rc_interconnect/), and
                         re-load + re-save the .icp if it is stale.

Run with the Lumerical python (INTERCONNECT required):
    & "C:\\Program Files\\Lumerical\\v231\\python\\python.exe" check_icp_s2p_reference.py
    # optional: pass an explicit .icp path as argv[1]
"""
import sys
from pathlib import Path

LUMERICAL_API_PATH = r"C:\Program Files\Lumerical\v231\api\python"
sys.path.append(LUMERICAL_API_PATH)
import lumapi  # noqa: E402

HERE = Path(__file__).resolve().parent          # analysis/
ROOT = HERE.parent                               # PS_Opt_V2/
DEFAULT_ICP = (ROOT / "Lumerical_Files" / "eye_rc_interconnect"
               / "mzm_eye_equalized.icp")

# Property names INTERCONNECT uses for a Touchstone / measurement file path,
# across element types. We probe each and print whichever exist.
PATH_PROPS = [
    "load from file",
    "filename",
    "s parameters filename",
    "s-parameters filename",
    "measurement filename",
    "file name",
]


def main():
    icp = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ICP
    if not icp.exists():
        sys.exit(f"Not found: {icp}")

    ic = lumapi.INTERCONNECT(hide=True)
    ic.load(str(icp))
    ic.groupscope("::Root Element")
    ic.selectall()
    n = int(ic.getnumber())
    print(f"Loaded {icp.name}  ({n} root elements)\n")

    found_any = False
    for i in range(1, n + 1):
        name = ic.get("name", i)
        for prop in PATH_PROPS:
            try:
                val = ic.getnamed(name, prop)
            except Exception:
                continue
            print(f"  {name}  |  {prop} = {val!r}")
            found_any = True

    if not found_any:
        print("  No file-path property found on any element.")
        print("  -> S-parameters appear embedded; moving the .s2p is harmless.")
    ic.close()


if __name__ == "__main__":
    main()
