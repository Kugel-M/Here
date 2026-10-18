# Technical links and repository status

## Team application

Team repository: [https://github.com/Kugel-M/Here](https://github.com/Kugel-M/Here). Source code is in `indoor_mapper_mvp/`; the complete sample map is distributed as a release attachment. The application runs on a Windows host with a mobile browser client. There is no public running-app URL. A LAN address is not a public evaluator link. The demo is in [`demo/HERE_Demo_EN.mp4`](../demo/HERE_Demo_EN.mp4), and the original two-slide PPTX retains its earlier demo for offline review; the playback page carries the latest revision.

## Third-party tools

These are upstream repositories used by the prototype, not repositories owned by the team. The prototype does not train a large AI model. hloc and Gaussian splatting are not part of this implementation.

| Tool | Role | Official source |
|---|---|---|
| COLMAP | Sparse SfM reconstruction and image registration | [COLMAP](https://github.com/colmap/colmap) |
| COLMAP image registration guide | Register a query against an existing reconstruction | [COLMAP image registration guide](https://colmap.github.io/faq.html#register-localize-new-images-into-an-existing-reconstruction) |
| Open3D | Desktop 3D point-cloud and camera visualization | [Open3D](https://github.com/isl-org/Open3D) |
| FFmpeg | Video frame extraction | [FFmpeg](https://github.com/FFmpeg/FFmpeg) |
| imageio-ffmpeg | FFmpeg executable distribution used by Python | [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) |
| NumPy | Coordinate transforms and graph geometry | [NumPy](https://github.com/numpy/numpy) |
| Pillow | Image handling and static arrow rendering | [Pillow](https://github.com/python-pillow/Pillow) |
| Kokoro ONNX | Offline synthetic English voice used only in the demo video | [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) |

## Team demonstration and source

- [Source repository](https://github.com/Kugel-M/Here)
- [Demo video](https://kugel-m.github.io/Here/technical-demo.html)
- [Evidence slides](https://github.com/Kugel-M/Here/blob/main/pitch-deck/HERE_Prototype_Proofs_EN.pptx)
- [Full sample map and evidence downloads](https://github.com/Kugel-M/Here/releases/latest)

These files document a Windows-hosted prototype; they are not a publicly hosted localization service.
