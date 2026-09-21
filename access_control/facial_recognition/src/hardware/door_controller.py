"""Raspberry Pi 5 GPIO relay controller for magnetic door locks."""

from __future__ import annotations

import enum
import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from gpiozero import OutputDevice
except (ImportError, Exception):  # pragma: no cover
    OutputDevice = None


class DoorState(str, enum.Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


class DoorController:
    """Thread-safe controller for a relay-operated magnetic door lock.

    Features:
      - Compatible with Raspberry Pi 5 RP1 GPIO via gpiozero/lgpio.
      - Graceful simulation fallback for non-Pi environments (dev PCs, tests).
      - Non-blocking auto-relock timer with thread-safe debouncing.
      - Clean lock/unlock and status telemetry.
    """

    def __init__(
        self,
        pin: int = 17,
        unlock_duration: float = 5.0,
        active_high: bool = False,
        enabled: bool = True,
    ) -> None:
        self.pin = int(pin)
        self.default_duration = float(unlock_duration)
        self.active_high = bool(active_high)
        self.enabled = bool(enabled)

        self._lock = threading.Lock()
        self._state = DoorState.LOCKED
        self._unlock_until = 0.0
        self._unlock_count = 0
        self._timer: Optional[threading.Timer] = None
        self._device: Any = None
        self._is_simulated = False

        self._initialize_hardware()

    def _initialize_hardware(self) -> None:
        if not self.enabled:
            logger.info("Door relay is disabled via configuration")
            self._is_simulated = True
            return

        if OutputDevice is None:
            self._is_simulated = True
            logger.info("gpiozero not available; door relay running in simulation mode")
            return

        try:
            # initial_value=False means starts in inactive (locked) state
            self._device = OutputDevice(
                self.pin,
                active_high=self.active_high,
                initial_value=False,
            )
            self._is_simulated = False
            logger.info(
                "Hardware door relay initialized on BCM GPIO %d (active_high=%s)",
                self.pin,
                self.active_high,
            )
        except Exception as exc:
            self._device = None
            self._is_simulated = True
            logger.warning(
                "Could not initialize physical GPIO %d (%s); falling back to simulation mode",
                self.pin,
                exc,
            )

    def unlock(self, duration: Optional[float] = None) -> bool:
        """Unlock the door for the given duration (or default), then auto-relock."""
        dur = float(duration if duration is not None else self.default_duration)
        dur = max(0.05, dur)

        with self._lock:
            if not self.enabled:
                logger.debug("Door relay unlock requested, but relay is disabled")
                return False

            now = time.monotonic()
            new_until = now + dur
            if new_until > self._unlock_until:
                self._unlock_until = new_until

            if self._state != DoorState.UNLOCKED:
                self._state = DoorState.UNLOCKED
                self._unlock_count += 1
                if self._device is not None:
                    try:
                        self._device.on()
                    except Exception as exc:
                        logger.error("Failed to activate relay on GPIO %d: %s", self.pin, exc)
                logger.info(">>> DOOR UNLOCKED on GPIO %d for %.1fs <<<", self.pin, dur)

            # Cancel existing timer and reschedule
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

            remaining = max(0.1, self._unlock_until - time.monotonic())
            self._timer = threading.Timer(remaining, self._on_timer_expire)
            self._timer.daemon = True
            self._timer.start()
            return True

    def _on_timer_expire(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._unlock_until - 0.05:
                # Timer was extended while running
                remaining = max(0.1, self._unlock_until - now)
                self._timer = threading.Timer(remaining, self._on_timer_expire)
                self._timer.daemon = True
                self._timer.start()
                return

            self._apply_lock()

    def lock(self) -> bool:
        """Immediately relock the door and cancel any pending auto-relock timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            return self._apply_lock()

    def _apply_lock(self) -> bool:
        if self._state == DoorState.LOCKED:
            return True

        self._state = DoorState.LOCKED
        self._unlock_until = 0.0
        if self._device is not None:
            try:
                self._device.off()
            except Exception as exc:
                logger.error("Failed to deactivate relay on GPIO %d: %s", self.pin, exc)

        logger.info(">>> DOOR LOCKED on GPIO %d <<<", self.pin)
        return True

    @property
    def is_unlocked(self) -> bool:
        with self._lock:
            return self._state == DoorState.UNLOCKED

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            remaining = max(0.0, self._unlock_until - now) if self._state == DoorState.UNLOCKED else 0.0
            return {
                "state": self._state.value,
                "is_unlocked": self._state == DoorState.UNLOCKED,
                "is_simulated": self._is_simulated,
                "enabled": self.enabled,
                "pin": self.pin,
                "active_high": self.active_high,
                "unlock_count": self._unlock_count,
                "remaining_seconds": round(remaining, 2),
            }

    def cleanup(self) -> None:
        """Safely reset relay and release GPIO resources on shutdown."""
        self.lock()
        with self._lock:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
                self._device = None


_global_door_controller: Optional[DoorController] = None
_global_lock = threading.Lock()


def get_door_controller(
    pin: Optional[int] = None,
    unlock_duration: Optional[float] = None,
    active_high: Optional[bool] = None,
    enabled: Optional[bool] = None,
) -> DoorController:
    """Retrieve or create the singleton DoorController instance."""
    global _global_door_controller
    with _global_lock:
        if _global_door_controller is None:
            c_pin = pin if pin is not None else int(os.getenv("EDGE_DOOR_RELAY_PIN", "17"))
            c_dur = unlock_duration if unlock_duration is not None else float(os.getenv("EDGE_DOOR_UNLOCK_DURATION_SECONDS", "5.0"))
            c_act = active_high if active_high is not None else os.getenv("EDGE_DOOR_RELAY_ACTIVE_HIGH", "false").lower() in {"1", "true", "yes", "on"}
            c_enb = enabled if enabled is not None else os.getenv("EDGE_DOOR_RELAY_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            _global_door_controller = DoorController(
                pin=c_pin,
                unlock_duration=c_dur,
                active_high=c_act,
                enabled=c_enb,
            )
        return _global_door_controller


def reset_door_controller() -> None:
    """Reset singleton for testing purposes."""
    global _global_door_controller
    with _global_lock:
        if _global_door_controller is not None:
            _global_door_controller.cleanup()
            _global_door_controller = None
