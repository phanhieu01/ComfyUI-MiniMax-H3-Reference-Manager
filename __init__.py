"""MiniMax H3 reference manager with bounded reference-count controls.

The node exposes upload widgets directly in the node.  The four dropdowns
control how many of those widgets are visible/used: 9 images, 3 videos, 3
paired video-audios, and 3 standalone audios.
"""

import math
import os
import re

from aiohttp import web

import folder_paths
import nodes
import torch
import comfy.utils
from comfy_api.latest import InputImpl
from comfy_extras.nodes_audio import load as load_audio
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo
from server import PromptServer

WEB_DIRECTORY = "./js"


def _files(content_types):
    input_dir = folder_paths.get_input_directory()
    files = [name for name in os.listdir(input_dir)
             if os.path.isfile(os.path.join(input_dir, name))]
    return [""] + sorted(folder_paths.filter_files_content_types(files, content_types))


VIDEO_AUDIO_SOURCES = ["", "Video reference 1", "Video reference 2", "Video reference 3"]

REFERENCE_VIDEO_MIN_SHORT_EDGE = 480
REFERENCE_VIDEO_MAX_SHORT_EDGE = 720
REFERENCE_VIDEO_MULTIPLE = 32

REFERENCE_TAG_RE = re.compile(r"<(Picture|Video|Audio)\s+(\d+)>", re.IGNORECASE)


@PromptServer.instance.routes.get("/minimax_h3_reference_manager/files")
async def _reference_manager_files(request):
    return web.json_response({
        "image": _files(["image"]),
        "video": _files(["video"]),
        "audio": _files(["audio", "video"]),
    })


def _file_value(value):
    return value if isinstance(value, str) and value else None


def _audio_generation_enabled(value):
    return value is True or value == "true" or value == 1 or value == "1"


def _reference_video_canvas(phase1_width, phase1_height):
    """Return an H3-grid canvas derived from the selected Phase-1 canvas."""
    phase1_width = max(REFERENCE_VIDEO_MULTIPLE, int(phase1_width or 0))
    phase1_height = max(REFERENCE_VIDEO_MULTIPLE, int(phase1_height or 0))
    phase1_short_edge = min(phase1_width, phase1_height)
    short_edge = min(
        REFERENCE_VIDEO_MAX_SHORT_EDGE,
        max(REFERENCE_VIDEO_MIN_SHORT_EDGE, phase1_short_edge),
    )
    short_edge = max(
        REFERENCE_VIDEO_MULTIPLE,
        (short_edge // REFERENCE_VIDEO_MULTIPLE) * REFERENCE_VIDEO_MULTIPLE,
    )
    scale = short_edge / phase1_short_edge
    width = max(
        REFERENCE_VIDEO_MULTIPLE,
        math.floor(phase1_width * scale / REFERENCE_VIDEO_MULTIPLE) * REFERENCE_VIDEO_MULTIPLE,
    )
    height = max(
        REFERENCE_VIDEO_MULTIPLE,
        math.floor(phase1_height * scale / REFERENCE_VIDEO_MULTIPLE) * REFERENCE_VIDEO_MULTIPLE,
    )
    return width, height


def _validate_reference_file(value, label, content_types):
    value = _file_value(value)
    if value is None:
        return True
    if not folder_paths.exists_annotated_filepath(value):
        return f"{label} file is not available in the ComfyUI input folders: {value}"
    try:
        path = folder_paths.get_annotated_filepath(value)
    except ValueError:
        return f"{label} has an invalid file path: {value}"
    if not os.path.isfile(path):
        return f"{label} is not a file: {value}"
    if not folder_paths.filter_files_content_types([os.path.basename(path)], content_types):
        return f"{label} has an unsupported file type: {value}"
    return True


def _validate_reference_inputs(values):
    try:
        image_count = int(values.get("image_reference_count", 0))
        video_count = int(values.get("video_reference_count", 0))
        video_audio_count = int(values.get("video_audio_reference_count", 0))
        audio_count = int(values.get("audio_reference_count", 0))
    except (TypeError, ValueError):
        return "Reference counts must be whole numbers."

    limits = (
        ("image_reference_count", image_count, 9),
        ("video_reference_count", video_count, 3),
        ("video_audio_reference_count", video_audio_count, 3),
        ("audio_reference_count", audio_count, 3),
    )
    for name, count, maximum in limits:
        if count < 0 or count > maximum:
            return f"{name} must be between 0 and {maximum}."

    for index in range(image_count):
        result = _validate_reference_file(
            values.get(f"ref_image_{index}"),
            f"Image reference {index + 1}",
            ["image"],
        )
        if result is not True:
            return result

    for index in range(video_count):
        result = _validate_reference_file(
            values.get(f"ref_video_{index}"),
            f"Video reference {index + 1}",
            ["video"],
        )
        if result is not True:
            return result

    if _audio_generation_enabled(values.get("generate_audio_without_reference")):
        return True

    for index in range(audio_count):
        result = _validate_reference_file(
            values.get(f"ref_audio_{index}"),
            f"Audio reference {index + 1}",
            ["audio", "video"],
        )
        if result is not True:
            return result

    effective_video_audio_count = min(video_audio_count, video_count)
    selected_sources = set()
    for index in range(effective_video_audio_count):
        source = values.get(f"ref_video_audio_{index}")
        video_index = _video_source_index(source)
        if video_index is None or video_index >= video_count:
            return (
                f"Video-paired audio {index + 1} must select an enabled "
                f"video reference (1-{video_count})."
            )
        if video_index in selected_sources:
            return f"Video reference {video_index + 1} is selected more than once as paired audio."
        selected_sources.add(video_index)
    return True


def _load_image_file(value):
    value = _file_value(value)
    if value is None:
        return None
    return nodes.LoadImage().load_image(value)[0]


def _load_video_components(value):
    value = _file_value(value)
    if value is None:
        return None
    path = folder_paths.get_annotated_filepath(value)
    return InputImpl.VideoFromFile(path).get_components()


def _load_video_frames(value):
    components = _load_video_components(value)
    return None if components is None else components.images


def _load_audio_file(value):
    value = _file_value(value)
    if value is None:
        return None
    path = folder_paths.get_annotated_filepath(value)
    waveform, sample_rate = load_audio(path)
    return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}


