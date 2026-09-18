import json
from typing import Any, Dict, Optional

from ..backends.redis_client import RedisClient


class ContextKVMemory:
    def __init__(self, redis: RedisClient):
        self._redis = redis

    def _key(self, agent_id: str, session_id: str, key: str) -> str:
        return f"{agent_id}__{session_id}__{key}"

    def get(self, agent_id: str, session_id: str, key: str) -> Optional[Dict[str, Any]]:
        raw = self._redis.get(self._key(agent_id, session_id, key))
        return json.loads(raw) if raw is not None else None

    def set(self, agent_id: str, session_id: str, key: str, data: Dict[str, Any]) -> None:
        self._redis.set(self._key(agent_id, session_id, key), json.dumps(data))

    def delete(self, agent_id: str, session_id: str, key: str) -> None:
        self._redis.delete(self._key(agent_id, session_id, key))