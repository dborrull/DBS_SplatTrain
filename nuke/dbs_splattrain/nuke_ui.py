# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Nuke side of DBS_SplatTrain: the node's buttons.

Nuke Non-commercial allows 10 Python Node objects per session, so every button works from the
node it belongs to (nuke.thisNode()) and reaches everything else by name (Tcl and knob paths).
The heavy work runs in separate processes, so Nuke stays usable:
  export: a Nuke terminal (`-t`) runs tools/DBS_export_shot.py on the saved script
  train:  Brush (brush_app.exe) trains on the exported dataset
Their progress is shown under the buttons and in the node's label."""

import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import nuke

from .colour import SRGB_ROLE
from .template import node_template

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORTER = os.path.join(ROOT, "tools", "DBS_export_shot.py")
DEFAULT_BRUSH = os.path.join(ROOT, "bin", "brush-v0.3.0", "brush_app.exe")
PASSTHROUGH = ("Dot", "NoOp", "PostageStamp")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW
PROGRESS_EXPORTS = 20      # Brush writes this many .ply during training: they show the progress

_jobs = {}                 # node full name -> running subprocess.Popen


class SplatError(Exception):
    pass


def _log(msg):
    print("[DBS_SplatTrain] %s" % msg)


def _fwd(p):
    return p.replace("\\", "/")


# ---- node creation ------------------------------------------------------------------------

def create_node():
    brush = DEFAULT_BRUSH if os.path.isfile(DEFAULT_BRUSH) else ""
    text = node_template(_fwd(brush), SRGB_ROLE, *_script_range())
    path = os.path.join(_temp_dir(), "DBS_SplatTrain_node.nk")
    with open(path, "w") as f:
        f.write(text)
    nuke.nodePaste(path)


def _script_range():
    """(first, last) of Project Settings, read through Tcl (no Node object)."""
    try:
        return int(nuke.tcl("value root.first_frame")), int(nuke.tcl("value root.last_frame"))
    except Exception:
        return 0, 0


def _temp_dir():
    import tempfile
    return tempfile.gettempdir()


# ---- reading the graph by name (no Node objects) ------------------------------------------

def _input_name(node_name, i):
    """Full name of input i of a node, through Dots, or None."""
    try:
        name = nuke.tcl("full_name [input %s %d]" % (node_name, i))
    except Exception:
        return None
    for _ in range(20):
        if not name or name == "0":
            return None
        try:
            cls = nuke.tcl("class %s" % name)
        except Exception:
            return None
        if cls not in PASSTHROUGH:
            return name
        try:
            name = nuke.tcl("full_name [input %s 0]" % name)
        except Exception:
            return None
    return None


def _work_dir(node):
    d = node["work_dir"].value().strip()
    if d:
        return d
    try:
        script = nuke.scriptName()
    except Exception:
        raise SplatError("Save the script first: the export reads it from disk.")
    return _fwd(os.path.join(os.path.dirname(script), "DBS_SplatTrain", node.name()))


def _set_status(node, text, state=None):
    def _do():
        try:
            node["status"].setValue(text)
            if state is not None:
                node["dbs_state"].setValue(state)
        except Exception:
            pass            # the node was deleted
    if threading.current_thread() is threading.main_thread():
        _do()
    else:
        nuke.executeInMainThread(_do)


def _busy(node):
    p = _jobs.get(node.fullName())
    return p is not None and p.poll() is None


def _tail(path, n=12):
    try:
        with open(path, "r", errors="replace") as f:
            lines = [l.rstrip() for l in f if l.strip()]
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def _run_async(node, cmd, log_path, on_done, on_poll=None):
    """Start cmd without a console window, its output to log_path; on_done(code, seconds) runs in
    Nuke's main thread when it ends; on_poll(seconds) runs in the waiting thread every 5 s.
    It runs in the log's folder: Brush writes its GPU autotune cache to target/ in its working
    folder, and Nuke's own (Program Files) is read-only, so Brush would crash on start."""
    log = open(log_path, "w")
    _log(subprocess.list2cmdline(cmd))
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                         cwd=os.path.dirname(log_path))
    _jobs[node.fullName()] = p
    t0 = time.time()

    def _wait():
        while p.poll() is None:
            time.sleep(5)
            if on_poll is not None and p.poll() is None:
                on_poll(time.time() - t0)
        log.close()
        code, sec = p.returncode, time.time() - t0
        nuke.executeInMainThread(lambda: on_done(code, sec))

    threading.Thread(target=_wait, daemon=True).start()


def _guard(fn):
    def wrapper(node, *a, **k):
        try:
            if _busy(node):
                raise SplatError("Busy: wait for the current step to finish, or press stop.")
            return fn(node, *a, **k)
        except SplatError as e:
            _set_status(node, "<font color=orange>%s</font>" % e)
            nuke.message("DBS_SplatTrain:\n" + str(e))
    wrapper.__name__ = fn.__name__
    return wrapper


