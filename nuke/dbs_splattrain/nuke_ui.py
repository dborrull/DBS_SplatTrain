# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Nuke side of DBS_SplatTrain: the node's buttons.

Nuke Non-commercial allows 10 Python Node objects per session, so every button works from the
node it belongs to (nuke.thisNode()) and reaches everything else by name (Tcl and knob paths).
The heavy work runs in separate processes, so Nuke stays usable:
  export: a Nuke terminal (`-t`) runs tools/DBS_export_shot.py on the saved script
  train:  Brush (brush_app.exe) trains on the exported dataset
  proxy:  Nuke's python.exe runs tools/DBS_decimate_splat.py (a lighter copy for the viewer)
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

from . import splat_ply
from .colour import SRGB_ROLE
from .template import node_template

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORTER = os.path.join(ROOT, "tools", "DBS_export_shot.py")
DEFAULT_BRUSH = os.path.join(ROOT, "bin", "brush-v0.3.0", "brush_app.exe")
DECIMATOR = os.path.join(ROOT, "tools", "DBS_decimate_splat.py")
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
        if "proxy_file" in node.knobs():
            node["proxy_file"].setValue("")       # a proxy of the previous splat
        _show(node)
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


# ---- showing the splat --------------------------------------------------------------------

def _show(node):
    """The node shows the splat as soon as 'splat' holds an existing file (after training, a .ply
    picked by hand, or a proxy): no load button. Without one, the plate passes through."""
    path = node["splat_file"].value().strip()
    node["dbs_loaded"].setValue(bool(path) and os.path.isfile(path))
    if node["dbs_loaded"].value():
        _apply_splat(node)
    update_info(node)


def _load(node):
    """The '3. load' button of nodes made before 0.1.0's automatic loading."""
    path = node["splat_file"].value().strip()
    if not path:
        found = sorted(glob.glob(os.path.join(_work_dir(node), "splats", "splat_*.ply")), key=os.path.getmtime)
        if not found:
            raise SplatError("No splat yet: train first, or pick a .ply in 'splat'.")
        path = _fwd(found[-1])
        node["splat_file"].setValue(path)
    if not os.path.isfile(path):
        raise SplatError("File not found: %s" % path)
    _show(node)
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
    path = _active_splat(node)[0]
    if not path or not os.path.isfile(path):
        raise SplatError("No splat to put in 3D: train and load first, or pick a .ply in 'splat'.")
    name = node.fullName()
    parent = name.rpartition(".")[0]
    geo = "DBS_Splat3D"
    i = 0
    while nuke.exists(_root_path(parent, geo)):   # its own name, so 'use proxy' can find it
        i += 1
        geo = "DBS_Splat3D%d" % i
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
  name %(geo)s
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
""" % dict(cam="push [node %s]\n" % cam if cam else "push 0\n", node=node.name(),
           file=_nk_quote(path), geo=geo,
           srgb=SRGB_ROLE, x=x + 250, y0=y - 120, y1=y - 20, y2=y + 30)
    tmp = os.path.join(_temp_dir(), "DBS_SplatTrain_3d.nk")
    with open(tmp, "w") as f:
        f.write(text)
    # A button runs inside the Group: paste next to the node, in its parent (root or a group).
    nuke.tcl("in %s {source {%s}}" % (parent or "root", _fwd(tmp)))
    if "dbs_3d" in node.knobs():
        full = (parent + "." if parent else "") + geo
        node["dbs_3d"].setValue(" ".join(node["dbs_3d"].value().split() + [full]))
    _set_status(node, "3D setup created next to the node: %s" % geo)


def _root_path(parent, name):
    """'root.Group1.Name': names that resolve the same from inside a group (where buttons run)."""
    return "root." + (parent + "." if parent else "") + name


# ---- proxy and info -----------------------------------------------------------------------

def _python():
    """Nuke's own python.exe (next to Nuke.exe), else Nuke in terminal mode."""
    exe = os.path.join(os.path.dirname(nuke.EXE_PATH), "python.exe" if sys.platform == "win32" else "python3")
    return [exe] if os.path.isfile(exe) else [nuke.EXE_PATH, "-t"]


