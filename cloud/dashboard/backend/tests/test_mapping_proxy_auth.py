import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.routers import mapping_proxy


def test_admin_proxy_authenticates_cloud_cookie_and_issues_node_admin_token(monkeypatch):
    cloud_secret = "test-cloud-secret-that-is-long-enough"
    mapping_secret = "test-mapping-secret-that-is-long-enough"
    monkeypatch.setattr(settings, "JWT_SECRET", cloud_secret)
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "ACCESS_COOKIE_NAME", "access_token")
    monkeypatch.setattr(settings, "MAPPING_JWT_SECRET", mapping_secret)
    monkeypatch.setattr(mapping_proxy, "MAPPING_MICROSERVICE_URL", "http://mapping.test")
    admin = SimpleNamespace(admin_type="SYSTEM_ADMIN", user=SimpleNamespace(email="admin@example.test"))
    auth_requests = []

    def authenticate(request, _db):
        auth_requests.append(request)
        if not request.cookies.get("access_token"):
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        return admin

    monkeypatch.setattr(mapping_proxy, "get_current_admin", authenticate)
    forwarded = {}

    class FakeAsyncClient:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def request(self, **kwargs):
            forwarded.update(kwargs)
            payload = jwt.decode(kwargs["headers"]["authorization"][7:], mapping_secret, algorithms=["HS256"])
            assert payload["type"] == "SYSTEM_ADMIN"
            assert payload["email"] == "admin@example.test"
            assert payload["exp"] <= time.time() + 300
            assert "cookie" not in kwargs["headers"]
            return SimpleNamespace(content=b'{"ok":true}', status_code=200, headers={"content-type": "application/json"})

    monkeypatch.setattr(mapping_proxy.httpx, "AsyncClient", FakeAsyncClient)
    app = FastAPI()
    app.include_router(mapping_proxy.router, prefix="/api/mapping-notification")
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)

    assert client.get("/api/mapping-notification/api/global-nodes").status_code == 401
    cloud_token = jwt.encode({"sub": "admin-1", "exp": 2_000_000_000}, cloud_secret, algorithm="HS256")
    accepted = client.get(
        "/api/mapping-notification/api/global-nodes",
        cookies={"access_token": cloud_token},
    )
    assert accepted.status_code == 200
    assert len(auth_requests) == 2
    assert forwarded["url"] == "http://mapping.test/api/global-nodes"


def test_public_mapping_reads_remain_public_and_do_not_forward_cloud_cookie(monkeypatch):
    observed = {}

    class FakeAsyncClient:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def request(self, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(content=b"[]", status_code=200, headers={"content-type": "application/json"})

    monkeypatch.setattr(mapping_proxy.httpx, "AsyncClient", FakeAsyncClient)
    app = FastAPI()
    app.include_router(mapping_proxy.router, prefix="/api/mapping-notification")
    app.dependency_overrides[get_db] = lambda: object()
    response = TestClient(app).get("/api/mapping-notification/api/floorplans", cookies={"access_token": "not-forwarded"})
    assert response.status_code == 200
    assert "cookie" not in observed["headers"]
    assert "authorization" not in observed["headers"]