def _minutes(sec):
    return "%.1f min" % (sec / 60.0) if sec >= 60 else "%d s" % sec


# ---- 1. export ----------------------------------------------------------------------------

def _start_export(node, then=None):
    name = node.fullName()
    plate, cam = _input_name(name, 0), _input_name(name, 1)
    points, mask = _input_name(name, 2), _input_name(name, 3)
    if not plate or not cam:
        raise SplatError("Connect the plate to 'plate' and the tracked camera to 'cam'.")
    try:
        script = nuke.scriptName()
    except Exception:
        raise SplatError("Save the script first: the export reads it from disk.")
    if nuke.modified():
        nuke.scriptSave()                     # the export reads the script from disk
    out = _work_dir(node)
    data = os.path.join(out, "dataset")
    if os.path.isdir(data):
        shutil.rmtree(data)                   # no frames left over from an earlier export
    if not os.path.isdir(out):
        os.makedirs(out)
    cmd = [nuke.EXE_PATH] + (["--nc"] if nuke.env.get("nc") else []) + [
        "-t", EXPORTER, script, plate, cam, data, "--step=%d" % max(1, int(node["step"].value()))]
    first, last = int(node["first"].value()), int(node["last"].value())
    if first:
        cmd.append("--first=%d" % first)
    if last:
        cmd.append("--last=%d" % last)
    if points:
        cmd.append("--points=%s" % points)
    if mask:
        cmd.append("--mask=%s" % mask)
    log = os.path.join(out, "export.log")
    _set_status(node, "exporting frames and cameras...", "exporting")

    def done(code, sec):
        n = len(glob.glob(os.path.join(data, "images", "*.png")))
        ok = code == 0 and n > 0 and os.path.isfile(os.path.join(data, "sparse", "0", "images.bin"))
        if not ok:
            _set_status(node, "<font color=orange>export failed: see %s</font>" % _fwd(log), "export failed")
            _log("export failed:\n" + _tail(log))
            return
        _set_status(node, "exported %d frames in %s" % (n, _minutes(sec)), "exported %d frames" % n)
        if then is not None:
            try:
                then(node)
            except SplatError as e:
                _set_status(node, "<font color=orange>%s</font>" % e)

    _run_async(node, cmd, log, done)


@_guard
def export(node):
    _start_export(node)


# ---- 2. train -----------------------------------------------------------------------------

