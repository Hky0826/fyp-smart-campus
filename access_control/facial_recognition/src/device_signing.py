from __future__ import annotations

import fnmatch
import hashlib
import hmac
import base64
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import requests


def validate_allowed_cloud_host(hostname: str | None) -> None:
    """Enforce optional ALLOWED_CLOUD_HOSTS allowlist (supports wildcards like *.example.com)."""
    raw = os.getenv("ALLOWED_CLOUD_HOSTS", "").strip()
    if not raw:
        return
    host = (hostname or "").strip().lower()
    patterns = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not host or not any(fnmatch.fnmatch(host, pat) for pat in patterns):
        raise ValueError(f"Cloud host '{host or 'unknown'}' is not in ALLOWED_CLOUD_HOSTS")


def validate_cloud_url(url: str, allow_insecure_loopback: bool = False) -> None:
    parsed = urlsplit(url)
    validate_allowed_cloud_host(parsed.hostname)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and allow_insecure_loopback and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    import ipaddress
    if parsed.scheme == "http" and (
        os.getenv("EDGE_ALLOW_INSECURE_HTTP", "false").lower() in {"1", "true", "yes", "on"}
        or (allow_insecure_loopback and os.getenv("APP_ENV", "development").lower() != "production")
    ):
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback:
                return
        except (ValueError, TypeError):
            pass
    raise ValueError("Cloud URLs must use HTTPS except explicit loopback development mode")


def signed_headers(secret: str, device_id: str, method: str, url: str, body: bytes = b"", params: dict | None = None) -> dict[str, str]:
    if not secret:
        raise ValueError("EDGE_SYNC_DEVICE_SECRET is required for signed cloud requests")
    parsed = urlsplit(url)
    query = urlencode(params or {}, doseq=True)
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    canonical = "\n".join((method.upper(), parsed.path or "/", query, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
    signature = hmac.new(secret.encode(), canonical, hashlib.sha256).digest()
    return {
        "X-Device-ID": device_id,
        "X-Device-Timestamp": timestamp,
        "X-Device-Nonce": nonce,
        "X-Device-Signature": base64.urlsafe_b64encode(signature).decode().rstrip("="),
    }


def sign_assertion(secret: str, assertion: dict) -> str:
    """Sign the canonical face-auth assertion sent to cloud edge-auth."""
    encoded = json.dumps(assertion, sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
