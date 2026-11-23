import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import config as config_module
from app.core.database import get_db
from app.core.device_auth import sign_assertion
from app.models.models import FaceAuthChallenge, User
from app.routers import edge_auth


class FakeQuery:
    def __init__(self, db, model):
        self.db, self.model, self.filters = db, model, {}

    def filter_by(self, **filters):
        self.filters.update(filters)
        return self

    def first(self):
        value = self.db.user if self.model is User else self.db.challenge
        if not value or any(getattr(value, key) != expected for key, expected in self.filters.items()):
            return None
        return value


class FakeDB:
    def __init__(self):
        self.user = SimpleNamespace(user_id=7, is_active=True, email="user@example.test", given_name="Test", full_name="Test User", roles=[])
        self.challenge = SimpleNamespace(
            challenge_id="challenge-1", device_id="edge-1", user_id=7,
            expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=1), used_at=None,
        )

    def query(self, model):
        return FakeQuery(self, model)

    def execute(self, _statement):
        if self.challenge.used_at is not None:
            return SimpleNamespace(rowcount=0)
        values = _statement.compile().params
        self.challenge.pad_score = values["pad_score"]
        self.challenge.liveness_passed = values["liveness_passed"]
        self.challenge.used_at = dt.datetime.utcnow()
        return SimpleNamespace(rowcount=1)

    def add(self, _value): pass
    def commit(self): pass
    def refresh(self, value): value.session_id = 1
    def rollback(self): pass


@pytest.fixture
def edge_client(monkeypatch):
    db = FakeDB()
    device = SimpleNamespace(device_id="edge-1", device_secret_ciphertext="test-secret-ciphertext")
    monkeypatch.setattr(edge_auth, "decrypt_device_secret", lambda _ciphertext: "test-device-secret")
    monkeypatch.setattr(config_module.settings, "JWT_SECRET", "test-cloud-secret-that-is-long-enough")
    monkeypatch.setattr(config_module.settings, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(config_module.settings, "EDGE_ACCESS_PAD_THRESHOLD", 0.75)
    app = FastAPI()
    app.include_router(edge_auth.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[edge_auth.require_signed_device_request] = lambda: device
    return TestClient(app), db


def assertion(score):
    value = {
        "challenge_id": "challenge-1", "user_id": 7,
        "match_passed": True, "liveness_passed": True,
        "pad_score": score, "pad_model_version": "test-pad",
    }
    return value, sign_assertion("test-device-secret", value)


def request_payload(score):
    value, signature = assertion(score)
    return {
        "user_id": 7, "device_id": "edge-1", "challenge_id": "challenge-1",
        "assertion": value, "assertion_signature": signature,
    }


def test_cloud_token_boundary_rejects_low_pad_and_allows_threshold_then_replay_fails(edge_client):
    client, db = edge_client
    rejected = client.post("/api/edge-auth/token", json=request_payload(0.05))
    assert rejected.status_code == 401
    assert db.challenge.used_at is None

    accepted = client.post("/api/edge-auth/token", json=request_payload(0.75))
    assert accepted.status_code == 200
    assert db.challenge.used_at is not None
    assert db.challenge.pad_score == 0.75
    assert db.challenge.liveness_passed is True
    replay = client.post("/api/edge-auth/token", json=request_payload(0.75))
    assert replay.status_code == 401


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.01])
def test_cloud_http_boundary_rejects_invalid_pad_values(edge_client, score):
    client, _ = edge_client
    response = client.post(
        "/api/edge-auth/token",
        content=json.dumps(request_payload(score)),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("field", ["match_passed", "liveness_passed"])
def test_cloud_http_boundary_requires_boolean_assertion_success(edge_client, field):
    client, db = edge_client
    payload = request_payload(0.9)
    payload["assertion"][field] = 1
    payload["assertion_signature"] = sign_assertion("test-device-secret", payload["assertion"])
    response = client.post("/api/edge-auth/token", json=payload)
    assert response.status_code == 401
    assert db.challenge.used_at is None