def _file_refs(values, prefix, loader, count):
    limit = max(0, int(count))
    return {
        f"{prefix}{index}": loaded
        for index, value in enumerate(values[:limit])
        if (loaded := loader(value)) is not None
    }


def _require_contiguous_slots(values, count, label):
    """Ensure count N really means slots 1..N, preserving H3 ordinals."""
    count = max(0, int(count))
    missing = [index + 1 for index, value in enumerate(values[:count])
               if _file_value(value) is None]
    if missing:
        raise ValueError(
            f"{label}: count={count} requires slots 1..{count}; "
            f"missing slot(s): {', '.join(map(str, missing))}. "
            "Fill the earlier slot or lower the count so H3 prompt ordinals stay aligned."
        )


def _limit_refs(refs, prefix, count):
    """Keep only the first N connected reference slots for the wrapper node."""
    if not refs:
        return {}
    limit = int(count)
    return {
        key: value for key, value in refs.items()
        if key.startswith(prefix) and int(key.rsplit("_", 1)[-1]) < limit
    }


def _upload_inputs(prefix, display_prefix, options, upload, max_count, tooltip):
    return [
        io.Combo.Input(
            f"{prefix}{index}",
            options=options,
            display_name=f"{display_prefix} {index + 1}",
            optional=True,
            default="",
            upload=upload,
            socketless=True,
            tooltip=tooltip,
        )
        for index in range(max_count)
    ]


def _video_audio_inputs(max_count=3):
    """Select the source video whose existing soundtrack should be reused."""
    return [
        io.Combo.Input(
            f"ref_video_audio_{index}",
            options=VIDEO_AUDIO_SOURCES,
            display_name=f"Audio from video {index + 1}",
            optional=True,
            default="",
            socketless=True,
            tooltip=(
                "Reuse the audio track from one of the Video reference slots; "
                "no second upload is needed."
            ),
        )
        for index in range(max_count)
    ]


def _video_source_index(value):
    """Convert 'Video reference N' to its zero-based reference-video index."""
    if not isinstance(value, str):
        return None
    prefix = "Video reference "
    if not value.startswith(prefix):
        return None
    try:
        index = int(value[len(prefix):]) - 1
    except ValueError:
        return None
    return index if 0 <= index < 3 else None


