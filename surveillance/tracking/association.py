"""Identity association and persistent track binding manager."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class TrackIdentity:
    """Identity record associated with an active ByteTrack track ID."""

    track_id: int
    identity: str = "unknown"
    user_id: Optional[str] = None
    similarity: float = 0.0
    matched_template: Optional[str] = None
    status: str = "unknown"  # "unknown" or "recognized"
    first_recognized_frame: Optional[int] = None
    last_seen_frame: int = 0
    event_logged: bool = False

    @property
    def is_recognized(self) -> bool:
        return self.status == "recognized" and self.user_id is not None

    def bind_match(
        self,
        user_id: str,
        identity: str,
        similarity: float,
        matched_template: Optional[str] = None,
        frame_id: int = 0,
    ) -> None:
        """Bind recognized user identity to this track permanently for its lifetime."""
        self.user_id = str(user_id)
        self.identity = str(identity)
        self.similarity = float(similarity)
        self.matched_template = matched_template
        self.status = "recognized"
        if self.first_recognized_frame is None:
            self.first_recognized_frame = frame_id
        self.last_seen_frame = frame_id
        logger.info(
            "Bound track ID %s to persistent identity '%s' (user_id=%s, similarity=%.4f)",
            self.track_id,
            self.identity,
            self.user_id,
            self.similarity,
        )


class IdentityManager:
    """Manages persistent track-to-identity bindings over ByteTrack track lifecycles."""

    def __init__(self) -> None:
        self._identities: Dict[int, TrackIdentity] = {}

    def get_identity(self, track_id: int) -> TrackIdentity:
        """Fetch or create identity record for a given track ID."""
        if track_id not in self._identities:
            self._identities[track_id] = TrackIdentity(track_id=track_id)
        return self._identities[track_id]

    def associate_identity(
        self,
        track_id: int,
        user_id: str,
        identity: str,
        similarity: float,
        matched_template: Optional[str] = None,
        frame_id: int = 0,
    ) -> TrackIdentity:
        """Associate recognized identity with track ID."""
        record = self.get_identity(track_id)
        record.bind_match(
            user_id=user_id,
            identity=identity,
            similarity=similarity,
            matched_template=matched_template,
            frame_id=frame_id,
        )
        return record

    def should_recognize(self, track_id: int) -> bool:
        """Requirement 8: Avoid repeatedly running face recognition once a track has been recognized."""
        record = self._identities.get(track_id)
        if record is None:
            return True
        return not record.is_recognized

    def update_active_tracks(self, active_track_ids: Set[int], frame_id: int = 0) -> None:
        """Requirement 7: Handle track loss and track expiration. Remove identities for expired tracks."""
        existing_ids = set(self._identities.keys())
        expired_ids = existing_ids - active_track_ids

        for expired_id in expired_ids:
            record = self._identities.pop(expired_id)
            logger.info(
                "Track ID %s expired. Removed persistent identity binding for user %s (%s).",
                expired_id,
                record.user_id,
                record.identity,
            )

        for track_id in active_track_ids:
            if track_id in self._identities:
                self._identities[track_id].last_seen_frame = frame_id

    def reset(self) -> None:
        """Clear all track identity bindings."""
        self._identities.clear()
