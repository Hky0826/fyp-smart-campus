"""Identity association and persistent track binding manager for access control."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class TrackIdentity:
    """Identity and access decision record associated with an active track ID."""

    track_id: int
    identity: str = "unknown"
    user_id: Optional[str] = None
    similarity: float = 0.0
    matched_template: Optional[str] = None
    access_decision: str = "PENDING"  # "GRANTED", "DENIED", "PENDING"
    status: str = "unknown"  # "unknown", "recognized", "denied"
    reason: Optional[str] = None
    cached_payload: Optional[Dict[str, Any]] = None
    first_recognized_at: Optional[float] = None
    last_seen_at: float = 0.0

    @property
    def is_recognized(self) -> bool:
        return self.status == "recognized" and self.user_id is not None

    @property
    def is_decided(self) -> bool:
        return self.status in ("recognized", "denied")

    @property
    def is_denied(self) -> bool:
        return self.status == "denied"

    def bind_match(
        self,
        user_id: str,
        identity: str,
        similarity: float,
        matched_template: Optional[str] = None,
        access_decision: str = "GRANTED",
        reason: Optional[str] = None,
        cached_payload: Optional[Dict[str, Any]] = None,
        timestamp: float = 0.0,
    ) -> None:
        """Bind recognized user identity and access decision to this track."""
        self.user_id = str(user_id)
        self.identity = str(identity)
        self.similarity = float(similarity)
        self.matched_template = matched_template
        self.access_decision = access_decision
        self.status = "recognized"
        self.reason = reason
        self.cached_payload = cached_payload
        self.last_seen_at = timestamp
        if self.first_recognized_at is None and timestamp > 0:
            self.first_recognized_at = timestamp
        logger.info(
            "Bound track ID %s to identity '%s' (user_id=%s, similarity=%.4f)",
            self.track_id,
            self.identity,
            self.user_id,
            self.similarity,
        )

    def bind_denial(
        self,
        reason: str,
        similarity: float = 0.0,
        cached_payload: Optional[Dict[str, Any]] = None,
        timestamp: float = 0.0,
    ) -> None:
        """Bind denial reason and access decision to this track."""
        self.access_decision = "DENIED"
        self.status = "denied"
        self.reason = reason
        self.similarity = float(similarity)
        self.cached_payload = cached_payload
        self.last_seen_at = timestamp
        self.denied_at = timestamp
        logger.info(
            "Bound track ID %s to denial: reason='%s' (similarity=%.4f)",
            self.track_id,
            self.reason,
            self.similarity,
        )

    def touch(self, timestamp: float) -> None:
        """Update last seen timestamp."""
        self.last_seen_at = timestamp


class IdentityManager:
    """Manages identity associations for active tracks."""

    def __init__(self) -> None:
        self._identities: Dict[int, TrackIdentity] = {}

    def reset(self) -> None:
        """Clear all active identities."""
        self._identities.clear()

    def get_identity(self, track_id: int) -> Optional[TrackIdentity]:
        """Get identity record for track if it exists."""
        return self._identities.get(track_id)

    def get_or_create(self, track_id: int, timestamp: float = 0.0) -> TrackIdentity:
        """Get existing identity record or create a new one."""
        if track_id not in self._identities:
            self._identities[track_id] = TrackIdentity(track_id=track_id, last_seen_at=timestamp)
        return self._identities[track_id]

    def bind_match(
        self,
        track_id: int,
        user_id: str,
        identity: str,
        similarity: float,
        matched_template: Optional[str] = None,
        access_decision: str = "GRANTED",
        reason: Optional[str] = None,
        cached_payload: Optional[Dict[str, Any]] = None,
        timestamp: float = 0.0,
    ) -> TrackIdentity:
        """Bind recognized user identity to track."""
        record = self.get_or_create(track_id, timestamp=timestamp)
        record.bind_match(
            user_id=user_id,
            identity=identity,
            similarity=similarity,
            matched_template=matched_template,
            access_decision=access_decision,
            reason=reason,
            cached_payload=cached_payload,
            timestamp=timestamp,
        )
        return record

    def bind_denial(
        self,
        track_id: int,
        reason: str,
        similarity: float = 0.0,
        cached_payload: Optional[Dict[str, Any]] = None,
        timestamp: float = 0.0,
    ) -> TrackIdentity:
        """Bind denial to track."""
        record = self.get_or_create(track_id, timestamp=timestamp)
        record.bind_denial(
            reason=reason,
            similarity=similarity,
            cached_payload=cached_payload,
            timestamp=timestamp,
        )
        return record

    associate_identity = bind_match
    associate_denial = bind_denial

    def should_recognize(self, track_id: int, timestamp: float = 0.0) -> bool:
        """Check if track requires recognition.

        Avoid repeatedly running face recognition once a track has been recognized/granted.
        If authentication failed or is below threshold, it should keep on checking!
        """
        record = self._identities.get(track_id)
        if record is None:
            return True
        return not record.is_recognized

    def update_active_tracks(self, active_track_ids: Set[int], timestamp: float = 0.0) -> None:
        """Prune track identities that are no longer active."""
        existing_ids = set(self._identities.keys())
        expired_ids = existing_ids - active_track_ids

        for expired_id in expired_ids:
            logger.debug("Track ID %s expired, removing identity binding", expired_id)
            del self._identities[expired_id]

        for active_id in active_track_ids:
            if active_id in self._identities:
                self._identities[active_id].last_seen_at = timestamp
