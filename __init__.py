"""MiniMax H3 reference manager with bounded reference-count controls.

The node exposes upload widgets directly in the node.  The four dropdowns
control how many of those widgets are visible/used: 9 images, 3 videos, 3
paired video-audios, and 3 standalone audios.
"""

import math
import os

import folder_paths
import nodes
import torch
import torch.nn.functional as F
from comfy_api.latest import InputImpl
from comfy_extras.nodes_audio import load as load_audio
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo

WEB_DIRECTORY = "./js"


def _files(content_types):
    input_dir = folder_paths.get_input_directory()
    files = [name for name in os.listdir(input_dir)
             if os.path.isfile(os.path.join(input_dir, name))]
    return [""] + sorted(folder_paths.filter_files_content_types(files, content_types))


IMAGE_FILES = _files(["image"])
VIDEO_FILES = _files(["video"])
AUDIO_FILES = _files(["audio", "video"])
VIDEO_AUDIO_SOURCES = ["", "Video reference 1", "Video reference 2", "Video reference 3"]


def _file_value(value):
    return value if isinstance(value, str) and value else None


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
                *_upload_inputs("ref_image_", "Image reference", IMAGE_FILES, io.UploadType.image, 9,
                                "Choose or upload an image reference directly in this node."),
                *_upload_inputs("ref_video_", "Video reference", VIDEO_FILES, io.UploadType.video, 3,
                                "Choose or upload a video reference directly in this node."),
                *_video_audio_inputs(3),
                *_upload_inputs("ref_audio_", "Audio reference", AUDIO_FILES, io.UploadType.audio, 3,
                                "Choose or upload a standalone audio reference directly in this node."),
            ],
            outputs=[io.AnyType.Output("bundle", display_name="reference_bundle")],
        )

    @classmethod
    def execute(cls, image_reference_count="2", video_reference_count="1",
                video_audio_reference_count="1", audio_reference_count="0",
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
            components = video_components.get(video_index)
            soundtrack = None if components is None else components.audio
            if soundtrack is not None:
                # H3 pairs the soundtrack by the source video's slot index.
                ref_video_audios[f"ref_video_audio_{video_index}"] = soundtrack
        ref_audios = _file_refs(
            [ref_audio_0, ref_audio_1, ref_audio_2],
            "ref_audio_", _load_audio_file, audio_reference_count)
        bundle = {
            "__type__": "minimax_h3_reference_bundle",
            "ref_images": ref_images,
            "ref_videos": ref_videos,
            "video_fps": video_fps,
            "ref_video_audios": ref_video_audios,
            "ref_audios": ref_audios,
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
            nchw = F.interpolate(nchw, size=(new_height, new_width),
                                 mode="bilinear", align_corners=False)
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
                "width/height to every video in the Reference Manager bundle."
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
            io.AnyType.Input("reference_bundle", optional=True,
                             tooltip="Reference bundle from MiniMax H3 Reference Bundle."),
        ])
        return schema

    @classmethod
    def execute(cls, clip, prompt, width, height, length, ref_image_size="match", vae=None,
                audio_vae=None, ref_images=None, ref_videos=None, ref_video_audios=None,
                ref_audios=None, image_reference_count="2", video_reference_count="1",
                video_audio_reference_count="1", audio_reference_count="0",
                reference_bundle=None):
        bundle_is_active = (isinstance(reference_bundle, dict)
                and reference_bundle.get("__type__") == "minimax_h3_reference_bundle"
                and reference_bundle.get("has_references"))
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
        else:
            selected_images = _limit_refs(ref_images, "ref_image_", image_reference_count)
            selected_videos = _limit_refs(ref_videos, "ref_video_", video_reference_count)
            selected_video_audios = _limit_refs(
                ref_video_audios, "ref_video_audio_", video_audio_reference_count)
            selected_audios = _limit_refs(ref_audios, "ref_audio_", audio_reference_count)
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
    "MiniMaxH3ReferenceVideoPreprocessor": MiniMaxH3ReferenceVideoPreprocessor,
    "MiniMaxH3ReferenceManager": MiniMaxH3ReferenceManager,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ReferenceBundle": "MiniMax H3 Reference Bundle (9/3/3/3)",
    "MiniMaxH3ReferenceVideoPreprocessor": "MiniMax H3 Reference Video Preprocessor",
    "MiniMaxH3ReferenceManager": "MiniMax H3 Reference Manager (9/3/3/3)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
