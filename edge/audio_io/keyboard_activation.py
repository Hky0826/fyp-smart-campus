"""Keyboard activation for the edge audio interaction pipeline."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable
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
        return self.wait_for_key({" "}, stop_event)

    def wait_for_key(
        self,
        keys: Iterable[str],
        stop_event: Event | None = None,
    ) -> KeyboardActivationEvent | None:
        """Block until one of the requested keys is pressed or a stop event is set."""
        accepted_keys = set(keys)
        key_names = ", ".join(_display_key(key) for key in sorted(accepted_keys))
        logger.info("Waiting for keypress: %s", key_names)
        if os.name == "nt":
            return self._wait_windows(accepted_keys, stop_event)
        return self._wait_posix(accepted_keys, stop_event)

    def _wait_windows(self, accepted_keys: set[str], stop_event: Event | None) -> KeyboardActivationEvent | None:
        try:
            import msvcrt
        except ImportError as exc:  # pragma: no cover - Windows-only fallback.
            raise RuntimeError("msvcrt is required for keyboard activation on Windows.") from exc

        while stop_event is None or not stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in accepted_keys:
                    return KeyboardActivationEvent(key=_event_key_name(key), detected_at=time.time())
            time.sleep(0.05)
        return None

    def _wait_posix(self, accepted_keys: set[str], stop_event: Event | None) -> KeyboardActivationEvent | None:
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
            tty.setraw(fd)
            while stop_event is None or not stop_event.is_set():
                readable, _, _ = select.select([fd], [], [], 0.1)
                if readable:
                    key = os.read(fd, 1).decode(errors="ignore")
                    if key in accepted_keys:
                        return KeyboardActivationEvent(key=_event_key_name(key), detected_at=time.time())
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)
        return None


def _display_key(key: str) -> str:
    if key == " ":
        return "SPACE"
    return key


def _event_key_name(key: str) -> str:
    if key == " ":
        return "space"
    return key
