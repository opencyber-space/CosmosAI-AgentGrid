"""Seed the hero-banner test image for the image-editing bid job into MinIO.

Creates `seed/hero_banner.png` in the `marketing-images` bucket with the properties the
job brief describes (1280x720, 72 DPI, sRGB profile, RGBA, underexposed to ~0.31 average
luminance, Canon EXIF with GPS and Artist). The scene is generated once with an OpenAI
image model and reused on later runs; set SEED_FORCE=1 to regenerate.

Prints one JSON line on stdout - the `input_image` reference for the job payload:
    {"bucket": ..., "object": ..., "url": ..., "facts": {...}}
Progress goes to stderr. Configuration comes from the repo .env via python-dotenv.
"""
import base64
import io
import json
import os
import subprocess
import sys

from dotenv import load_dotenv
from PIL import Image, ImageCms, ImageDraw, ImageEnhance, ImageOps, ImageStat

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from utils.image_models import GPS_IFD, MinioStore, image_facts  # noqa: E402

OBJECT_NAME = "seed/hero_banner.png"
BUCKET = "marketing-images"
WIDTH, HEIGHT = 1280, 720
TARGET_LUMINANCE = 0.31
SCENE_PROMPT = (
    "Photorealistic wide office photo: two people seated at a laptop left of centre, a wooden desk "
    "with a coffee cup, notebook and phone in the midground, an office window with blinds behind "
    "them and a potted plant far right. Soft backlight from the window, faces partially shadowed."
)


def log(msg):
    print(f"[seed_image] {msg}", file=sys.stderr, flush=True)


def git_root():
    try:
        return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True).strip()
    except Exception:
        return os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def generate_scene():
    """RGB scene from the OpenAI image model, or a drawn placeholder if that fails."""
    model = os.environ.get("SEED_IMAGE_MODEL", "gpt-image-1")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        log(f"generating scene with {model}")
        response = client.images.generate(model=model, prompt=SCENE_PROMPT, size="1536x1024")
        return Image.open(io.BytesIO(base64.b64decode(response.data[0].b64_json))).convert("RGB")
    except Exception as e:
        log(f"WARNING: image generation failed ({e}); using a drawn placeholder scene")
        img = Image.new("RGB", (WIDTH, HEIGHT), (170, 160, 150))
        draw = ImageDraw.Draw(img)
        for y in range(0, 420, 24):
            draw.rectangle([760, 40 + y, 1180, 52 + y], fill=(235, 235, 225))      # window blinds
        draw.rectangle([0, 470, WIDTH, HEIGHT], fill=(120, 80, 50))                # desk
        draw.ellipse([300, 180, 420, 300], fill=(90, 70, 60))                      # heads
        draw.ellipse([470, 200, 580, 310], fill=(80, 60, 55))
        draw.rectangle([270, 300, 620, 480], fill=(60, 60, 80))                    # bodies
        draw.rectangle([380, 400, 560, 480], fill=(40, 40, 45))                    # laptop
        draw.rectangle([1190, 330, 1260, 470], fill=(40, 110, 50))                 # plant
        return img


def underexpose(img, target=TARGET_LUMINANCE):
    for _ in range(5):
        current = ImageStat.Stat(img.convert("L")).mean[0] / 255.0
        if abs(current - target) < 0.005 or current == 0:
            break
        img = ImageEnhance.Brightness(img).enhance(target / current)
    return img


def build_png(scene):
    img = underexpose(ImageOps.fit(scene, (WIDTH, HEIGHT), Image.LANCZOS)).convert("RGBA")
    exif = Image.Exif()
    exif[0x010F] = "Canon"                  # Make
    exif[0x0110] = "EOS 90D"                # Model
    exif[0x013B] = "internal-photographer"  # Artist
    gps = exif.get_ifd(GPS_IFD)
    gps[1], gps[2] = "N", (12.0, 58.0, 17.76)
    gps[3], gps[4] = "E", (77.0, 35.0, 40.56)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(72, 72), exif=exif, icc_profile=icc)
    return buf.getvalue()


def main():
    load_dotenv(os.path.join(git_root(), ".env"))
    external = os.environ.get("SEED_MINIO_URL") or f"{os.environ['EXTERNAL_IP']}:{os.environ['MINIO_EXTERNAL_PORT']}"
    store = MinioStore({
        "MINIO_URL": external,
        "MINIO_EXTERNAL_URL": external,
        "MINIO_ACCESS_KEY": os.environ["MINIO_ACCESS_KEY"],
        "MINIO_SECRET_KEY": os.environ["MINIO_SECRET_KEY"],
        "MINIO_BUCKET": BUCKET,
    })
    if store.exists(OBJECT_NAME) and os.environ.get("SEED_FORCE") != "1":
        log(f"reusing existing {BUCKET}/{OBJECT_NAME}")
        data = store.get_bytes({"object": OBJECT_NAME})
    else:
        data = build_png(generate_scene())
        store.put_bytes(data, OBJECT_NAME)
        log(f"uploaded {BUCKET}/{OBJECT_NAME} ({len(data)} bytes)")
    ref = store.ref(OBJECT_NAME)
    ref["facts"] = image_facts(data)
    print(json.dumps(ref))


if __name__ == "__main__":
    main()
