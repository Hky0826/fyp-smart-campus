"""Mock and optional GPIO relay access controllers."""
from dataclasses import dataclass,field
import logging,threading
from time import monotonic
logger=logging.getLogger(__name__)
@dataclass
class MockAccessController:
    available:bool=True;unlocks:list[tuple[str,float,float]]=field(default_factory=list)
    def unlock(self,identity_id,duration_seconds):
        if not self.available:logger.warning('mock_unlock_rejected hardware_available=false');return False
        self.unlocks.append((identity_id,float(duration_seconds),monotonic()));logger.info('mock_unlock_accepted duration_seconds=%.2f',duration_seconds);return True
class GPIOAccessController:
    def __init__(self,pin,active_high=True,relay_factory=None):
        self._lock=threading.Lock();self._timer=None
        try:
            if relay_factory is None:
                from gpiozero import OutputDevice
                relay_factory=OutputDevice
            self._relay=relay_factory(int(pin),active_high=active_high,initial_value=False)
        except Exception as exc:self._relay=None;self._error=str(exc);logger.error('GPIO access controller unavailable: %s',exc)
    @property
    def available(self):return self._relay is not None
    def unlock(self,identity_id,duration_seconds):
        del identity_id
        if self._relay is None:logger.error('gpio_unlock_rejected hardware_available=false');return False
        with self._lock:
            if self._timer and self._timer.is_alive():logger.warning('gpio_unlock_rejected relay_already_active=true');return False
            self._relay.on();self._timer=threading.Timer(max(.1,float(duration_seconds)),self._lock_relay);self._timer.daemon=True;self._timer.start();logger.info('gpio_unlock_accepted duration_seconds=%.2f',duration_seconds);return True
    def _lock_relay(self):
        with self._lock:
            if self._relay:self._relay.off()
    def close(self):
        with self._lock:
            if self._timer:self._timer.cancel()
            if self._relay:self._relay.off();self._relay.close()