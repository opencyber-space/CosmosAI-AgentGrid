from typing import Optional

import redis

from ..config import RedisConfig


class RedisClient:
    def __init__(self, config: RedisConfig):
        self._client = redis.Redis(
            host=config.host,
            port=config.port,
            password=config.password or None,
            db=config.db,
            decode_responses=True,
        )

    def get(self, key: str) -> Optional[str]:
        return self._client.get(key)

    def set(self, key: str, value: str) -> None:
        self._client.set(key, value)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def close(self) -> None:
        self._client.close()

