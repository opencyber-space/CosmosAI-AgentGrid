"""Image-model backends, MinIO storage and image measurements for the image-editing team.

Mirrors the GoogleImageGenerator / MinioUploader pattern of
agentic-patterns/agent_codes/agent_marketing_image_generator.py, adapted for editing an
existing image: the model and its api_key come from the agent spec (integrations.models)
and MinIO settings from persona.config.parameters.MINIO_CONFIG.
"""
import base64
import io
import logging
from typing import Optional

from minio import Minio
from minio.error import S3Error
from openai import OpenAI
from PIL import ExifTags, Image, ImageStat

log = logging.getLogger(__name__)

GPS_IFD = 0x8825


def _get(block, key, default=None):
    return getattr(block, key, None) if hasattr(block, key) else (block.get(key, default) if isinstance(block, dict) else default)


def spec_models(subject):
    integrations = getattr(subject, "integrations", None)
    if integrations is None:
        return []
    return _get(integrations, "models", []) or []


def minio_config(subject):
    config = getattr(subject.persona, "config", {}) if hasattr(subject, "persona") else {}
    return (config or {}).get("parameters", {}).get("MINIO_CONFIG", {})


class OpenAIImageEditor:
    """Edits an input image with an OpenAI image model (`images.edit`).

    Uses the first `openai:*image*` block in the spec, or `model_name` when given.
    Optional llm_parameters `quality` and `input_fidelity` are passed through; the output
    size is always chosen to match the input's aspect ratio.
    """

    PASSTHROUGH = ("quality", "input_fidelity")

    def __init__(self, subject, model_name: Optional[str] = None):
        self.client = None
        self.model_name = ""
        self.params = {}
        for block in spec_models(subject):
            block_id = _get(block, "llm_block_id") or ""
            if not block_id.startswith("openai:") or "image" not in block_id:
                continue
            if model_name and block_id != model_name:
                continue
            llm_params = _get(block, "llm_parameters") or {}
            self.model_name = block_id
            self.client = OpenAI(api_key=llm_params.get("api_key"))
            self.params = {k: llm_params[k] for k in self.PASSTHROUGH if k in llm_params}
            log.info(f"OpenAIImageEditor using {block_id} params={self.params}")
            break

    # Output canvases the image models accept; the input is letterboxed onto the closest one.
    CANVASES = ((1536, 1024), (1024, 1536), (1024, 1024))
    PADDING_NOTE = (" The picture is letterboxed with plain padding bands; keep the picture area at exactly the "
                    "same position and scale and do not extend the scene into the bands.")

    def edit_image_bytes(self, image_bytes: bytes, prompt: str, background: Optional[str] = None) -> Optional[bytes]:
        """Edit an image and return the result with the input's aspect ratio and framing.

        The model only renders fixed canvases (e.g. 1536x1024), and resizing a 16:9 image onto
        one lets the model reframe it. So the input is scaled to fit the closest canvas and
        padded, and the same picture area is cropped back out of the result - the output
        lines up with the input pixel for pixel after resizing to the input size.
        """
        if self.client is None:
            return None
        source = Image.open(io.BytesIO(image_bytes))
        source = source.convert("RGBA" if "A" in source.getbands() else "RGB")
        canvas_size = min(self.CANVASES, key=lambda c: abs(c[0] / c[1] - source.width / source.height))
        scale = min(canvas_size[0] / source.width, canvas_size[1] / source.height)
        fitted = source.resize((round(source.width * scale), round(source.height * scale)), Image.LANCZOS)
        left, top = (canvas_size[0] - fitted.width) // 2, (canvas_size[1] - fitted.height) // 2
        canvas = Image.new(source.mode, canvas_size, (0, 0, 0, 255) if source.mode == "RGBA" else (0, 0, 0))
        canvas.paste(fitted, (left, top))
        padded = (left, top) != (0, 0)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")

        kwargs = dict(
            model=self.model_name.split(":", 1)[1],
            image=("input.png", buf.getvalue(), "image/png"),
            prompt=prompt + (self.PADDING_NOTE if padded else ""),
            output_format="png",
            **self.params,
        )
        kwargs["size"] = f"{canvas_size[0]}x{canvas_size[1]}"
        if background:
            kwargs["background"] = background
        response = self.client.images.edit(**kwargs)
        b64 = response.data[0].b64_json if response.data else None
        if not b64:
            return None
        result = Image.open(io.BytesIO(base64.b64decode(b64)))
        if result.size != canvas_size:
            result = result.resize(canvas_size, Image.LANCZOS)
        result = result.crop((left, top, left + fitted.width, top + fitted.height))
        out = io.BytesIO()
        result.save(out, format="PNG")
        return out.getvalue()


class MinioStore:
    """Reads and writes images in the job bucket; URLs use the external MinIO address."""

    def __init__(self, config):
        self.client = Minio(
            config["MINIO_URL"],
            access_key=config["MINIO_ACCESS_KEY"],
            secret_key=config["MINIO_SECRET_KEY"],
            secure=False,
        )
        self.bucket = config.get("MINIO_BUCKET", "marketing-images")
        self.external_url = config.get("MINIO_EXTERNAL_URL") or config["MINIO_URL"]
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def get_bytes(self, ref) -> bytes:
        response = self.client.get_object(ref.get("bucket") or self.bucket, ref["object"])
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, object_name) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False

    def put_bytes(self, data: bytes, object_name: str, content_type: str = "image/png") -> dict:
        self.client.put_object(self.bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type)
        return self.ref(object_name)

    def ref(self, object_name) -> dict:
        return {"bucket": self.bucket, "object": object_name,
                "url": f"http://{self.external_url}/{self.bucket}/{object_name}"}


def to_png_bytes(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data))
    if img.format == "PNG":
        return data
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def exif_tag_names(img) -> list:
    """Names of the EXIF tags present, with GPS reported as GPSInfo only when it has entries."""
    exif = img.getexif()
    names = []
    for tag in exif:
        if tag == GPS_IFD:
            if exif.get_ifd(GPS_IFD):
                names.append("GPSInfo")
            continue
        names.append(ExifTags.TAGS.get(tag, hex(tag)))
    return sorted(names)


def image_facts(data: bytes) -> dict:
    """Facts about an image measured with PIL - never estimated by a model."""
    img = Image.open(io.BytesIO(data))
    dpi = img.info.get("dpi")
    luminance = img.convert("L")
    histogram = luminance.histogram()
    total = max(sum(histogram), 1)
    return {
        "format": img.format,
        "width": img.width,
        "height": img.height,
        "mode": img.mode,
        "has_alpha": "A" in img.getbands(),
        "dpi": [round(float(d)) for d in dpi] if dpi else None,
        "icc_profile": bool(img.info.get("icc_profile")),
        "exif_tags": exif_tag_names(img),
        "avg_luminance": round(ImageStat.Stat(luminance).mean[0] / 255.0, 3),
        "clipped_highlights_pct": round(100.0 * sum(histogram[250:]) / total, 2),
        "bytes": len(data),
    }
