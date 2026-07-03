import redis
import logging

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
