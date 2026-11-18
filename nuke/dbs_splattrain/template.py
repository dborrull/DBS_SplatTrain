# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""The DBS_SplatTrain node as .nk text, pasted by DBS_SplatTrain.create_node().

Inside: the plate passes through until a splat is loaded; then the splat (GeoImport) is
rendered through the 'cam' input (SplatRender: scene on input 2, camera on input 1) and
brought from sRGB to scene_linear (Brush learns from sRGB PNGs)."""

from . import __version__

TILE = 0x3f7f9fff

TIPS = {
    "first": "First frame to train from. Set to the script's range when the node is created. "
             "0 = the plate's first frame.",
    "last": "Last frame to train from. Set to the script's range when the node is created. "
            "0 = the plate's last frame.",
    "step": "Use one frame every N. 3 works well: about 80 frames from 240.",
    "trainer": "Program that trains the splat. Only Brush for now.",
    "steps": "Training steps. 30000 for quality (about 20 min for 80 frames on an RTX 4060 Ti), "
             "7000 for a quick test.",
    "max_res": "Images bigger than this are scaled down for training.",
    "work_dir": "Folder for the dataset and the trained splats. Empty = next to the script, in "
                "DBS_SplatTrain/<node name>.",
    "brush": "brush_app.exe (Brush v0.3.0 is in the repo's bin folder).",
    "splat_file": "The trained splat (.ply). Load fills it in; you can also pick any .ply.",
    "proxy_size": "How many splats the proxy keeps (the most visible ones). The full splat is never "
                  "overwritten: the proxy goes next to it as splat_<steps>_500k.ply.",
    "proxy_custom": "Number of splats for 'custom'.",
    "do_proxy": "Write a lighter copy of 'splat' for a faster viewer (takes a few seconds).",
    "proxy_file": "The light splat. 'make proxy' fills it in; you can also pick any .ply.",
    "use_proxy": "Show the proxy in the viewer. Renders (Write) always use the full splat.",
    "show_splat": "Output the rendered splat. Off: the plate passes through.",
    "do_3d": "Put the splat next to this node as a 3D setup (GeoImport -> SplatRender through the "
             "camera -> back to scene_linear), to edit it: e.g. FieldShape into the mask of a "
             "GeoDeletePoints between GeoImport and SplatRender.",
}


def _tip(k):
    return ' t "%s"' % TIPS[k].replace('"', '\\"')


def _py(call):
    return '"import DBS_SplatTrain; DBS_SplatTrain.%s(nuke.thisNode())"' % call


# The splat the node renders: the proxy in the GUI viewer when 'use_proxy' is on, else the full one
# (Tcl in a file knob; $gui is 0 in renders). node: the DBS_SplatTrain node ("parent" inside it).
def splat_expr(node):
    return ("[if {[value N.use_proxy] && $gui && [string length [value N.proxy_file]]} "
            "{return [value N.proxy_file]} {return [value N.splat_file]}]").replace("N.", node + ".")


def node_template(brush, srgb, first=0, last=0):
    t = {k + "_t": _tip(k) for k in TIPS}
    t.update(first=int(first), last=int(last), tile=TILE, version=__version__, brush=brush, srgb=srgb,
             py_export=_py("export"), py_train=_py("train"), py_load=_py("load"),
             py_all=_py("run_all"), py_stop=_py("stop"), py_3d=_py("create_3d"),
             py_proxy=_py("make_proxy"), splat_expr=splat_expr("parent"),
             py_changed='"import DBS_SplatTrain; DBS_SplatTrain.knob_changed(nuke.thisNode(), nuke.thisKnob())"')
    return """set cut_paste_input [stack 0]
