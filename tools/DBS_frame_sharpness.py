# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Measure how sharp each frame of a plate is (Nuke terminal, Non-commercial OK).

"C:/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t tools/DBS_frame_sharpness.py <script.nk> <plate>
    --first=F --last=L --out=sharpness.json

Sharpness = mean of the squared Laplacian (edges) at half resolution: a frame with motion blur has
soft edges and a low value. The values only compare frames of the same shot. Writes
{"frames": {"1001": 0.0123, ...}} to --out. Uses 5 Python Node objects (Non-commercial allows 10).
"""

import argparse
import json
import os
import sys
import time

import nuke

# The script may hold DBS_SplatTrain nodes, whose callbacks import the module.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nuke"))

LAPLACIAN = [0, 1, 0, 1, -4, 1, 0, 1, 0]


def measure(plate, first, last):
    w, h = plate.width(), plate.height()
    small = nuke.nodes.Reformat(type="scale", scale=0.5, filter="Cubic")
    small.setInput(0, plate)
    lap = nuke.nodes.Matrix(channels="rgb", normalize=False)
    lap["matrix"].setValue(LAPLACIAN)
    lap.setInput(0, small)
    sq = nuke.nodes.Expression(expr0="(r*r+g*g+b*b)/3", expr1="(r*r+g*g+b*b)/3", expr2="(r*r+g*g+b*b)/3")
    sq.setInput(0, lap)
    ct = nuke.nodes.CurveTool(operation="Avg Intensities", channels="rgb")
    ct["ROI"].setValue([2, 2, w // 2 - 2, h // 2 - 2])   # skip the border (black edges, bbox)
    ct.setInput(0, sq)
    nuke.execute(ct, first, last)
    return {f: ct["intensitydata"].valueAt(f, 0) for f in range(first, last + 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("plate")
    ap.add_argument("--first", type=int, required=True)
    ap.add_argument("--last", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(sys.argv[1:])
    nuke.scriptOpen(a.script)
    plate = nuke.toNode(a.plate)
    if plate is None:
        sys.exit("DBS: node not found: %s" % a.plate)
    t0 = time.time()
    s = measure(plate, a.first, a.last)
    with open(a.out, "w") as f:
        json.dump({"plate": a.plate, "frames": {str(k): v for k, v in s.items()}}, f, indent=1)
    print("DBS: sharpness of %d frames in %.1f s -> %s" % (len(s), time.time() - t0, a.out))


main()
