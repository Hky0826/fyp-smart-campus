"""Wake word detection using openWakeWord."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Event

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WakeWordEvent:
    """A wake word detection event."""

    name: str
    score: float
    detected_at: float


class WakeWordDetector:
    """Continuously listen for a configured openWakeWord trigger."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError("openwakeword is not installed. Install edge/audio_io/requirements.txt first.") from exc

        if self.config.wake_word_model_path.exists():
            wakeword_models = [str(self.config.wake_word_model_path)]
        else:
            wakeword_models = [self.config.wake_word_name]

        self._model = Model(wakeword_models=wakeword_models, inference_framework="onnx")
        logger.info("Loaded openWakeWord model(s): %s", wakeword_models)
        return self._model

    def wait_for_wake_word(self, stop_event: Event | None = None) -> WakeWordEvent | None:
        """Block until a wake word is detected or a stop event is set."""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice and numpy are required for wake word detection.") from exc

        model = self._load_model()
        blocksize = max(1, int(self.config.sample_rate * self.config.wake_word_frame_ms / 1000))
        logger.info("Listening for wake word '%s'", self.config.wake_word_name)

        with sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            device=self.config.microphone_device,
        ) as stream:
            while stop_event is None or not stop_event.is_set():
                samples, overflowed = stream.read(blocksize)
                if overflowed:
                    logger.warning("Wake word audio input overflowed")
                flattened = np.asarray(samples, dtype=np.int16).reshape(-1)
                prediction = model.predict(flattened)
                name, score = self._best_prediction(prediction)
                if score >= self.config.wake_word_threshold:
                    logger.info("Wake word detected: %s score=%.3f", name, score)
                    time.sleep(self.config.wake_word_cooldown_seconds)
                    return WakeWordEvent(name=name, score=score, detected_at=time.time())

        return None

    @staticmethod
    def _best_prediction(prediction) -> tuple[str, float]:
        if isinstance(prediction, dict) and prediction:
            name, score = max(prediction.items(), key=lambda item: float(item[1]))
            return str(name), float(score)
        return "unknown", 0.0
