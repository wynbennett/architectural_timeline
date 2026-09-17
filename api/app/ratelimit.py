"""Per-client leaky bucket for endpoints that call the model.

Each client IP has a bucket that fills by one per call and leaks one unit every
LLM_RATE_LEAK_SECONDS. A call is allowed while the level stays at or under
LLM_RATE_CAPACITY, so a client can burst `capacity` calls and then sustain one call per
leak interval. State is per process (per Fluid-compute instance on Vercel), which is
enough to blunt abuse of a public demo.
"""
from __future__ import annotations

import math
import threading
import time
from functools import wraps

from flask import jsonify, request

from .config import Config


class LeakyBucket:
    def __init__(self, capacity: float, leak_seconds: float) -> None:
        self.capacity, self.leak_seconds = capacity, leak_seconds
        self._levels: dict[str, tuple[float, float]] = {}  # key -> (level, last_ts)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            level, last = self._levels.get(key, (0.0, now))
            level = max(0.0, level - (now - last) / self.leak_seconds)
            if level + 1 <= self.capacity:
                self._levels[key] = (level + 1, now)
                if len(self._levels) > 10_000:  # forget idle clients
                    self._levels = {k: v for k, v in self._levels.items() if now - v[1] < self.capacity * self.leak_seconds}
                return True, 0
            self._levels[key] = (level, now)
            return False, int(math.ceil((level + 1 - self.capacity) * self.leak_seconds))


_bucket: LeakyBucket | None = None


def bucket() -> LeakyBucket:
    global _bucket
    if _bucket is None:
        _bucket = LeakyBucket(Config.LLM_RATE_CAPACITY, Config.LLM_RATE_LEAK_SECONDS)
    return _bucket


def client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.headers.get("X-Real-IP") or request.remote_addr or "unknown"


def llm_rate_limited(view):
    """Decorator for routes that spend model tokens."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if Config.RATE_LIMIT_ENABLED:
            allowed, retry_after = bucket().check(client_ip())
            if not allowed:
                resp = jsonify({"error": f"rate limit: too many model calls, try again in {retry_after}s", "retry_after": retry_after})
                resp.status_code = 429
                resp.headers["Retry-After"] = str(retry_after)
                return resp
        return view(*args, **kwargs)

    return wrapper