def _prepare_prompt(prompt, image_count, video_count, audio_count,
                    generate_audio_without_reference=False):
    """Keep prompt ordinals aligned with the exact H3 presentation payload."""
    prompt = str(prompt or "")
    if generate_audio_without_reference:
        # A no-reference-audio render must not leave dangling <Audio N> tags or
        # copy instructions in the prompt. Preserve the surrounding prose so a
        # single-line prompt is never accidentally discarded.
        prompt = re.sub(r"<Audio\s+\d+>", "the generated soundtrack", prompt,
                        flags=re.IGNORECASE)
        prompt = re.sub(r"\bfully[_ ]copy\b", "generate_new", prompt,
                        flags=re.IGNORECASE)
        prompt = re.sub(r"\breused?\s+unchanged\b", "generated to match the output",
                        prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\baudio\s+reuse\b", "original audio generation", prompt,
                        flags=re.IGNORECASE)
        instruction = (
            "audio_generation_instruction:\n"
            "Generate original synchronized diegetic audio appropriate to the visual action. "
            "Do not copy or reference external audio."
        )
        if "audio_generation_instruction:" not in prompt.lower():
            prompt = prompt.rstrip() + "\n\n" + instruction

    limits = {
        "picture": int(image_count),
        "video": int(video_count),
        "audio": int(audio_count),
    }
    invalid = []
    for kind, ordinal_text in REFERENCE_TAG_RE.findall(prompt):
        ordinal = int(ordinal_text)
        available = limits[kind.lower()]
        if ordinal < 1 or ordinal > available:
            invalid.append(f"<{kind.title()} {ordinal}> (available: {available})")
    if invalid:
        raise ValueError(
            "Prompt reference tag(s) do not match the active MiniMax H3 bundle: "
            + ", ".join(dict.fromkeys(invalid))
            + ". H3 numbers Picture, Video, and Audio independently in presentation order."
        )
    return prompt


