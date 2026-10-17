# Source checkout and sample data

This Git checkout excludes the large sample map and demo photographs. Download the full evidence package from [Releases](https://github.com/Kugel-M/Here/releases/latest), then copy its `03_Application/indoor_mapper_mvp/projects/` and `demo_inputs/` folders into this directory. The remaining reproduction instructions assume those folders have been copied. Alternatively, build a new map using your own video.

# HERE: indoor reconstruction, visual localization and navigation

This Windows prototype builds a sparse 3D map from phone video, localizes a new photo with COLMAP, and uses the resulting camera pose to plan a route and display arrows on real scene photographs. A mobile browser provides the camera/upload and navigation interface. Processing runs on the Windows host.

## Requirements and installation

Use Windows 10/11, Python 3.12 (64-bit), and COLMAP. The development machine used COLMAP 4.2.1 CUDA. NVIDIA GPU processing is optional; the desktop UI also supports CPU processing. Install COLMAP from https://github.com/colmap/colmap/releases .

Open PowerShell in this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Edit `config.json` and set `colmap_exe` to the full path of your installed `colmap.exe`. Alternatively, set the `COLMAP_EXE` environment variable. Leave `ffmpeg_exe` blank to use imageio-ffmpeg's bundled executable. Then check:

```powershell
.\.venv\Scripts\python.exe app.py doctor
```

## Reproduce the demonstrated flow

1. Double-click `Start-Demo-Mobile.cmd`. It selects the bundled map explicitly and prints a fresh access URL. Keep the service window open.
2. Open the printed URL on the Windows host. On a phone, use the host's LAN URL on the same trusted Wi-Fi network. The localhost address does not work from a phone. A new host may need its normal private-network firewall permission.
3. Select **从相册选择 / Choose from album** and upload `demo_inputs/corridor_query.jpg`. This is an existing test photo, included to reproduce a photo-replay demonstration.
4. Once localization succeeds, enter **参考点1** (Waypoint 1) as the destination and choose **开始导航 / Start navigation**. The destination is the entrance/shoe-cabinet reference waypoint. The graph is an unverified candidate route, so the application labels it as a preview.
5. **下一张参考图 / Next reference image** previews a future step without changing your position.
6. Upload `projects/map_20261011_035045/images/frame_000001.jpg` for the controlled arrival check. This is a registered mapping frame, so this check is not a held-out accuracy test or a physical walking test.

To test real use, take a new photo at the mapped location and upload it. Each photo computes a new pose; there is no continuous tracking. A localization failure is reported rather than replaced with invented coordinates.

## Desktop and command line

Double-click `Start.cmd` for the desktop app. Choose `projects/map_20261011_035045` as the map. To localize from the command line:

```powershell
.\.venv\Scripts\python.exe app.py localize --project projects/map_20261011_035045 --photo demo_inputs/corridor_query.jpg
```

Add `--cpu` if your COLMAP build does not provide usable GPU support. Use your own MP4/MOV with `app.py reconstruct --video ... --project ...` to create a different map. The original 4K capture video is not bundled; the ready map is included.

## Code and data

- `mapper/engine.py`: frame selection, reconstruction, feature matching and query image registration.
- `mapper/model.py`: COLMAP model parsing, camera poses and reprojection quality checks.
- `mapper/navigation.py`: floorplan alignment and reference-image association.
- `mapper/visual_nav/`: independent graph, POI lookup, A* planner, instructions, reference-image selection, arrow rendering and navigation controller.
- `mobile_server.py` and `mobile/`: Windows-hosted mobile web interface and API.
- `projects/map_20261011_035045/`: prebuilt map, 155 input frames, 141 registered cameras, 35,040 sparse points and the separate 13-node navigation graph.
- `demo_inputs/recorded_pose.json`: recorded result for inspection. New localization creates its own query session; this example is not an active location.

The original map signature and the numerical pose data are preserved. Local machine paths in packaged metadata are replaced with portable descriptions. Runtime environments, existing access tokens, upload history and query databases are not included. Access tokens are generated on first launch.

## Technical scope

XYZ uses the original COLMAP coordinate frame and arbitrary scale. Metric calibration, verified passable routes and a measured floorplan alignment remain required for field navigation. The old floorplan position is shown as an estimate; the independent navigation graph uses the original 3D pose. Arrows are direction illustrations on static photographs, not live camera AR. The interface is Chinese; the evidence package provides English explanations and a UI translation reference.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

The local HTTP tests may require a loopback port. `tests/run_real_visual_navigation.py` is a development-machine integration script, not the portable demo entry point; use the steps above instead.

## Repository and reuse

Team repository: https://github.com/Kugel-M/Here. This folder is the team's source handover, separate from third-party repositories. Application source is distributed under the repository MIT license. Third-party software retains its own licenses; see ../docs/Technical_Links_and_Repositories.md. The sample data is distributed separately for reproducing the demonstration.
