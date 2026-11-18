# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Gaussian splat .ply files: count and decimate (plain Python: Nuke ships no numpy).

Works on binary little-endian .ply with float properties (Brush, Inria 3DGS, most tools).
Decimation keeps the splats that cover most of the picture: opacity times the area of the
splat's two largest axes (scales are stored as logs, opacity as a logit). The kept splats keep
all their properties (colour, spherical harmonics) and their order."""

import array
import math
import os
import sys

PRESETS = {"500k": 500000, "100k": 100000}


class PlyError(Exception):
    pass


def header(path):
    """(vertex count, property names, header size in bytes, comments) of a splat .ply."""
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise PlyError("not a .ply file: %s" % path)
        n, props, comments, fmt = None, [], [], None
        while True:
            line = f.readline()
            if not line:
                raise PlyError("no end_header: %s" % path)
            words = line.decode("ascii", "replace").split()
            if not words:
                continue
            if words[0] == "format":
                fmt = words[1]
            elif words[0] == "comment":
                comments.append(" ".join(words[1:]))
            elif words[0] == "element":
                if words[1] != "vertex" or n is not None:
                    raise PlyError("only one 'vertex' element is supported: %s" % path)
                n = int(words[2])
            elif words[0] == "property":
                if words[1] != "float":
                    raise PlyError("only float properties are supported (%s): %s" % (words[1], path))
                props.append(words[2])
            elif words[0] == "end_header":
                break
        if fmt != "binary_little_endian":
            raise PlyError("only binary little-endian .ply is supported: %s" % path)
        return n, props, f.tell(), comments


def count(path):
    return header(path)[0]


def short_count(n):
    """313258 -> '313k', 1200000 -> '1.2M', 950 -> '950'."""
    if n >= 1000000:
        return ("%.1fM" % (n / 1e6)).replace(".0M", "M")
    if n >= 1000:
        return "%dk" % round(n / 1000.0)
    return str(n)


def describe(path):
    """'313,258 splats, 73.9 MB' (or the reason it cannot be read)."""
    try:
        n = count(path)
    except (OSError, PlyError) as e:
        return str(e)
    return "{:,} splats, {:.1f} MB".format(n, os.path.getsize(path) / 1e6)


def decimated_name(path, keep):
    """splat_30000.ply, 500000 -> splat_30000_500k.ply (next to it)."""
    root, ext = os.path.splitext(path)
    return "%s_%s%s" % (root, short_count(keep) if keep % 1000 == 0 else str(keep), ext)


def decimate(src, dst, keep):
    """Write the `keep` most visible splats of src to dst. Returns (kept, total)."""
    n, props, start, _ = header(src)
    for p in ("opacity", "scale_0", "scale_1", "scale_2"):
        if p not in props:
            raise PlyError("no '%s' property: is it a Gaussian splat? %s" % (p, src))
    with open(src, "rb") as f:
        f.seek(start)
        data = f.read()
    k = len(props)
    if len(data) < n * k * 4:
        raise PlyError("file is shorter than its header says: %s" % src)
    if keep >= n:
        raise PlyError("it has %d splats, not more than %d: nothing to decimate" % (n, keep))
    vals = array.array("f")
    vals.frombytes(data[:n * k * 4])
    if sys.byteorder != "little":
        vals.byteswap()
    io, i0, i1, i2 = (props.index(p) for p in ("opacity", "scale_0", "scale_1", "scale_2"))
    score = []
    for r in range(0, n * k, k):
        a, b, c = vals[r + i0], vals[r + i1], vals[r + i2]
        lo = min(a, b, c)
        o = vals[r + io]
        o = 1.0 / (1.0 + math.exp(-o)) if o > -60 else 0.0
        score.append(o * math.exp(min(a + b + c - lo, 80.0)))      # opacity x area of the 2 largest axes
    kept = sorted(sorted(range(n), key=score.__getitem__, reverse=True)[:keep])
    rec = k * 4
    body = b"".join(data[i * rec:(i + 1) * rec] for i in kept)
    with open(src, "rb") as f:
        head = f.read(start).decode("ascii")
    head = head.replace("element vertex %d\n" % n, "element vertex %d\n" % keep, 1)
    if "element vertex %d\n" % keep not in head:
        raise PlyError("could not rewrite the header of %s" % src)
    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(head.encode("ascii"))
        f.write(body)
    if os.path.exists(dst):
        os.remove(dst)
    os.rename(tmp, dst)
    return keep, n