class MiniMaxH3ReferenceBundle(io.ComfyNode):
    """Collect uploaded references without loading any H3 models."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MiniMaxH3ReferenceBundle",
            display_name="MiniMax H3 Reference Bundle (9/3/3/3)",
            category="model/conditioning/minimax",
            description=(
                "Collect up to 9 images, 3 videos, 3 paired video-audios, and "
                "3 standalone audios. The bundle is consumed by the H3 workflow."
            ),
            inputs=[
                io.Combo.Input("image_reference_count", options=[str(i) for i in range(10)], default="2",
                               tooltip="Number of image reference slots to use (0-9)."),
                io.Combo.Input("video_reference_count", options=[str(i) for i in range(4)], default="1",
                               tooltip="Number of video reference slots to use (0-3)."),
                io.Combo.Input("video_audio_reference_count", options=[str(i) for i in range(4)], default="1",
                               tooltip="Number of audio tracks paired with reference videos (0-3)."),
                io.Combo.Input("audio_reference_count", options=[str(i) for i in range(4)], default="0",
                               tooltip="Number of standalone audio references to use (0-3)."),
                io.Boolean.Input(
                    "generate_audio_without_reference",
                    default=False,
                    display_name="Generate audio without references",
                    tooltip=(
                        "Ignore all paired and standalone audio references and let H3 generate "
                        "a new soundtrack. Audio reference controls are hidden in the UI."
                    ),
                ),
                *_upload_inputs("ref_image_", "Image reference", _files(["image"]), io.UploadType.image, 9,
                                "Choose or upload an image reference directly in this node."),
                *_upload_inputs("ref_video_", "Video reference", _files(["video"]), io.UploadType.video, 3,
                                "Choose or upload a video reference directly in this node."),
                *_video_audio_inputs(3),
                *_upload_inputs("ref_audio_", "Audio reference", _files(["audio", "video"]), io.UploadType.audio, 3,
                                "Choose or upload a standalone audio reference directly in this node."),
            ],
            outputs=[
                io.AnyType.Output("bundle", display_name="reference_bundle"),
            ],
        )

    @classmethod
    def execute(cls, image_reference_count="2", video_reference_count="1",
                video_audio_reference_count="1", audio_reference_count="0",
                generate_audio_without_reference=False,
                ref_image_0="", ref_image_1="", ref_image_2="", ref_image_3="", ref_image_4="",
                ref_image_5="", ref_image_6="", ref_image_7="", ref_image_8="",
                ref_video_0="", ref_video_1="", ref_video_2="",
                ref_video_audio_0="", ref_video_audio_1="", ref_video_audio_2="",
                ref_audio_0="", ref_audio_1="", ref_audio_2=""):
        ref_images = _file_refs(
            [ref_image_0, ref_image_1, ref_image_2, ref_image_3, ref_image_4,
             ref_image_5, ref_image_6, ref_image_7, ref_image_8],
            "ref_image_", _load_image_file, image_reference_count)
        video_values = [ref_video_0, ref_video_1, ref_video_2]
        active_video_count = max(0, int(video_reference_count))
        _require_contiguous_slots(
            [ref_image_0, ref_image_1, ref_image_2, ref_image_3, ref_image_4,
             ref_image_5, ref_image_6, ref_image_7, ref_image_8],
            image_reference_count,
            "Image references",
        )
        _require_contiguous_slots(video_values, active_video_count, "Video references")
        if _audio_generation_enabled(generate_audio_without_reference):
            video_audio_reference_count = "0"
            audio_reference_count = "0"
        else:
            _require_contiguous_slots(
                [ref_audio_0, ref_audio_1, ref_audio_2], audio_reference_count,
                "Standalone audio references",
            )
        ref_videos = {}
        video_fps = {}
        video_components = {}
        for video_index, video_value in enumerate(video_values[:active_video_count]):
            video_file = _file_value(video_value)
            if video_file is None:
                continue
            components = _load_video_components(video_file)
            if components is None or components.images is None or len(components.images) == 0:
                raise ValueError(f"Video reference {video_index + 1} could not be decoded: {video_file}")
            slot_name = f"ref_video_{video_index}"
            ref_videos[slot_name] = components.images
            video_fps[slot_name] = float(components.frame_rate or 0.0)
            video_components[video_index] = components
        ref_video_audios = {}
        audio_values = [ref_video_audio_0, ref_video_audio_1, ref_video_audio_2]
        active_video_audio_count = max(0, int(video_audio_reference_count))
        _require_contiguous_slots(audio_values, active_video_audio_count, "Video-paired audio references")
        selected_video_audio_sources = set()
        for audio_slot, source in enumerate(audio_values[:active_video_audio_count]):
            video_index = _video_source_index(source)
            if video_index is None:
                raise ValueError(
                    f"Video-paired audio {audio_slot + 1} must select Video reference 1, 2, or 3."
                )
            if video_index >= active_video_count:
                raise ValueError(
                    f"Video-paired audio {audio_slot + 1} points to Video reference {video_index + 1}, "
                    f"but only {active_video_count} video reference(s) are enabled."
                )
            if video_index in selected_video_audio_sources:
                raise ValueError(
                    f"Video reference {video_index + 1} was selected more than once as paired audio. "
                    "Each video can contribute only one H3 <Audio N> reference."
                )
            selected_video_audio_sources.add(video_index)
            components = video_components.get(video_index)
            soundtrack = None if components is None else components.audio
            if soundtrack is None:
                raise ValueError(
                    f"Video reference {video_index + 1} has no decodable audio track, but it was "
                    "enabled as a paired audio reference. Disable that audio slot or choose a video with audio."
                )
            # H3 pairs the soundtrack by the source video's slot index. Audio
            # ordinals are assigned later by video presentation order.
            ref_video_audios[f"ref_video_audio_{video_index}"] = soundtrack
        ref_audios = _file_refs(
            [ref_audio_0, ref_audio_1, ref_audio_2],
            "ref_audio_", _load_audio_file, audio_reference_count)
        presentation_order = []
        for image_ordinal, slot_name in enumerate(ref_images, 1):
            presentation_order.append({"tag": f"<Picture {image_ordinal}>", "slot": slot_name})
        audio_ordinal = 0
        audio_reference_order = []
        for video_ordinal, slot_name in enumerate(ref_videos, 1):
            suffix = slot_name.rsplit("_", 1)[-1]
            audio_key = f"ref_video_audio_{suffix}"
            if audio_key in ref_video_audios:
                audio_ordinal += 1
                item = {
                    "tag": f"<Audio {audio_ordinal}>",
                    "slot": audio_key,
                    "paired_with": f"<Video {video_ordinal}>",
                }
                presentation_order.append(item)
                audio_reference_order.append(item)
            presentation_order.append({"tag": f"<Video {video_ordinal}>", "slot": slot_name})
        for slot_name in ref_audios:
            audio_ordinal += 1
            item = {"tag": f"<Audio {audio_ordinal}>", "slot": slot_name}
            presentation_order.append(item)
            audio_reference_order.append(item)

        bundle = {
            "__type__": "minimax_h3_reference_bundle",
            "ref_images": ref_images,
            "ref_videos": ref_videos,
            "video_fps": video_fps,
            "ref_video_audios": ref_video_audios,
            "ref_audios": ref_audios,
            "generate_audio_without_reference": _audio_generation_enabled(
                generate_audio_without_reference),
            "presentation_order": presentation_order,
            "audio_reference_order": audio_reference_order,
            "reference_order": {
                "images": list(ref_images),
                "videos": list(ref_videos),
                "video_audios": list(ref_video_audios),
                "audios": list(ref_audios),
            },
        }
        bundle["has_references"] = any(bundle[key] for key in (
            "ref_images", "ref_videos", "ref_video_audios", "ref_audios"))
        return io.NodeOutput(bundle)

    @classmethod
    def validate_inputs(cls, **kwargs):
        return _validate_reference_inputs(kwargs)


class MiniMaxH3ReferenceInputManager(io.ComfyNode):
    """Metadata-only control panel for the socket-based H3 reference router.

    This node deliberately does not decode images, videos, or audio and does not
    build a reference bundle.  It only exposes the selected input filenames and
    counts so that ordinary VHS/Core loader nodes inside a subgraph can load and
    route each slot directly into MiniMaxH3ReferenceToVideo.
    """

    @classmethod
    def define_schema(cls):
        outputs = [
            io.Int.Output("image_count", display_name="image_count"),
            io.Int.Output("video_count", display_name="video_count"),
            io.Int.Output("video_audio_count", display_name="video_audio_count"),
            io.Int.Output("audio_count", display_name="audio_count"),
        ]
        outputs.extend(
            io.String.Output(f"image_{index}_path", display_name=f"image_{index}")
            for index in range(1, 10)
        )
        outputs.extend(
            io.String.Output(f"video_{index}_path", display_name=f"video_{index}")
            for index in range(1, 4)
        )
        outputs.extend(
            io.Int.Output(
                f"video_audio_{index}_source",
                display_name=f"video_audio_{index}_source",
            )
            for index in range(1, 4)
        )
        outputs.extend(
            io.String.Output(f"audio_{index}_path", display_name=f"audio_{index}")
            for index in range(1, 4)
        )
        outputs.append(
            io.Boolean.Output(
                "generate_audio_without_reference",
                display_name="generate_audio_without_reference",
            )
        )
        return io.Schema(
            node_id="MiniMaxH3ReferenceInputManager",
            display_name="MiniMax H3 Reference Input Manager",
            category="model/conditioning/minimax",
            description=(
                "Metadata-only reference control panel. Select files and counts; "
                "the actual VHS/Core loader and slot switches live inside the subgraph."
            ),
            inputs=[
                io.Combo.Input("image_reference_count", options=[str(i) for i in range(10)], default="2"),
                io.Combo.Input("video_reference_count", options=[str(i) for i in range(4)], default="1"),
                io.Combo.Input("video_audio_reference_count", options=[str(i) for i in range(4)], default="1"),
                io.Combo.Input("audio_reference_count", options=[str(i) for i in range(4)], default="0"),
                io.Boolean.Input(
                    "generate_audio_without_reference",
                    default=False,
                    display_name="Generate audio without references",
                ),
                *_upload_inputs("ref_image_", "Image reference", _files(["image"]), io.UploadType.image, 9,
                                "Filename is forwarded to the matching loader inside the subgraph."),
                *_upload_inputs("ref_video_", "Video reference", _files(["video"]), io.UploadType.video, 3,
                                "Filename is forwarded to the matching VHS loader inside the subgraph."),
                *_video_audio_inputs(3),
                *_upload_inputs("ref_audio_", "Audio reference", _files(["audio", "video"]), io.UploadType.audio, 3,
                                "Filename is forwarded to the matching VHS audio loader inside the subgraph."),
            ],
            outputs=outputs,
        )

    @classmethod
    def execute(
        cls,
        image_reference_count="2",
        video_reference_count="1",
        video_audio_reference_count="1",
        audio_reference_count="0",
        generate_audio_without_reference=False,
        ref_image_0="", ref_image_1="", ref_image_2="", ref_image_3="", ref_image_4="",
        ref_image_5="", ref_image_6="", ref_image_7="", ref_image_8="",
        ref_video_0="", ref_video_1="", ref_video_2="",
        ref_video_audio_0="", ref_video_audio_1="", ref_video_audio_2="",
        ref_audio_0="", ref_audio_1="", ref_audio_2="",
    ):
        def selected_path(value):
            value = _file_value(value)
            return folder_paths.get_annotated_filepath(value) if value else ""

        image_count = max(0, min(int(image_reference_count), 9))
        video_count = max(0, min(int(video_reference_count), 3))
        audio_without_reference = _audio_generation_enabled(generate_audio_without_reference)
        if audio_without_reference:
            video_audio_count = 0
            audio_count = 0
        else:
            video_audio_count = max(0, min(int(video_audio_reference_count), 3, video_count))
            audio_count = max(0, min(int(audio_reference_count), 3))
        image_values = (
            ref_image_0, ref_image_1, ref_image_2, ref_image_3, ref_image_4,
            ref_image_5, ref_image_6, ref_image_7, ref_image_8,
        )
        image_paths = [
            selected_path(value) if index < image_count else ""
            for index, value in enumerate(image_values)
        ]
        video_values = (ref_video_0, ref_video_1, ref_video_2)
        video_paths = [
            selected_path(value) if index < video_count else ""
            for index, value in enumerate(video_values)
        ]
        # Paired audio is selected from an already-loaded reference video; no
        # second upload is needed.  Return one-based source indices (0 means
        # disabled) so the subgraph can route the native VHS audio outputs.
        if audio_without_reference:
            video_audio_sources = [0, 0, 0]
            audio_paths = ["", "", ""]
        else:
            video_audio_sources = []
            for index, value in enumerate((ref_video_audio_0, ref_video_audio_1, ref_video_audio_2)):
                if index >= video_audio_count:
                    video_audio_sources.append(0)
                    continue
                source_index = _video_source_index(value)
                source_number = source_index + 1 if source_index is not None else 0
                video_audio_sources.append(source_number if source_number <= video_count else 0)
            audio_paths = [
                selected_path(value) if index < audio_count else ""
                for index, value in enumerate((ref_audio_0, ref_audio_1, ref_audio_2))
            ]
        return io.NodeOutput(
            image_count,
            video_count,
            video_audio_count,
            audio_count,
            *image_paths,
            *video_paths,
            *video_audio_sources,
            *audio_paths,
            audio_without_reference,
        )

    @classmethod
    def validate_inputs(cls, **kwargs):
        return _validate_reference_inputs(kwargs)


def _preprocess_reference_frames(frames, source_fps, target_fps, frame_load_cap,
                                 target_megapixels, target_width=0, target_height=0):
    """Apply shared frame sampling and the exact connected Phase-1 size."""
    if frames is None:
        return None
    if not torch.is_tensor(frames):
        frames = torch.as_tensor(frames)
    if frames.ndim != 4 or frames.shape[0] == 0:
        return frames
    frames = frames.float()
    total_frames = int(frames.shape[0])
    source_fps = float(source_fps or 0.0)
    target_fps = float(target_fps or 0.0)
    frame_load_cap = max(0, int(frame_load_cap or 0))

    if target_fps > 0 and source_fps > 0:
        duration = total_frames / source_fps
        target_count = max(1, int(math.ceil(duration * target_fps - 1e-6)))
        if frame_load_cap > 0:
            target_count = min(target_count, frame_load_cap)
        sample_positions = torch.arange(target_count, dtype=torch.float32)
        sample_indices = torch.floor(sample_positions * source_fps / target_fps)
        sample_indices = sample_indices.clamp(max=total_frames - 1).long()
        frames = frames.index_select(0, sample_indices)
    elif frame_load_cap > 0:
        frames = frames[:frame_load_cap]

    target_width = int(target_width or 0)
    target_height = int(target_height or 0)
    if target_width > 0 and target_height > 0 and frames.shape[0] > 0:
        new_width = max(32, int(round(target_width / 32.0)) * 32)
        new_height = max(32, int(round(target_height / 32.0)) * 32)
    else:
        target_megapixels = float(target_megapixels or 0.0)
        new_width = new_height = 0
    if (new_width > 0 and new_height > 0) or (
            float(target_megapixels or 0.0) > 0 and frames.shape[0] > 0):
        height, width = int(frames.shape[1]), int(frames.shape[2])
        if new_width <= 0 or new_height <= 0:
            scale = math.sqrt(float(target_megapixels) * 1048576.0 / max(1, width * height))
            new_width = max(32, int(round(width * scale / 32.0)) * 32)
            new_height = max(32, int(round(height * scale / 32.0)) * 32)
        if new_width != width or new_height != height:
            nchw = frames.permute(0, 3, 1, 2)
            nchw = comfy.utils.common_upscale(
                nchw, new_width, new_height, "bilinear", "center")
            frames = nchw.permute(0, 2, 3, 1).contiguous()
    return frames


class MiniMaxH3ReferenceVideoPreprocessor(io.ComfyNode):
    """Preprocess every bundle video with the shared H3 load settings."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MiniMaxH3ReferenceVideoPreprocessor",
            display_name="MiniMax H3 Reference Video Preprocessor",
            category="model/conditioning/minimax",
            description=(
                "Apply one shared FPS, frame cap, and the connected Phase-1 "
                "width/height to every video in the Reference Manager bundle, "
                "bounded to the 480-720 short-edge reference-video range."
            ),
            inputs=[
                io.AnyType.Input("reference_bundle", optional=True),
                io.Float.Input("fps", default=24.0, min=0.0, max=120.0, step=1.0, optional=True),
                io.Int.Input("frame_load_cap", default=124, min=0, max=4096, step=1, optional=True),
                io.Float.Input("final_megapixels", default=1.0, min=0.01, max=4.0, step=0.01, optional=True),
                io.Float.Input("phase1_scale", default=0.5, min=0.01, max=1.0, step=0.01, optional=True),
                io.Int.Input("target_width", default=0, min=0, max=16384, step=16, optional=True,
                             tooltip="Exact Phase 1 width. When connected, this overrides MP estimation."),
                io.Int.Input("target_height", default=0, min=0, max=16384, step=16, optional=True,
                             tooltip="Exact Phase 1 height. When connected, this overrides MP estimation."),
            ],
            outputs=[
                io.AnyType.Output("bundle", display_name="reference_bundle"),
                io.Image.Output("layout_image", display_name="reference layout image"),
            ],
        )

    @classmethod
    def execute(cls, reference_bundle=None, fps=24.0, frame_load_cap=124,
                final_megapixels=1.0, phase1_scale=0.5, target_width=0, target_height=0):
        if not (isinstance(reference_bundle, dict)
                and reference_bundle.get("__type__") == "minimax_h3_reference_bundle"):
            fallback = torch.zeros((1, 1024, 576, 3), dtype=torch.float32)
            return io.NodeOutput(reference_bundle or {}, fallback)

        target_width = max(0, int(target_width or 0))
        target_height = max(0, int(target_height or 0))
        if target_width > 0 and target_height > 0:
            target_width, target_height = _reference_video_canvas(target_width, target_height)
        target_megapixels = max(
            0.5, min(float(final_megapixels or 0.0) * float(phase1_scale or 0.0), 1.0)
        )
        processed_bundle = dict(reference_bundle)
        processed_videos = {}
        raw_videos = reference_bundle.get("ref_videos") or {}
        video_fps = reference_bundle.get("video_fps") or {}
        for slot_name, frames in raw_videos.items():
            processed_videos[slot_name] = _preprocess_reference_frames(
                frames,
                video_fps.get(slot_name, 0.0),
                fps,
                frame_load_cap,
                target_megapixels,
                target_width,
                target_height,
            )
        processed_bundle["ref_videos"] = processed_videos
        processed_bundle["video_preprocess"] = {
            "force_rate": float(fps or 0.0),
            "frame_load_cap": int(frame_load_cap or 0),
            "target_megapixels": target_megapixels,
            "target_width": target_width,
            "target_height": target_height,
        }
        # The first active reference only supplies an aspect-ratio image for
        # the workflow's resolution calculator. It is not treated as a
        # privileged motion or audio source; every active video remains in
        # the bundle and is conditioned by H3 equally.
        layout_image = next(
            (frames[:1] for frames in processed_videos.values()
             if frames is not None and len(frames) > 0),
            None,
        )
        if layout_image is None:
            layout_image = next(
                (image[:1] for image in (reference_bundle.get("ref_images") or {}).values()
                 if image is not None and len(image) > 0),
                None,
            )
        if layout_image is None:
            layout_image = torch.zeros((1, 1024, 576, 3), dtype=torch.float32)
        return io.NodeOutput(processed_bundle, layout_image)


