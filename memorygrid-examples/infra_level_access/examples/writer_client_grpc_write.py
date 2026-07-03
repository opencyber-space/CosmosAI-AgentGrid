"""
Write an object through object_api's gRPC service using framedb_writer_client.

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
from framedb_writer_client import new_objects_api_client
from framedb_writer_client import framedb_pb2, framedb_pb2_grpc
import grpc

OBJECT_API_GRPC_ADDRESS = os.getenv("MEMORYGRID_OBJECT_API_URL")  # host:port, no scheme


def main():
    client = new_objects_api_client(OBJECT_API_GRPC_ADDRESS)

    key = f"sample-key--{int(time.time())}"
    

    response = client.write_to_memory(
        framedb_id="demo-instance-2",
        data=b"Hello, FrameDB!",
        key=key,
        metadata={"source": "writer-client-grpc"},
    )

    print("success:", response.success)
    print("message:", response.message)
    print("key:", response.key)


    # for accessing via gRPC
    channel = grpc.insecure_channel(OBJECT_API_GRPC_ADDRESS)
    stub = framedb_pb2_grpc.ObjectServiceStub(channel)
    resp = stub.GetObject(framedb_pb2.GetObjectRequest(key=key))
    if resp.found:
        print(resp.object.data, resp.object.framedb_id, resp.object.type)


if __name__ == "__main__":
    main()
