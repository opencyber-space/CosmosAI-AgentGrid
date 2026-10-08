"""MinIO access for the video-analytics bidding example.

Agents run inside the cluster and reach MinIO on its internal address; the URLs they
hand back travel outward -- onto a bid, into a task record, to a human opening a
spreadsheet -- so those are always built from the external address. Writing the internal
address into a bid would produce a link nobody outside the cluster can open.

Configuration comes from the repo `.env` via python-dotenv. Nothing here opens `.env`
directly, and no address or credential is hardcoded.
"""
import io
import logging
import os
import subprocess

import urllib3
from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

log = logging.getLogger(__name__)

# minio-py's default client waits indefinitely on a connect. An agent that blocks here
# never returns a report, its Bid Manager never submits a bid, and evaluation -- which
# needs a bid from every participant and has no timeout of its own -- stalls the entire
# round. So every call is bounded: fail fast, let the agent decline, keep the round
# moving. Overridable via VA_MINIO_CONNECT_TIMEOUT / VA_MINIO_READ_TIMEOUT.
CONNECT_TIMEOUT = float(os.environ.get("VA_MINIO_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.environ.get("VA_MINIO_READ_TIMEOUT", "60"))

# Buckets this example owns.
#
# All three need anonymous download (read-only) access set by hand in MinIO, once per
# cluster. This example never inlines a document: the RFP, the evaluation images and the
# generated workbooks all travel as URLs, which are then opened by readers holding no
# MinIO credentials -- the dashboard, a reviewer, anyone reading a finished bid. The
# upload succeeds either way; only the reading fails, and it fails as a 403 on a link
# that looks correct.
#
#     MinIO Console -> Buckets -> <bucket> -> Anonymous -> Add Access Rule
#     Prefix: /     Access: readonly
RFP_BUCKET = "va-bidding-rfp"
DOCS_BUCKET = "va-bidding-docs"
EVAL_BUCKET = "va-bidding-eval"

_loaded = False


def _git_root():
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=here, text=True
        ).strip()
    except Exception:
        # Inside a container there is no git checkout; fall back to the tree layout.
        return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def load_env():
    """Load the repo .env once, without overriding anything already in the environment.

    In-cluster the pod's own environment wins, which is why `override` stays False --
    a deployed agent must not be silently reconfigured by a stale file baked into an
    image.
    """
    global _loaded
    if not _loaded:
        load_dotenv(os.path.join(_git_root(), ".env"), override=False)
        _loaded = True


def _addr(ip_key, port_key):
    load_env()
    ip = os.environ.get(ip_key)
    port = os.environ.get(port_key)
    if not ip or not port:
        raise RuntimeError(
            f"{ip_key} and {port_key} must be set (see .env.template) to reach MinIO"
        )
    return f"{ip}:{port}"


def internal_address():
    """Where an in-cluster agent connects.

    Derived from INTERNAL_IP/MINIO_INTERNAL_PORT. Set VA_MINIO_URL only to override that
    derivation; it is not part of .env.template, because a deployment whose MinIO is
    reachable the normal way never needs it.
    """
    return os.environ.get("VA_MINIO_URL") or _addr("INTERNAL_IP", "MINIO_INTERNAL_PORT")


def external_address():
    """What goes into a URL anyone outside the cluster will open.

    This one travels: it ends up in the rfp_url on the task and in the document links on
    every bid, which are opened by the dashboard and by readers holding no credentials.
    So it must be reachable from outside the cluster, where the internal address is not.
    Override with VA_MINIO_EXTERNAL_URL when EXTERNAL_IP/MINIO_EXTERNAL_PORT do not
    describe how the outside world reaches MinIO.
    """
    return os.environ.get("VA_MINIO_EXTERNAL_URL") or _addr("EXTERNAL_IP", "MINIO_EXTERNAL_PORT")


class MinioStore:
    """Uploads and downloads for the example's buckets.

    `connect_address` defaults to the internal address, which is correct for an agent
    pod. Scripts run from a developer's machine pass the external address instead --
    `seed_rfp.py` and `seed_eval_images.py` both do.
    """

    def __init__(self, connect_address=None, external_url=None, secure=False):
        load_env()
        self.address = connect_address or internal_address()
        self.external_url = external_url or external_address()
        access_key = os.environ.get("MINIO_ACCESS_KEY")
        secret_key = os.environ.get("MINIO_SECRET_KEY")
        if not access_key or not secret_key:
            raise RuntimeError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be set (see .env.template)")
        http_client = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT),
            retries=urllib3.Retry(total=2, backoff_factor=0.3,
                                  status_forcelist=[500, 502, 503, 504]),
        )
        self.client = Minio(self.address, access_key=access_key, secret_key=secret_key,
                            secure=secure, http_client=http_client)

    def ensure_bucket(self, bucket):
        if not self.client.bucket_exists(bucket):
            log.info("creating bucket %s", bucket)
            self.client.make_bucket(bucket)

    def ref(self, bucket, object_name):
        """The outward-facing reference for an object: {bucket, object, url}."""
        return {
            "bucket": bucket,
            "object": object_name,
            "url": f"http://{self.external_url}/{bucket}/{object_name}",
        }

    def put_file(self, path, bucket, object_name, content_type="application/octet-stream"):
        self.ensure_bucket(bucket)
        self.client.fput_object(bucket, object_name, path, content_type=content_type)
        log.info("uploaded %s -> %s/%s", path, bucket, object_name)
        return self.ref(bucket, object_name)

    def put_bytes(self, data, bucket, object_name, content_type="application/octet-stream"):
        self.ensure_bucket(bucket)
        self.client.put_object(
            bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type
        )
        log.info("uploaded %d bytes -> %s/%s", len(data), bucket, object_name)
        return self.ref(bucket, object_name)

    def get_bytes(self, bucket, object_name):
        response = self.client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, bucket, object_name):
        try:
            self.client.stat_object(bucket, object_name)
            return True
        except S3Error:
            return False


def parse_url(url):
    """Split a MinIO URL back into `(bucket, object_name)`.

    Agents receive the RFP as a URL and need to fetch it over the *internal* address,
    so the bucket and key are recovered here rather than the URL being fetched as-is.
    Returns `(None, None)` for a URL that is not shaped like a MinIO object.
    """
    if not url:
        return None, None
    without_scheme = url.split("://", 1)[-1]
    parts = without_scheme.split("/", 2)
    if len(parts) < 3:
        return None, None
    return parts[1], parts[2]