class MiniMaxH3ReferenceManager(MiniMaxH3ReferenceToVideo):
    """Official H3 reference conditioning plus count dropdowns."""

    @classmethod
    def define_schema(cls):
        schema = super().define_schema()
        schema.node_id = "MiniMaxH3ReferenceManager"
        schema.display_name = "MiniMax H3 Reference Manager (9/3/3/3)"
        schema.description = (
            "MiniMax H3 references: choose the active count for up to 9 images, "
            "3 videos, 3 video+audio pairs, and 3 standalone audios. "
            "Connect only the slots you enable."
        )
        schema.inputs.extend([
            io.Combo.Input("image_reference_count", options=[str(i) for i in range(10)], default="2",
                           tooltip="Number of image reference slots to use (0-9)."),
            io.Combo.Input("video_reference_count", options=[str(i) for i in range(4)], default="1",
                           tooltip="Number of video reference slots to use (0-3)."),
            io.Combo.Input("video_audio_reference_count", options=[str(i) for i in range(4)], default="1",
                           tooltip="Number of audio tracks paired with reference videos (0-3)."),
            io.Combo.Input("audio_reference_count", options=[str(i) for i in range(4)], default="0",
                           tooltip="Number of standalone audio references to use (0-3)."),
            io.Boolean.Input("generate_audio_without_reference", default=False,
                             display_name="Generate audio without references"),
            io.AnyType.Input("reference_bundle", optional=True,
                             tooltip="Reference bundle from MiniMax H3 Reference Bundle."),
        ])
        return schema

    @classmethod
    def execute(cls, clip, prompt, width, height, length, ref_image_size="match", vae=None,
                audio_vae=None, ref_images=None, ref_videos=None, ref_video_audios=None,
                ref_audios=None, image_reference_count="2", video_reference_count="1",
                video_audio_reference_count="1", audio_reference_count="0",
                generate_audio_without_reference=False,
                reference_bundle=None):
        bundle_is_active = (isinstance(reference_bundle, dict)
                and reference_bundle.get("__type__") == "minimax_h3_reference_bundle")
        if bundle_is_active:
            ref_images = reference_bundle.get("ref_images") or {}
            ref_videos = reference_bundle.get("ref_videos") or {}
            ref_video_audios = reference_bundle.get("ref_video_audios") or {}
            ref_audios = reference_bundle.get("ref_audios") or {}
            # The external bundle has already applied all four user-selected
            # counts. Do not truncate it again with this wrapper's standalone
            # compatibility widgets (whose defaults would otherwise reduce a
            # three-video bundle back to one video).
            selected_images = ref_images
            selected_videos = ref_videos
            selected_video_audios = ref_video_audios
            selected_audios = ref_audios
            generate_audio_without_reference = bool(
                reference_bundle.get("generate_audio_without_reference", False)
            )
        else:
            selected_images = _limit_refs(ref_images, "ref_image_", image_reference_count)
            selected_videos = _limit_refs(ref_videos, "ref_video_", video_reference_count)
            selected_video_audios = _limit_refs(
                ref_video_audios, "ref_video_audio_", video_audio_reference_count)
            selected_audios = _limit_refs(ref_audios, "ref_audio_", audio_reference_count)
            if generate_audio_without_reference:
                selected_video_audios = {}
                selected_audios = {}

        prompt = _prepare_prompt(
            prompt,
            len(selected_images or {}),
            len(selected_videos or {}),
            len(selected_video_audios or {}) + len(selected_audios or {}),
            generate_audio_without_reference,
        )
        return super().execute(
            clip=clip,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            ref_image_size=ref_image_size,
            vae=vae,
            audio_vae=audio_vae,
            ref_images=selected_images,
            ref_videos=selected_videos,
            ref_video_audios=selected_video_audios,
            ref_audios=selected_audios,
        )


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ReferenceBundle": MiniMaxH3ReferenceBundle,
    "MiniMaxH3ReferenceInputManager": MiniMaxH3ReferenceInputManager,
    "MiniMaxH3ReferenceVideoPreprocessor": MiniMaxH3ReferenceVideoPreprocessor,
    "MiniMaxH3ReferenceManager": MiniMaxH3ReferenceManager,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ReferenceBundle": "MiniMax H3 Reference Bundle (9/3/3/3)",
    "MiniMaxH3ReferenceInputManager": "MiniMax H3 Reference Input Manager",
    "MiniMaxH3ReferenceVideoPreprocessor": "MiniMax H3 Reference Video Preprocessor",
    "MiniMaxH3ReferenceManager": "MiniMax H3 Reference Manager (9/3/3/3)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
