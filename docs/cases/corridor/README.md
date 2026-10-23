# Recorded corridor navigation case

[Open the interactive walkthrough](https://kugel-m.github.io/Here/recorded-case.html)

This static walkthrough presents one saved application session recorded on 18 October 2026. The six selectable presentation stages are input photo, computed pose, saved route, photo guidance, second photo registration and arrival match. They are not six measured walking positions.

## Evidence

- Navigation session: `aded2c003b2e46ffbe8860a293f8d42c`.
- First observation: `20261018_131314_bb06fe`; 1,529 2D–3D correspondences; median reprojection error 0.7051084381156537 px.
- Second observation: `20261018_131330_215bfc`; 942 2D–3D correspondences; median reprojection error 0.7758863212255551 px.
- Saved revision 1: `navigating`, route T001 to T002, action `straight` and photo action `straight`.
- Saved revision 2: `arrived`, near waypoint T002.
- `input.jpg` and `update.jpg` are the exact original submitted query JPEGs. `straight.jpg` and `arrival.jpg` are the exact application-generated overlay JPEGs. The three PNG app captures are original 1440 × 2880 captures from the same recorded workflow.
- `case.json` contains selected numeric outputs and SHA-256 checksums. Local host paths, access credentials and unrelated records are excluded. English place names and explanations are editorial translations.

## Interpretation

Both observations replay registered mapping photos through the real localization engine. The page does not run COLMAP or accept a new upload, and browsing stages does not advance a live position. The final status represents the recorded near-destination match, not an independently observed physical arrival.

The diagram is an orthographic projection of the original navigation graph onto its model horizontal plane, with the first-to-second observation direction upwards. It is not a geographic map or the application's older floor-plan calibration. Orange markers and heading vectors come from the corresponding original poses. Route polylines come from the saved first route. No intermediate observations are synthesized.

The source graph remains `field_verified=false`, `meters_per_unit=null`, and the routes are `preview_only=true`. Model units are not metres. Reprojection errors are image-space checks rather than measured physical positioning errors. Static arrows are photo guidance, not live camera AR. These boundaries are retained in the page and exported data.
