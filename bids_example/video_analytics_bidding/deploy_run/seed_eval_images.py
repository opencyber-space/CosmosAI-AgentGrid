"""Seed the evaluator's sample image set and its ground truth into MinIO.

The RFP demands a live vendor bake-off -- "all vendors will be provided with a live
stream with similar Field of View to ensure common ground ... outcomes will be measured
and compared among all vendors to check the accuracy". This script is the "common
ground" half of that: one image set, one ground truth, identical for every bidder.

The ground truth travels on the bid job (`bid_job_metadata.evaluation`) rather than
living inside the evaluator. That keeps the evaluator generic, lets a second round use a
different set without re-uploading a function, and -- most usefully -- puts the answer
key in the job record where a reviewer can check the scoring by hand.

An image already in MinIO is left alone, so editing `make_image` below changes nothing
until the set is re-uploaded over the top:

    SEED_FORCE=1 ./venv/bin/python deploy_run/seed_eval_images.py

One manual step in MinIO, once per cluster: set **va-bidding-rfp**, **va-bidding-eval**
and **va-bidding-docs** to anonymous *download* (read-only) access. Everything this
example produces travels as a URL rather than as inlined bytes -- the RFP on the task,
the sample images on the bid job, the commercial and sizing workbooks on each bid --
and those URLs are opened by things holding no MinIO credentials: a reviewer clicking
through the dashboard, and anyone reading the bid record afterwards. Without the
policy the objects upload fine and every link 403s.

    MinIO Console -> Buckets -> <bucket> -> Anonymous -> Add Access Rule
    Prefix: /     Access: readonly

Prints one JSON line on stdout for `va_bidding_request.sh` to fold into the task:
    {"bucket": ..., "sample_images": [{"name", "url", "ground_truth"}, ...]}
Progress goes to stderr.
"""
import json
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "nodes")))

from common.minio_store import EVAL_BUCKET, MinioStore, external_address  # noqa: E402

# The answer key. Each company's config.yaml declares what it *would* answer for these
# names; where the two differ, that company scores a wrong answer. Ten images over two
# endpoints per company gives twenty graded calls each.
GROUND_TRUTH = {
    "face_01.png": True,
    "face_02.png": False,
    "face_03.png": True,
    "face_04.png": True,
    "face_05.png": False,
    "face_06.png": True,
    "face_07.png": False,
    "face_08.png": True,
    "face_09.png": True,
    "face_10.png": False,
}

PREFIX = "eval"
SIZE = (320, 240)


def log(msg):
    print(f"[seed_eval_images] {msg}", file=sys.stderr, flush=True)


def make_image(name, has_subject):
    """A small deterministic placeholder scene.

    The endpoints never decode these -- their verdicts are configured -- so the pixels
    carry no information the round depends on. They exist so the URLs resolve to real
    images, and so the set is visually legible to someone opening it: a frame with a
    figure is a positive, an empty frame is a negative.
    """
    img = Image.new("RGB", SIZE, (34, 38, 46))
    draw = ImageDraw.Draw(img)

    # A crude camera frame, so the set reads as CCTV stills rather than colour swatches.
    draw.rectangle([6, 6, SIZE[0] - 7, SIZE[1] - 7], outline=(90, 98, 110), width=2)
    draw.line([0, 185, SIZE[0], 200], fill=(70, 76, 88), width=3)   # ground plane

    if has_subject:
        draw.ellipse([140, 70, 180, 112], fill=(206, 178, 152))      # head
        draw.polygon([(133, 118), (187, 118), (196, 186), (124, 186)], fill=(58, 92, 138))
        draw.ellipse([149, 84, 156, 91], fill=(40, 40, 46))          # eyes
        draw.ellipse([165, 84, 172, 91], fill=(40, 40, 46))

    draw.text((12, SIZE[1] - 22), f"{name}  subject={'yes' if has_subject else 'no'}",
              fill=(150, 158, 170))
    return img


def main():
    store = MinioStore(connect_address=external_address())
    store.ensure_bucket(EVAL_BUCKET)

    force = os.environ.get("SEED_FORCE") == "1"
    sample_images = []

    for name, truth in GROUND_TRUTH.items():
        object_name = f"{PREFIX}/{name}"
        if store.exists(EVAL_BUCKET, object_name) and not force:
            log(f"{object_name} already present")
            ref = store.ref(EVAL_BUCKET, object_name)
        else:
            import io
            buf = io.BytesIO()
            make_image(name, truth).save(buf, format="PNG")
            ref = store.put_bytes(buf.getvalue(), EVAL_BUCKET, object_name, "image/png")
            log(f"uploaded {object_name}")
        sample_images.append({"name": name, "url": ref["url"], "ground_truth": truth})

    positives = sum(1 for i in sample_images if i["ground_truth"])
    log(f"{len(sample_images)} images ready ({positives} positive, "
        f"{len(sample_images) - positives} negative)")

    print(json.dumps({"bucket": EVAL_BUCKET, "sample_images": sample_images}))


if __name__ == "__main__":
    main()
