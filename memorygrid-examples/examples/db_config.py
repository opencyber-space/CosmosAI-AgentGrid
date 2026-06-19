"""
Shared DB configuration for all examples.

Defaults point to the NodePort addresses defined in k8s/:
  Postgres  x.x.x.x:30432
  ArangoDB  x.x.x.x:30529
  Weaviate  x.x.x.x:30880

Override any value with environment variables.
"""
import os,sys
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
    
lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
from agentic_memory.config import ArangoConfig, MemoryConfig, WeaviateConfig, PostgresConfig, RedisConfig


def make_config(embedding_dim: int = 1536) -> MemoryConfig:
    return MemoryConfig(
        postgres=PostgresConfig(
            host=os.environ.get("POSTGRES_HOST"),
            port=int(os.environ.get("POSTGRES_PORT")),
            database=os.environ.get("POSTGRES_DB"),
            username=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD"),
        ),
        arango=ArangoConfig(
            url=os.environ.get("ARANGO_URL"),
            username=os.environ.get("ARANGO_USER"),
            password=os.environ.get("ARANGO_PASSWORD"),
            database=os.environ.get("ARANGO_DB"),
        ),
        weaviate=WeaviateConfig(
            host=os.environ.get("WEAVIATE_HOST"),
            port=int(os.environ.get("WEAVIATE_PORT")),
            grpc_port=int(os.environ.get("WEAVIATE_GRPC_PORT")),
            embedding_dim=embedding_dim,
        ),
        redis=RedisConfig(
            host=os.environ.get("REDIS_HOST"),
            port=int(os.environ.get("REDIS_PORT")),
            password=os.environ.get("REDIS_PASSWORD"),
            db=int(os.environ.get("REDIS_DB")),
        ),
        embedding_model=os.environ.get("EMBEDDING_MODEL"),
    )


def make_openai_config() -> MemoryConfig:
    """Alias kept for backward compatibility."""
    return make_config()
