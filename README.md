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
- Each selected image, video, and audio reference has a local preview directly
  below its own input slot. Paired audio previews use the selected video's
  soundtrack.
- File selectors refresh automatically after an upload. Use **Refresh files**
  when a file was copied into `ComfyUI/input` outside the node; restarting the
  server is not required.
- When **Generate audio without references** is enabled, both audio-reference
  groups are hidden and their old values are ignored during execution.
- Uploaded files are decoded by the bundle node into the native H3 reference tensors.
- In a two-phase H3 workflow, the existing **VHS Load Video** nodes receive the
  Phase-1-derived width and height, then center-crop and resize each reference
  video before it reaches H3. The short edge is kept between 480 and 704 pixels
  on the 32-pixel H3 grid.
- Phase 2 uses the official **MiniMax H3 Reference to Video** node with its video
  inputs left unconnected. Paired soundtracks are routed through its standalone
  audio-reference inputs, so Phase 2 does not condition on the motion reference.
- The workflow does not add custom conditioning or resolution nodes; it reuses
  the official H3 node and existing ComfyUI/VHS nodes.
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

The tested two-phase workflow is included at
`workflows/minimax_h3_two_phase_socket_refs.json`.

The node requires a ComfyUI build that provides `comfy_api.latest` and the
native MiniMax H3 nodes. No extra Python packages are required.
