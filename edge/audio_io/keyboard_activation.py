"""Keyboard activation for the edge audio interaction pipeline."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from threading import Event


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyboardActivationEvent:
    """A keyboard activation event."""

    key: str
    detected_at: float


class SpacebarActivationDetector:
    """Wait for the user to press the space bar."""

    def wait_for_spacebar(self, stop_event: Event | None = None) -> KeyboardActivationEvent | None:
        """Block until space is pressed or a stop event is set."""
        logger.info("Waiting for space bar to activate chatbot")
        if os.name == "nt":
            return self._wait_windows(stop_event)
        return self._wait_posix(stop_event)

    def _wait_windows(self, stop_event: Event | None) -> KeyboardActivationEvent | None:
        try:
            import msvcrt
        except ImportError as exc:  # pragma: no cover - Windows-only fallback.
            raise RuntimeError("msvcrt is required for keyboard activation on Windows.") from exc

        while stop_event is None or not stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == " ":
                    return KeyboardActivationEvent(key="space", detected_at=time.time())
            time.sleep(0.05)
        return None

    def _wait_posix(self, stop_event: Event | None) -> KeyboardActivationEvent | None:
        if not sys.stdin or not sys.stdin.isatty():
            raise RuntimeError("Keyboard activation requires an interactive terminal.")

        try:
            import select
            import termios
            import tty
        except ImportError as exc:  # pragma: no cover - POSIX modules are platform-provided.
            raise RuntimeError("POSIX terminal support is required for keyboard activation.") from exc

        fd = sys.stdin.fileno()
        original_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while stop_event is None or not stop_event.is_set():
                readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                if readable and sys.stdin.read(1) == " ":
                    return KeyboardActivationEvent(key="space", detected_at=time.time())
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)
        return None
