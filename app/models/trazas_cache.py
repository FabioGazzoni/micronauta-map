import time

from app.config import TRAZAS_CACHE_TTL_SECONDS


class TrazasCache:
    def __init__(self, ttl_seconds: int = TRAZAS_CACHE_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._data = None
        self._timestamp = 0.0

    def get(self):
        if self._data is None:
            return None
        if time.time() - self._timestamp >= self._ttl:
            return None
        return self._data

    def set(self, data):
        self._data = data
        self._timestamp = time.time()

    def clear(self):
        self._data = None
        self._timestamp = 0.0
