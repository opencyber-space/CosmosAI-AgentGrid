"""
Write an object directly to Redis/TiDB using framedb_writer_client's ad-hoc writer,
bypassing object_api's gRPC service entirely.

Install first:
    pip install -e ../writer-client
"""
import os,sys,time
from dotenv import load_dotenv
# Find .env by walking up to the directory containing .git
def find_git_root(path):
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent

_git_root = find_git_root(__file__)
if _git_root:
    load_dotenv(os.path.join(_git_root, '.env'))
else:
    load_dotenv()

lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
from framedb_writer_client import new_framedb_writer

ROUTING_SERVICE_URL = os.getenv("MEMORYGRID_ROUTING_SERVICE_URL")
GLOBAL_CONFIG_URL = os.getenv("MEMORYGRID_GLOBAL_CONFIG")  # despite the param name, this is global-config


def main():
    writer = new_framedb_writer(
        routing_service_url=ROUTING_SERVICE_URL,
        config_service_url=GLOBAL_CONFIG_URL,
    )
    key = f"sample-key--{int(time.time())}"

    result = writer.write(
        key=key,
        framedb_id="demo-instance-2",
        data=b"Hello again, FrameDB!",
        type_="in-memory",  # "in-memory" | "storage" | "stream"
        metadata={"source": "writer-client-direct"},
    )

    print(result)


if __name__ == "__main__":
    main()
