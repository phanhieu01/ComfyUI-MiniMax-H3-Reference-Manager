# ComfyUI MiniMax H3 Reference Manager

MiniMax H3 reference-management nodes for ComfyUI.

Use **MiniMax H3 Reference Bundle** outside a subgraph to collect references,
then connect its `reference_bundle` output to **MiniMax H3 Reference Manager**
inside the H3 conditioning workflow.

## Features

- Up to 9 image references.
- Up to 3 video references.
- Up to 3 audio tracks paired with reference videos. Each pairing selects
  **Video reference 1/2/3**, so the video is loaded only once.
- Up to 3 standalone audio references.
- **Generate audio without references** mode hides both audio-reference groups,
  removes them from the H3 payload, cleans dangling `<Audio N>` copy wording
  from the prompt, and asks H3 to synthesize a new synchronized soundtrack.
- The reference node shows exactly the selected number of upload fields.
- Each field has a file selector and an Upload button; no Load Image/Video/Audio node or manual wire is required.
- Changing a count immediately adds or hides the corresponding fields.
- A read-only summary shows the selected filenames and the source video used
  for each paired soundtrack. Audio ordinals are displayed in the same order
  used by H3: paired soundtracks follow video presentation order, then
  standalone audio continues the numbering.
- The summary also provides local previews: image thumbnails, video controls,
  and audio controls (including audio extracted from a selected video).
- Uploaded files are decoded by the bundle node into the native H3 reference tensors.
- In a two-phase H3 workflow, **MiniMax H3 Reference Video Preprocessor** applies
  the shared FPS, frame cap, and exact connected Phase-1 width/height to every enabled video slot.
  All processed videos remain equal members of the bundle; there is no separate
  `source_video` or `VHS_LoadVideo` path. The workflow chooses canvas aspect
  ratio explicitly; the optional layout-image output is not part of the sizing
  dependency, avoiding a circular graph.
- Paired audio selectors reject duplicates, disabled video slots, and videos
  without a decodable audio track so prompt ordinals cannot silently drift.
- Prompt tags are checked against the active bundle before conditioning.
- When a bundle is connected, its external count controls are authoritative;
  the internal H3 wrapper does not apply a second count limit.
- Uses ComfyUI's official `MiniMaxH3ReferenceToVideo` implementation.

## Installation

Copy this folder into:

```text
ComfyUI/custom_nodes/ComfyUI-MiniMax-H3-Reference-Manager
```

Restart ComfyUI and search for **MiniMax H3 Reference Manager (9/3/3/3)**.

The node requires a ComfyUI build that provides `comfy_api.latest` and the
native MiniMax H3 nodes. No extra Python packages are required.
