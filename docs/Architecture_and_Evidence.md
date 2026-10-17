# Architecture and prototype evidence

## Data flow

Phone video → FFmpeg frame selection → COLMAP feature extraction/matching → sparse reconstruction → fixed map.

New phone photo → existing COLMAP image registration → validated camera XYZ and orientation → independent navigation graph → POI name/alias resolution → A* route → turn instructions → real-photo arrow overlay.

A subsequent photo runs localization again, then updates, replans or pauses the route. Browsing a reference image does not advance the computed location.

## Pose conventions

COLMAP's rotation `R` and translation `t` transform world points into camera coordinates. Camera position is `C = -R.T @ t`; camera-to-world rotation is `R.T`; forward direction is `R.T @ [0, 0, 1]`. The original map signature guards against mixing coordinate frames. Single-camera SfM has arbitrary scale until a measured reference is supplied.

## Recorded demonstration

The included map contains 141 registered reference cameras and 35,040 sparse points. Its independent candidate navigation graph has 13 nodes and 12 connections. In the recorded corridor-photo run, registration passed the quality checks with 68 valid 2D–3D correspondences, median reprojection error 1.681 pixels and 90th-percentile error 4.232 pixels. These are image-space geometric checks, not measured physical positioning accuracy.

The recorded query position was (-1.7446436335, 0.1306592002, 0.1073897476) in model units. The application generated seven route steps to entrance/shoe-cabinet Waypoint 1. The arrival stage replayed the map's registered frame_000001.jpg through actual localization and produced a near-destination result.

## Current boundaries

The recorded demo is an edited application walkthrough using real photos and computed poses. It is not a continuous walking video. Ground-truth position error, metric scale, passability and a complete phone walking trial remain to be measured/verified. The reconstructed geometry is a sparse point cloud. Static photo arrows are not live camera AR. The Windows-hosted application is not currently publicly deployed.