push $cut_paste_input
Group {
 name DBS_SplatTrain1
 tile_color %(tile)d
 label "\\[value dbs_state]"
 knobChanged %(py_changed)s
 addUserKnob {20 dbs l DBS_SplatTrain}
 addUserKnob {26 info l "" +STARTLINE T "<i>plate -> 'plate', tracked camera -> 'cam',<br>tracker point cloud -> 'points', roto of what moves (optional) -> 'mask'</i>"}
 addUserKnob {26 div_frames l frames}
 addUserKnob {3 first l first%(first_t)s}
 first %(first)d
 addUserKnob {3 last l last -STARTLINE%(last_t)s}
 last %(last)d
 addUserKnob {3 step l "every N frames" -STARTLINE%(step_t)s}
 step 3
 addUserKnob {26 div_train l training}
 addUserKnob {4 trainer l trainer M {Brush}%(trainer_t)s}
 addUserKnob {3 steps l steps -STARTLINE%(steps_t)s}
 steps 30000
 addUserKnob {3 max_res l "max resolution" -STARTLINE%(max_res_t)s}
 max_res 1920
 addUserKnob {2 work_dir l "work folder"%(work_dir_t)s}
 addUserKnob {2 brush l brush%(brush_t)s}
 brush "%(brush)s"
 addUserKnob {26 div_run l run}
 addUserKnob {22 run_all l "<b>  Export + Train + Load  </b>" +STARTLINE T %(py_all)s}
 addUserKnob {22 stop l stop -STARTLINE T %(py_stop)s}
 addUserKnob {22 do_export l "1. export" +STARTLINE T %(py_export)s}
 addUserKnob {22 do_train l "2. train" -STARTLINE T %(py_train)s}
 addUserKnob {22 do_load l "3. load" -STARTLINE T %(py_load)s}
 addUserKnob {26 status l "" +STARTLINE T " "}
 addUserKnob {26 div_out l output}
 addUserKnob {2 splat_file l splat%(splat_file_t)s}
 addUserKnob {26 splat_info l "" +STARTLINE T " "}
 addUserKnob {6 show_splat l "show splat" +STARTLINE%(show_splat_t)s}
 addUserKnob {22 do_3d l "create 3D setup" -STARTLINE T %(py_3d)s%(do_3d_t)s}
 show_splat true
 addUserKnob {26 div_proxy l proxy}
 addUserKnob {4 proxy_size l "proxy size" M {500k 100k custom}%(proxy_size_t)s}
 addUserKnob {3 proxy_custom l "" -STARTLINE +HIDDEN%(proxy_custom_t)s}
 proxy_custom 250000
 addUserKnob {22 do_proxy l "make proxy" -STARTLINE T %(py_proxy)s%(do_proxy_t)s}
 addUserKnob {2 proxy_file l proxy%(proxy_file_t)s}
 addUserKnob {26 proxy_info l "" +STARTLINE T " "}
 addUserKnob {6 use_proxy l "use proxy in the viewer" +STARTLINE%(use_proxy_t)s}
 addUserKnob {26 ver l "" +STARTLINE T "<small>DBS_SplatTrain v%(version)s  -  by David Borrull</small>"}
 addUserKnob {1 dbs_state +INVISIBLE}
 dbs_state "not trained"
 addUserKnob {6 dbs_loaded +INVISIBLE}
}
 Input {
  inputs 0
  name plate
  xpos 0
  ypos -300
 }
set N_plate [stack 0]
 Input {
  inputs 0
  name cam
  number 1
  xpos 300
  ypos -300
 }
set N_cam [stack 0]
 Input {
  inputs 0
  name points
  number 2
  xpos 450
  ypos -300
 }
 Input {
  inputs 0
  name mask
  number 3
  xpos 600
  ypos -300
 }
 GeoImport {
  inputs 0
  file {%(splat_expr)s}
  name DBS_Splat
  disable {{!parent.dbs_loaded}}
  xpos 150
  ypos -260
 }
set N_scene [stack 0]
push $N_scene
push $N_cam
push 0
 SplatRender {
  inputs 3
  name DBS_Render
  xpos 150
  ypos -180
 }
 OCIOColorSpace {
  in_colorspace "%(srgb)s"
  out_colorspace scene_linear
  name DBS_FromSRGB
  xpos 150
  ypos -140
 }
push $N_plate
 Switch {
  inputs 2
  which {{"parent.dbs_loaded && parent.show_splat"}}
  name DBS_Out
  xpos 0
  ypos -140
 }
 Output {
  name Output1
  xpos 0
  ypos -100
 }
end_group
""" % t
