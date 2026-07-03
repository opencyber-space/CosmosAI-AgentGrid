import collections
import sys


class LFUCache:
    def __init__(self, max_size_bytes: int):
        self.max_size_bytes = max_size_bytes
        self.cache = {}
        self.metadata = {}
        self.freq_map = collections.defaultdict(collections.OrderedDict)  # freq -> {key: None}
        self.key_freq = {}
        self.current_size = 0
        self.min_freq = 0

    def _get_size(self, value: bytes) -> int:
        return len(value)

    def _evict(self):
        while self.current_size > self.max_size_bytes:
            if self.min_freq not in self.freq_map or not self.freq_map[self.min_freq]:
                self.min_freq += 1
                continue

            key, _ = self.freq_map[self.min_freq].popitem(last=False)
            value, freq = self.cache.pop(key)
            self.current_size -= self._get_size(value)
            self.metadata.pop(key, None)
            del self.key_freq[key]

    def add(self, key: str, value: bytes, metadata: dict = None):
        size = self._get_size(value)

        if size > self.max_size_bytes:
            raise ValueError(f"Item size {size} exceeds max cache size {self.max_size_bytes}")

        if key in self.cache:
            # Update existing key
            self.remove(key)

        # Evict until enough space
        self.current_size += size
        self._evict()

        # Insert new
        self.cache[key] = (value, 1)
        self.metadata[key] = metadata or {}
        self.freq_map[1][key] = None
        self.key_freq[key] = 1
        self.min_freq = 1

    def get_metadata(self, key: str) -> dict:
        return self.metadata.get(key, {})

    def get(self, key: str) -> bytes:
        if key not in self.cache:
            return None

        value, freq = self.cache[key]

        # Remove from current freq list
        del self.freq_map[freq][key]
        if not self.freq_map[freq]:
            del self.freq_map[freq]
            if self.min_freq == freq:
                self.min_freq += 1

        # Update freq
        new_freq = freq + 1
        self.cache[key] = (value, new_freq)
        self.freq_map[new_freq][key] = None
        self.key_freq[key] = new_freq

        return value

    def remove(self, key: str):
        if key not in self.cache:
            return

        value, freq = self.cache.pop(key)
        self.current_size -= self._get_size(value)
        self.metadata.pop(key, None)
        del self.freq_map[freq][key]
        if not self.freq_map[freq]:
            del self.freq_map[freq]
            if self.min_freq == freq:
                self.min_freq += 1
        del self.key_freq[key]

    def clear(self):
        self.cache.clear()
        self.metadata.clear()
        self.freq_map.clear()
        self.key_freq.clear()
        self.current_size = 0
        self.min_freq = 0
