---
name: minimax-h3-ref2va-multiframe
description: Create timed guide images, write correctly indexed MiniMax H3 Ref2VA prompts, and run the user's local multiframe workflow in ComfyUI. Use for video edits that combine character or outfit references with timed image guides.
---

# MiniMax H3 Ref2VA with Multiframe Guides

Use this skill for the user's local two-phase MiniMax H3 Ref2VA workflow. The workflow consumes the ordinary image/video/audio references and multiframe guide images through its Reference Manager. Guides go to both Qwen Vision for their `<Picture N>` prompt labels and Add Guide for temporal anchoring.

## Workflow and operating rules

- Use the ordinary workflow bundled at `workflows/minimax_h3_ref2va_multiframe_reference.json` in the ComfyUI-MiniMax-H3-Reference-Manager repository. Load it into ComfyUI or use the matching copy in ComfyUI's user workflows directory. Confirm the loaded graph matches the bundled workflow; do not use an API workflow.
- Treat the saved graph as fixed during a run. Do not edit its JSON, rewire nodes, or use `set_workflow_slot(stdout: false)`. Use only slots exposed by `list_workflow_slots`; follow `comfyui-workflow-control` for the MCP slot, validation, job, and output-fetch sequence.
- Keep the workflow's phase, megapixels, aspect ratio, and other render settings unless the user explicitly asks to change an exposed setting. Set the exposed duration to the source clip's duration; the workflow handles its 24 fps input path, and guide time maps as `frame_idx = round(time_seconds * 24)`.
- Before running, check the local server, read workflow slots and notes, confirm required files and counts, validate, then submit through MCP and wait for the job. If the graph, guide count, prompt map, or paths do not match, stop and report the mismatch instead of repairing the graph during the run.

## Prepare the clip and guide images

1. Identify the source video, character/identity references, target outfit or product references, and requested edit. Ask only for missing material that prevents a grounded edit; do not invent a target identity or outfit.
2. Read video metadata and sample the timeline before choosing anchors. Use `video-scene-analysis` when the clip has cuts, fast changes, or the user needs a detailed timeline. Let the source video control action, camera, framing, setting, and edit timing.
3. Choose 1–5 guide times at meaningful visual states, such as an outfit reveal or a close-up where the target appearance must hold. Do not add a guide for every ordinary pose change. Use 0 only when no timed guide is needed.
4. For each selected time, inspect a representative source frame and the supplied references. Generate one guide image for that moment using the source frame for scene/composition, the character image for identity, and the target reference for the requested look. Keep unrelated board layout, labels, and props out of the generated scene unless requested. Use the `imagegen` skill and make a separate image-generation call for each distinct guide.
5. Save each final guide under `D:\ComfyUI\input` with a stable name containing the clip and timestamp, for example `<clip>_guide_1_2s.png`. Confirm the file exists and that ComfyUI can select it before setting its manager slot. Never leave a guide path pointing to an older job's image.

## Build the prompt and reference map

Use the Reference Manager and `MiniMax H3 Prompt Reference Guide` as the source of truth for reference order. Set ordinary `image_reference_count` to the number of character/outfit/product images; set `multiframe_reference_count` to the selected guide count. Active guides are consecutive from Guide 1.

- Set reference files, counts, and guide times on the Reference Manager's inputs (the `101.*` slots in this saved workflow). The connected `100.image_*_path` and `100.guide_*` subgraph inputs are mirrors; do not override them. Set the combined prompt through `100.prompt` and the source-matched duration through `100.duration_seconds`.
- Guide N is normally `<Picture image_reference_count + N>`. Confirm the exact labels in the workflow's prompt reference map; do not assume guide number equals picture number.
- Example: 0 ordinary images + 1 guide gives Guide 1 = `<Picture 1>`. Two ordinary images + three guides gives Guide 1–3 = `<Picture 3>`–`<Picture 5>`.
- Pictures count ordinary image references first, then active guides; `<Video N>` and `<Audio N>` use their own independent numbering. If the on-canvas map has not refreshed yet, derive the manifest from the active manager slots in presentation order and cross-check it before submitting.
- If the source video has audio and the user has not asked to replace it, pair the source video with its audio through the manager, then preserve it as `<Audio N>` in the prompt. If the source has no audio, leave paired audio disabled; if the user requests generated audio, enable the workflow's explicit audio-generation switch and do not claim an `<Audio N>` reference.
- Set every active guide image and its time. Clear or ignore inactive guide slots and stale references. Keep reference counts aligned with populated paths.
- Write the prompt in English as one text value using these six headings in order. Use only labels present in the map:

```text
# MiniMax H3 Ref2VA Prompt — <clip>

## subject_definitions
...

## summary
...

## retention_analysis
...

## detailed_description
...

## overall_soundscape
...

## non_diegetic_music
...
```

In `subject_definitions`, define reusable people/looks as `<Subject N>` and cite their assigned `<Picture N>` references; identify each guide picture as a timed visual anchor and `<Video 1>` as the source of scene structure and motion. In `summary` and `retention_analysis`, state what changes (identity/outfit) and what stays from the source. In `detailed_description`, describe only the planned visual state at each guide time; do not invent actions, cuts, or transitions. Keep the full target outfit consistent after its planned reveal. When source audio is reused, identify `<Audio N>` and say it remains unchanged; use `N/A` for sound fields when no audio is present or requested. Avoid frame numbers, render settings, unsupported details, and long negative-prompt lists in the prose.

## Run and report

- Populate the prompt, media paths, counts, guide paths, and guide times through the workflow's approved MCP slots. Preserve the other workflow settings by default.
- Validate before queueing. On validation error, missing required media, stale slots, or a prompt-map mismatch, stop without submitting.
- Run the validated ordinary workflow through MCP, track the job, fetch its output, and report the final video path together with the guide manifest and prompt used. If the user explicitly asks to queue from the ComfyUI UI instead, prepare and validate the workflow, then stop before submitting.
