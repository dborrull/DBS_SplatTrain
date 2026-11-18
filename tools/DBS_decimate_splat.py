# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Decimate a Gaussian splat .ply (plain Python 3; the node runs it with Nuke's python.exe).

python tools/DBS_decimate_splat.py splat_30000.ply --keep=500000 [--out=file.ply]

Keeps the most visible splats (opacity x area) and writes them next to the source with the
count as a suffix (splat_30000_500k.ply), so the original is never overwritten.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nuke"))
from dbs_splattrain import splat_ply  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--keep", type=int, required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    out = a.out or splat_ply.decimated_name(a.src, a.keep)
    if os.path.abspath(out) == os.path.abspath(a.src):
        sys.exit("DBS: the output would overwrite the source")
    t0 = time.time()
    try:
        kept, total = splat_ply.decimate(a.src, out, a.keep)
    except (OSError, splat_ply.PlyError) as e:
        sys.exit("DBS: %s" % e)
    print("DBS: kept %d of %d splats in %.1f s -> %s" % (kept, total, time.time() - t0, out))


if __name__ == "__main__":
    main()
