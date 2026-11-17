# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Train a Brush dataset headless and time it (plain Python).

python tools/DBS_train_brush.py <dataset_dir> [--steps 7000] [--brush bin/brush-v0.3.0/brush_app.exe]
    [--max-resolution 1920] [-- extra Brush flags]

Writes <dataset_dir>_exports/splat_<steps>.ply (only at the end). Brush keeps the dataset's world,
so the .ply is in the track's space (Brush header: "Vertical axis: y").
"""

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    argv = sys.argv[1:]
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--steps", type=int, default=7000)
    ap.add_argument("--brush", default=os.path.join(ROOT, "bin", "brush-v0.3.0", "brush_app.exe"))
    ap.add_argument("--max-resolution", type=int, default=1920)
    a = ap.parse_args(argv)
    data = os.path.abspath(a.dataset)
    export = data.rstrip("\\/") + "_exports"
    if not os.path.isdir(export):
        os.makedirs(export)
    cmd = [a.brush, data, "--total-steps", str(a.steps), "--export-every", str(a.steps),
           "--export-path", export, "--export-name", "splat_{iter}.ply", "--eval-every", str(10 ** 9),
           "--max-resolution", str(a.max_resolution)] + extra
    print("DBS:", subprocess.list2cmdline(cmd))
    t0 = time.time()
    res = subprocess.run(cmd)
    print("DBS: Brush exit %d in %.1f min" % (res.returncode, (time.time() - t0) / 60.0))
    ply = os.path.join(export, "splat_%d.ply" % a.steps)
    print("DBS: %s %s" % (ply, "OK" if os.path.isfile(ply) else "missing"))
    sys.exit(res.returncode)


main()
