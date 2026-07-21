"""Prerecorded spoken feedback for final access-control decisions."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from .audio_player import AudioPlayer


logger = logging.getLogger(__name__)

SOUND_DIR = Path(__file__).resolve().parent / "sounds"


class AccessFeedbackPlayer:
    """Play the bundled access-result clips without blocking the Qt UI thread."""

    _CLIPS = {
        "access-granted": SOUND_DIR / "access_granted.wav",
        "access-denied": SOUND_DIR / "access_denied.wav",
    }

    def __init__(self, player_factory: Callable[[], AudioPlayer] = AudioPlayer) -> None:
        self._player = player_factory()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._closed = False

    def play_for_mode(self, mode: str) -> None:
        """Play the clip for a newly entered final access mode, if one exists."""
        clip = self._CLIPS.get(mode)
        if clip is None:
            return

        with self._lock:
            if self._closed or (self._worker and self._worker.is_alive()):
                return
            self._worker = threading.Thread(
                target=self._play,
                args=(mode, clip),
                daemon=True,
                name="access-feedback-audio",
            )
            self._worker.start()

    def close(self) -> None:
        """Prevent new playback when the kiosk is shutting down."""
        with self._lock:
            self._closed = True

    def _play(self, mode: str, clip: Path) -> None:
        try:
            self._player.play_wav(clip)
            logger.info("Played prerecorded access feedback mode=%s clip=%s", mode, clip.name)
        except Exception as exc:  # pragma: no cover - depends on the device audio stack
            logger.warning("Could not play prerecorded access feedback mode=%s: %s", mode, exc)

