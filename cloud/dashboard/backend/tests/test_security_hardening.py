import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.device_auth import canonical_request, sign_request
from app.core.config import Settings


def test_device_signature_binds_body_path_and_query():
    signature = sign_request("device-secret", "POST", "/api/sync/upstream/logs", "a=1", "1", "n" * 16, b"body")
    assert signature != sign_request("device-secret", "POST", "/api/sync/upstream/logs", "a=1", "1", "n" * 16, b"changed")
    assert canonical_request("POST", "/a", "", "1", "n" * 16, b"") != canonical_request("POST", "/b", "", "1", "n" * 16, b"")


def test_jwt_secret_has_no_default_fallback(monkeypatch):
    settings = Settings()
    settings.JWT_SECRET = ""
    try:
        settings.validate_security()
    except RuntimeError as exc:
        assert "JWT_SECRET" in str(exc)
    else:
        raise AssertionError("missing JWT_SECRET must fail validation")
