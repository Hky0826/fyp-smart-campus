from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException, Request, status

from app.core.config import settings


@dataclass
class _Bucket:
    hits: deque[float]


class RateLimiter:
    """Small local fallback; deployments should set RATE_LIMIT_REDIS_URL."""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(deque()))
        self._lock = Lock()
        self.redis = None
        if settings.APP_ENV == "production":
            if not settings.RATE_LIMIT_REDIS_URL:
                raise RuntimeError("Production rate limiting requires RATE_LIMIT_REDIS_URL")
            try:
                import redis
                self.redis = redis.Redis.from_url(settings.RATE_LIMIT_REDIS_URL, decode_responses=True)
                self.redis.ping()
            except Exception as exc:
                raise RuntimeError("Production Redis rate limiting is unavailable") from exc

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if self.redis is not None:
            redis_key = f"smart-campus:rate:{key}"
            try:
                with self.redis.pipeline() as pipeline:
                    pipeline.incr(redis_key)
                    pipeline.expire(redis_key, window_seconds)
                    count, _ = pipeline.execute()
                return int(count) <= limit
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Rate limiting service unavailable") from exc
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
            while bucket.hits and bucket.hits[0] <= now - window_seconds:
                bucket.hits.popleft()
            if len(bucket.hits) >= limit:
                return False
            bucket.hits.append(now)
            return True


limiter = RateLimiter()

_failed_logins: dict[str, tuple[int, float]] = {}


def record_failed_login(key: str, lockout_seconds: int = 300, threshold: int = 5) -> None:
    if limiter.redis is not None:
        try:
            redis_key = f"smart-campus:login-failures:{key}"
            count = int(limiter.redis.incr(redis_key))
            limiter.redis.expire(redis_key, lockout_seconds)
            if count >= threshold:
                lockout = lockout_seconds * min(8, 2 ** max(0, count - threshold))
                limiter.redis.setex(f"{redis_key}:locked", lockout, "1")
                raise HTTPException(status_code=429, detail="Account temporarily locked")
            return
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Rate limiting service unavailable") from exc
    now = time.monotonic()
    count, locked_until = _failed_logins.get(key, (0, 0.0))
    if locked_until > now:
        raise HTTPException(status_code=429, detail="Account temporarily locked")
    count += 1
    _failed_logins[key] = (count, now + lockout_seconds if count >= threshold else 0.0)


def ensure_login_allowed(key: str) -> None:
    if limiter.redis is not None:
        try:
            if limiter.redis.exists(f"smart-campus:login-failures:{key}:locked"):
                raise HTTPException(status_code=429, detail="Account temporarily locked")
            return
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Rate limiting service unavailable") from exc
    value = _failed_logins.get(key)
    if value and value[1] > time.monotonic():
        raise HTTPException(status_code=429, detail="Account temporarily locked")


def clear_failed_logins(key: str) -> None:
    if limiter.redis is not None:
        try:
            limiter.redis.delete(f"smart-campus:login-failures:{key}", f"smart-campus:login-failures:{key}:locked")
            return
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Rate limiting service unavailable") from exc
    _failed_logins.pop(key, None)


def client_ip(request: Request, trusted_proxy_ips: tuple[str, ...] = ()) -> str:
    peer = request.client.host if request.client else "unknown"
    # Forwarded headers are attacker-controlled unless the direct peer is a
    # configured reverse proxy.
    if peer in trusted_proxy_ips:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return peer


def enforce_limit(key: str, limit: int, window_seconds: int, detail: str = "Rate limit exceeded") -> None:
    if not limiter.allow(key, limit, window_seconds):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail, headers={"Retry-After": str(window_seconds)})
