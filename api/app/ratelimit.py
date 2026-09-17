"""Per-client leaky bucket for model calls.

Each client has a bucket that fills by one per model call and leaks one unit every
LLM_RATE_LEAK_SECONDS. A call is allowed while the level stays at or under
LLM_RATE_CAPACITY, so a client can burst `capacity` calls and then sustain one call per
leak interval. The client key is the request's remote address; behind a proxy, ProxyFix
(TRUSTED_PROXY_HOPS) rewrites that from X-Forwarded-For, so the header is only honored
for the configured number of hops and cannot be spoofed by the client. State is per
process (per Fluid-compute instance on Vercel), which is enough to blunt abuse of a demo.

Routes call `rate_limit_response()` right before they would spend tokens, so cached
answers and rejected requests do not consume budget.
"""
from __future__ import annotations

import math
import threading
import time

from flask import Response, jsonify, request

from .config import Config


class LeakyBucket:
    def __init__(self, capacity: float, leak_seconds: float) -> None:
        self.capacity, self.leak_seconds = max(1.0, capacity), max(0.001, leak_seconds)
        self._levels: dict[str, tuple[float, float]] = {}  # key -> (level, last_ts)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            level, last = self._levels.get(key, (0.0, now))
            level = max(0.0, level - (now - last) / self.leak_seconds)
            if len(self._levels) > 10_000:  # forget idle clients (rare; only under many distinct keys)
                idle = self.capacity * self.leak_seconds
                self._levels = {k: v for k, v in self._levels.items() if now - v[1] < idle}
            if level + 1 <= self.capacity:
                self._levels[key] = (level + 1, now)
                return True, 0
            self._levels[key] = (level, now)
            return False, int(math.ceil((level + 1 - self.capacity) * self.leak_seconds))


_bucket: LeakyBucket | None = None


def bucket() -> LeakyBucket:
    global _bucket
    if _bucket is None:
        _bucket = LeakyBucket(Config.LLM_RATE_CAPACITY, Config.LLM_RATE_LEAK_SECONDS)
    return _bucket


def rate_limit_response() -> Response | None:
    """Charge one model call to the caller. Returns a 429 response to send, or None to proceed."""
    if not Config.RATE_LIMIT_ENABLED:
        return None
    allowed, retry_after = bucket().check(request.remote_addr or "unknown")
    if allowed:
        return None
    resp = jsonify({"error": f"rate limit: too many model calls, try again in {retry_after}s", "retry_after": retry_after})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(retry_after)
    return resp