def _proxy_count(node):
    size = node["proxy_size"].value()
    if size == "custom":
        return max(1000, int(node["proxy_custom"].value()))
    return splat_ply.PRESETS[size]


@_guard
def make_proxy(node):
    src = node["splat_file"].value().strip()
    if not src or not os.path.isfile(src):
        raise SplatError("No splat to make a proxy of: train and load first, or pick a .ply in 'splat'.")
    keep = _proxy_count(node)
    try:
        total = splat_ply.count(src)
    except (OSError, splat_ply.PlyError) as e:
        raise SplatError(str(e))
    if keep >= total:
        raise SplatError("The splat has {:,} splats: a {:,} proxy would not be lighter.".format(total, keep))
    out = splat_ply.decimated_name(src, keep)
    cmd = _python() + [DECIMATOR, src, "--keep=%d" % keep, "--out=%s" % out]
    log = os.path.join(os.path.dirname(src), "proxy.log")
    _set_status(node, "making a {:,}-splat proxy...".format(keep), "making proxy")

    def done(code, sec):
        if code != 0 or not os.path.isfile(out):
            _set_status(node, "<font color=orange>proxy failed: see %s</font>" % _fwd(log), "proxy failed")
            _log("proxy failed:\n" + _tail(log))
            return
        node["proxy_file"].setValue(_fwd(out))
        node["use_proxy"].setValue(True)
        _show(node)
        _set_status(node, "proxy written in %s: %s" % (_minutes(sec), os.path.basename(out)), "proxy ready")

    _run_async(node, cmd, log, done)


def _info(path):
    path = path.strip()
    if not path:
        return " "
    if not os.path.isfile(path):
        return "<font color=orange>file not found</font>"
    return "<small>%s</small>" % splat_ply.describe(path)


def update_info(node):
    """Splat count and size of 'splat' and 'proxy' under them (reads only the .ply header)."""
    for file_knob, info_knob in (("splat_file", "splat_info"), ("proxy_file", "proxy_info")):
        if info_knob in node.knobs():
            node[info_knob].setValue(_info(node[file_knob].value()))


def _active_splat(node):
    """(path, is the proxy): the proxy when 'use proxy' is on and it exists, else 'splat'."""
    if "use_proxy" in node.knobs() and node["use_proxy"].value():
        proxy = node["proxy_file"].value().strip()
        if proxy and os.path.isfile(proxy):
            return proxy, True
    return node["splat_file"].value().strip(), False


def _apply_splat(node):
    """Put the active splat in the node's GeoImport and in its 3D setups. A new path is enough
    for a GeoImport to re-read it; pressing its 'reload' would fail while the viewer renders
    ("I'm already executing something else"). By name only: no Node objects."""
    path, proxy = _active_splat(node)
    parent = node.fullName().rpartition(".")[0]
    targets = [_root_path(parent, node.name() + ".DBS_Splat")]
    if "dbs_3d" in node.knobs():
        targets += ["root." + t for t in node["dbs_3d"].value().split()]
    for t in targets:
        if not nuke.exists(t):
            continue
        try:
            if nuke.tcl("value %s.file" % t) != path:
                nuke.knob(t + ".file", path)
        except Exception as e:
            _log("could not update %s: %s" % (t, e))
    if "dbs_mode" in node.knobs():
        node["dbs_mode"].setValue("proxy" if proxy else "")


def knob_changed(node, knob):
    name = knob.name()
    if name in ("splat_file", "proxy_file", "use_proxy"):
        _show(node)
    elif name == "proxy_size":
        node["proxy_custom"].setVisible(knob.value() == "custom")
    elif name == "showPanel":
        update_info(node)
        node["proxy_custom"].setVisible(node["proxy_size"].value() == "custom")


# ---- all, stop ----------------------------------------------------------------------------

@_guard
def run_all(node):
    _start_export(node, then=_start_train)      # training shows the splat when it ends


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