def _start_train(node, then=None):
    out = _work_dir(node)
    data = os.path.join(out, "dataset")
    if not os.path.isfile(os.path.join(data, "sparse", "0", "images.bin")):
        raise SplatError("Nothing exported yet: press '1. export' first.")
    brush = node["brush"].value().strip() or DEFAULT_BRUSH
    if not os.path.isfile(brush):
        raise SplatError("Brush not found: %s" % brush)
    steps = max(100, int(node["steps"].value()))
    exports = os.path.join(out, "splats")
    if not os.path.isdir(exports):
        os.makedirs(exports)
    for old in glob.glob(os.path.join(exports, "progress_*.ply")):
        os.remove(old)
    every = max(1, steps // PROGRESS_EXPORTS)
    cmd = [brush, data, "--total-steps", str(steps), "--export-every", str(every),
           "--export-path", exports, "--export-name", "progress_{iter}.ply",
           "--eval-every", str(10 ** 9), "--max-resolution", str(int(node["max_res"].value()))]
    log = os.path.join(out, "train.log")
    _set_status(node, "training: starting...", "training 0%")

    def poll(sec):
        done_iters = [int(m.group(1)) for m in
                      (re.search(r"progress_(\d+)\.ply$", f) for f in os.listdir(exports)) if m]
        it = max(done_iters) if done_iters else 0
        for i in done_iters:                 # keep only the newest: each one can be 100 MB
            if i < it:
                try:
                    os.remove(os.path.join(exports, "progress_%d.ply" % i))
                except OSError:
                    pass
        pct = 100 * it // steps
        if it:
            left = ", about %s left" % _minutes(sec * (steps - it) / float(it))
        else:
            left = ", first estimate at %d%%" % (100 // PROGRESS_EXPORTS)
        _set_status(node, "training: %d%% (%d / %d steps), %s%s" % (pct, it, steps, _minutes(sec), left),
                    "training %d%%" % pct)

    def done(code, sec):
        final = os.path.join(exports, "progress_%d.ply" % steps)
        if code != 0 or not os.path.isfile(final):
            _set_status(node, "<font color=orange>training failed: see %s</font>" % _fwd(log), "training failed")
            _log("training failed:\n" + _tail(log))
            return
        name = os.path.join(exports, "splat_%d.ply" % steps)
        if os.path.exists(name):
            os.remove(name)
        os.rename(final, name)
        for f in glob.glob(os.path.join(exports, "progress_*.ply")):
            os.remove(f)
        node["splat_file"].setValue(_fwd(name))
        _set_status(node, "trained %d steps in %s" % (steps, _minutes(sec)), "trained")
        if then is not None:
            try:
                then(node)
            except SplatError as e:
                _set_status(node, "<font color=orange>%s</font>" % e)

    _run_async(node, cmd, log, done, poll)


@_guard
def train(node):
    _start_train(node)


# ---- 3. load ------------------------------------------------------------------------------

def _load(node):
    path = node["splat_file"].value().strip()
    if not path:
        found = sorted(glob.glob(os.path.join(_work_dir(node), "splats", "splat_*.ply")), key=os.path.getmtime)
        if not found:
            raise SplatError("No splat yet: train first, or pick a .ply in 'splat'.")
        path = _fwd(found[-1])
        node["splat_file"].setValue(path)
    if not os.path.isfile(path):
        raise SplatError("File not found: %s" % path)
    nuke.knob(node.fullName() + ".DBS_Splat.file", path)
    node["dbs_loaded"].setValue(True)
    _set_status(node, "loaded %s" % os.path.basename(path), "splat loaded")


@_guard
def load(node):
    _load(node)


# ---- 3D setup -----------------------------------------------------------------------------

def _nk_quote(s):
    return '"%s"' % s.replace("\\", "/").replace('"', '\\"')


@_guard
def create_3d(node):
    """Paste GeoImport (the splat) -> SplatRender (through the node's camera) -> OCIOColorSpace
    (sRGB -> scene_linear) to the right of the node, so the splat can be edited in 3D (Field
    nodes, GeoDeletePoints between GeoImport and SplatRender). Connects by 'push [node ...]'
    and pastes with nothing selected: no Node objects besides this one."""
    path = node["splat_file"].value().strip()
    if not path or not os.path.isfile(path):
        raise SplatError("No splat to put in 3D: train and load first, or pick a .ply in 'splat'.")
    name = node.fullName()
    cam = _input_name(name, 1)
    try:
        x, y = int(float(nuke.tcl("value %s.xpos" % name))), int(float(nuke.tcl("value %s.ypos" % name)))
    except Exception:
        x, y = 0, 0
    text = """%(cam)sset N_cam [stack 0]
 GeoImport {
  inputs 0
  file %(file)s
  label "splat from %(node)s\\nedit here (Field nodes, GeoDeletePoints)"
  name DBS_Splat3D
  xpos %(x)d
  ypos %(y0)d
 }
set N_scene [stack 0]
push $N_scene
push $N_cam
push 0
 SplatRender {
  inputs 3
  name DBS_SplatRender
  xpos %(x)d
  ypos %(y1)d
 }
 OCIOColorSpace {
  in_colorspace %(srgb)s
  out_colorspace scene_linear
  label "splat colours are sRGB"
  name DBS_SplatFromSRGB
  xpos %(x)d
  ypos %(y2)d
 }
""" % dict(cam="push [node %s]\n" % cam if cam else "push 0\n", file=_nk_quote(path), node=node.name(),
           srgb=SRGB_ROLE, x=x + 250, y0=y - 120, y1=y - 20, y2=y + 30)
    tmp = os.path.join(_temp_dir(), "DBS_SplatTrain_3d.nk")
    with open(tmp, "w") as f:
        f.write(text)
    # A button runs inside the Group: paste next to the node, in its parent (root or a group).
    parent = name.rpartition(".")[0] or "root"
    nuke.tcl("in %s {source {%s}}" % (parent, _fwd(tmp)))
    _set_status(node, "3D setup created next to the node")


# ---- all, stop ----------------------------------------------------------------------------

@_guard
def run_all(node):
    _start_export(node, then=lambda n: _start_train(n, then=_load))


def stop(node):
    p = _jobs.get(node.fullName())
    if p is None or p.poll() is not None:
        _set_status(node, "nothing running")
        return
    p.kill()
    _set_status(node, "<font color=orange>stopped</font>", "stopped")


# ---- menu ---------------------------------------------------------------------------------

ICON = "DBS_SplatTrain.png"   # next to DBS_SplatTrain.py (in the plugin path), + @2x


def install_menu():
    """DBS_SplatTrain under the DBS button in the Nodes toolbar (with David's other tools), and in
    Nodes > 3D."""
    cmd = "import DBS_SplatTrain; DBS_SplatTrain.create_node()"
    tb = nuke.menu("Nodes").findItem("DBS") or nuke.menu("Nodes").addMenu("DBS", icon=ICON)
    tb.addCommand("DBS_SplatTrain", cmd, icon=ICON)
    nuke.menu("Nodes").addMenu("3D").addCommand("DBS_SplatTrain", cmd, icon=ICON)
