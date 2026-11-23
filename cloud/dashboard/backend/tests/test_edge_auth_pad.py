import pytest
from fastapi import HTTPException

from app.routers.edge_auth import _validated_pad_score
from app.core.config import settings


@pytest.mark.parametrize("score", [0.05, -0.1, 1.01, float("nan"), float("inf"), None, "invalid", "0.9", True, 10 ** 1000])
def test_cloud_rejects_invalid_or_below_threshold_pad_scores(monkeypatch, score):
    monkeypatch.setattr(settings, "EDGE_ACCESS_PAD_THRESHOLD", 0.75)
    with pytest.raises(HTTPException) as error:
        _validated_pad_score(score)
    assert error.value.status_code == 401


def test_cloud_accepts_pad_score_at_configured_threshold(monkeypatch):
    monkeypatch.setattr(settings, "EDGE_ACCESS_PAD_THRESHOLD", 0.75)
    assert _validated_pad_score(0.75) == 0.75
