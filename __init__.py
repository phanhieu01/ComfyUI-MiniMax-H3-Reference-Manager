"""MiniMax H3 reference manager with bounded reference-count controls.

The node keeps the official MiniMax H3 reference conditioning implementation
and adds four dropdowns that cap how many dynamically connected slots are used:
9 images, 3 videos, 3 paired video-audios, and 3 standalone audios.
"""

from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo


def _limit_refs(refs, prefix, count):
    """Keep only the first N dynamic reference slots."""
    if not refs:
        return {}
    limit = int(count)
    return {
        key: value for key, value in refs.items()
        if key.startswith(prefix) and int(key.rsplit("_", 1)[-1]) < limit
    }


class MiniMaxH3ReferenceBundle(io.ComfyNode):
    """Collect dynamic reference slots without loading any H3 models."""

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
                io.Autogrow.Input("ref_images", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input("ref_image"), prefix="ref_image_", min=0, max=9)),
                io.Autogrow.Input("ref_videos", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input("ref_video"), prefix="ref_video_", min=0, max=3)),
                io.Autogrow.Input("ref_video_audios", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input("ref_video_audio"), prefix="ref_video_audio_", min=0, max=3)),
                io.Autogrow.Input("ref_audios", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input("ref_audio"), prefix="ref_audio_", min=0, max=3)),
            ],
            outputs=[io.AnyType.Output("bundle", display_name="reference_bundle")],
        )

    @classmethod
    def execute(cls, image_reference_count="2", video_reference_count="1",
                video_audio_reference_count="1", audio_reference_count="0",
                ref_images=None, ref_videos=None, ref_video_audios=None, ref_audios=None):
        bundle = {
            "__type__": "minimax_h3_reference_bundle",
            "ref_images": _limit_refs(ref_images, "ref_image_", image_reference_count),
            "ref_videos": _limit_refs(ref_videos, "ref_video_", video_reference_count),
            "ref_video_audios": _limit_refs(ref_video_audios, "ref_video_audio_", video_audio_reference_count),
            "ref_audios": _limit_refs(ref_audios, "ref_audio_", audio_reference_count),
        }
        bundle["has_references"] = any(bundle[key] for key in (
            "ref_images", "ref_videos", "ref_video_audios", "ref_audios"))
        return io.NodeOutput(bundle)


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
        if (isinstance(reference_bundle, dict)
                and reference_bundle.get("__type__") == "minimax_h3_reference_bundle"
                and reference_bundle.get("has_references")):
            ref_images = reference_bundle.get("ref_images") or {}
            ref_videos = reference_bundle.get("ref_videos") or {}
            ref_video_audios = reference_bundle.get("ref_video_audios") or {}
            ref_audios = reference_bundle.get("ref_audios") or {}
        return super().execute(
            clip=clip,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            ref_image_size=ref_image_size,
            vae=vae,
            audio_vae=audio_vae,
            ref_images=_limit_refs(ref_images, "ref_image_", image_reference_count),
            ref_videos=_limit_refs(ref_videos, "ref_video_", video_reference_count),
            ref_video_audios=_limit_refs(ref_video_audios, "ref_video_audio_", video_audio_reference_count),
            ref_audios=_limit_refs(ref_audios, "ref_audio_", audio_reference_count),
        )


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ReferenceBundle": MiniMaxH3ReferenceBundle,
    "MiniMaxH3ReferenceManager": MiniMaxH3ReferenceManager,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ReferenceBundle": "MiniMax H3 Reference Bundle (9/3/3/3)",
    "MiniMaxH3ReferenceManager": "MiniMax H3 Reference Manager (9/3/3/3)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
