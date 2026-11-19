# Changelog

## 0.1.0 (2026-11-19)
- `skip blurry frames` (on for new nodes; exporter `--sharpest`): in each group of N frames the
  export takes the sharpest one (mean squared Laplacian at half resolution, measured by
  `tools/DBS_frame_sharpness.py` in a second Nuke terminal). The status says how many were swapped.
- No load button: the node shows the `.ply` in `splat` as soon as it exists (after training, picked
  by hand, or a new proxy). `Export + Train` replaces `Export + Train + Load`.
- Proxy: `make proxy` (500k / 100k / custom) writes a decimated copy of the splat with the size as
  a suffix; `use proxy` swaps it in (node and its 3D setups, reloaded), the label says `proxy`.
  Splat count and file size under `splat` and `proxy`. `tools/DBS_decimate_splat.py`,
  `nuke/dbs_splattrain/splat_ply.py` (plain Python: Nuke ships no numpy).
- README banner (`tools/make_banner.py`) and screenshots; note on what masks can and cannot remove.
- Fix: `create 3D setup` put the nodes inside the DBS_SplatTrain group; now they go next to it.
- New nodes take `first` / `last` from the script's frame range (Project Settings) instead of 0.
- Training progress every 5 % (was 10 %), with the time since the start from the first poll;
  only the newest progress .ply is kept on disk.
- `create 3D setup` button: the loaded splat next to the node as GeoImport -> SplatRender ->
  OCIOColorSpace, for editing in 3D (Field nodes).
- Panel help text on two lines (it was cut off).
- Fix: Brush crashed on start when launched from the node: it writes a GPU cache to target/ in
  its working folder, and Nuke's (Program Files) is read-only. Both processes now run in the
  work folder.
- The DBS_SplatTrain node (DBS menu, own icon): plate / cam / points / mask inputs, frames,
  steps, work folder; Export + Train + Load and step-by-step buttons, stop, progress in the
  panel and the label. Export and training run as separate processes. The node renders the
  loaded splat through `cam` (SplatRender) and brings it back to scene_linear.
- Colour: plate written through the OCIO role `texture_paint` (sRGB), splat brought back from it.
- `tools/make_icon.py`: draws the node icon.

## 0.0.1
- `tools/DBS_export_shot.py`: Nuke terminal export of a tracked shot as a Brush dataset
  (images every N frames, optional inverted motion masks, COLMAP binary cameras with the tracker
  points as points3D, or transforms.json).
- `tools/DBS_train_brush.py`: headless Brush run with timing.
- `tests/synthetic_brush.py`: synthetic dataset check against Brush.
- Exporter: non-square pixel plates stretched to square pixels.
