
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
from framedb_sdk import FrameDBClient

GLOBAL_CONFIG_URL = os.getenv("MEMORYGRID_GLOBAL_CONFIG")
ROUTING_SERVICE_URL = os.getenv("MEMORYGRID_ROUTING_SERVICE_URL")


def main():
    db = FrameDBClient(
        cluster_url=GLOBAL_CONFIG_URL,
        routing_url=ROUTING_SERVICE_URL,
    )

    key = f"sql-sample-key-{int(time.time())}"

    write_result = db.set_object({
        "key": key,
        "framedb_id": "sql-003",
        "data": b"Hello from SQL storage!",
        "type": "storage",
        "metadata": {"source": "framedb_sdk"},
    })
    print("write:", write_result)

    read_result = db.get_object(key)
    print(read_result)
    if read_result["found"]:
        obj = read_result["object"]
        print("data:", obj["data"])
        print("framedb_id:", obj["framedb_id"])
        print("type:", obj["type"])
        print("metadata:", obj["metadata"])
    else:
        print("not found:", read_result["message"])


if __name__ == "__main__":
    main()
