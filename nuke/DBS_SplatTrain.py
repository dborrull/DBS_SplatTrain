# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""DBS_SplatTrain entry point for Nuke: train a Gaussian splat (Brush) from a tracked shot.

Install: add this folder to the plugin path, then in ~/.nuke/menu.py:

    nuke.pluginAddPath("<repo>/nuke")
    import DBS_SplatTrain
    DBS_SplatTrain.install_menu()
"""

from dbs_splattrain import __version__
from dbs_splattrain.nuke_ui import (create_3d, create_node, export, install_menu, knob_changed, load, make_proxy,
                                    run_all, stop, train, update_info)

__all__ = ["__version__", "create_3d", "create_node", "export", "install_menu", "knob_changed", "load", "make_proxy",
           "run_all", "stop", "train", "update_info"]
