import redis
import logging
from typing import List


class RedisInterface:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client = None
        self.logger = logging.getLogger("RedisInterface")

    def connect(self):
        try:
            self.client = redis.from_url(self.redis_url, decode_responses=False)
            self.client.ping()
            self.logger.info(f"Connected to Redis at {self.redis_url}")
        except redis.RedisError as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            raise

    def set(self, key: str, value: bytes):
        if not self.client:
            raise ConnectionError("Redis client not connected.")
        self.client.set(key, value)
        self.logger.debug(f"Set key={key}")

    def get(self, key: str) -> bytes:
        if not self.client:
            raise ConnectionError("Redis client not connected.")
        value = self.client.get(key)
        if value is None:
            self.logger.warning(f"Key '{key}' not found in Redis")
        return value

    def lpush(self, queue_name: str, value: bytes):
        if not self.client:
            raise ConnectionError("Redis client not connected.")
        self.client.lpush(queue_name, value)
        self.logger.debug(f"Pushed to queue='{queue_name}'")

    def rpop(self, queue_name: str) -> bytes:
        if not self.client:
            raise ConnectionError("Redis client not connected.")
        value = self.client.rpop(queue_name)
        if value is None:
            self.logger.warning(f"Queue '{queue_name}' is empty")
        return value

    def pull_all_inputs(self, queue_name: str) -> List[bytes]:
        if not self.client:
            raise ConnectionError("Redis client not connected.")
        results = []
        while True:
            value = self.client.rpop(queue_name)
            if value is None:
                break
            results.append(value)
        self.logger.debug(f"Pulled {len(results)} items from queue='{queue_name}'")
        return results
    
    def listen_for_inputs(self, queue_name: str):
        if not self.client:
            raise ConnectionError("Redis client not connected.")
        self.logger.info(f"Listening on queue='{queue_name}' for incoming data...")
        while True:
            try:
                _, value = self.client.blpop(queue_name)
                yield value
            except redis.RedisError as e:
                self.logger.error(f"Redis error on '{queue_name}': {e}")
                break
