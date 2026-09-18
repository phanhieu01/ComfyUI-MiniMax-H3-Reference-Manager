# ComfyUI MiniMax H3 Reference Manager

Standalone MiniMax H3 reference-conditioning node for ComfyUI.

## Features

- Up to 9 image references.
- Up to 3 video references.
- Up to 3 audio tracks paired with reference videos.
- Up to 3 standalone audio references.
- Dropdowns cap how many connected slots are used; unused connected slots are ignored.
- Uses ComfyUI's official `MiniMaxH3ReferenceToVideo` implementation.

## Installation

Copy this folder into:

```text
ComfyUI/custom_nodes/ComfyUI-MiniMax-H3-Reference-Manager
```

Restart ComfyUI and search for **MiniMax H3 Reference Manager (9/3/3/3)**.

The node requires a ComfyUI build that provides `comfy_api.latest` and the
native MiniMax H3 nodes. No extra Python packages are required.
