from dataclasses import dataclass, field


@dataclass
class WeaviateConfig:
    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    collection_prefix: str = "AgentMemory"
    embedding_dim: int = 1536


@dataclass
class ArangoConfig:
    url: str = "http://localhost:8529"
    username: str = "root"
    password: str = ""
    database: str = "agent_memory"


@dataclass
class PostgresConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "agent_memory"
    username: str = "postgres"
    password: str = ""


@dataclass
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0


@dataclass
class MemoryConfig:
    weaviate: WeaviateConfig = field(default_factory=WeaviateConfig)
    arango: ArangoConfig = field(default_factory=ArangoConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    embedding_model: str = "text-embedding-3-small"
    top_k: int = 5
