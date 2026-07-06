"""Run the local audio interaction pipeline on the edge device."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event

try:
    from .audio_player import AudioPlaybackError, AudioPlayer
    from .cloud_client import CloudChatClient, CloudChatCredentials, CloudClientError
    from .config import AudioIOConfig
    from .download_models import ModelSetupError, ensure_assets
    from .keyboard_activation import SpacebarActivationDetector
    from .recorder import SpeechRecorder
    from .stt_whisper import WhisperCppTranscriber
    from .tts_piper import PiperTTS, PiperTTSError
except ImportError:  # Allows `python edge/audio_io/main.py` from repo root.
    from audio_player import AudioPlaybackError, AudioPlayer
    from cloud_client import CloudChatClient, CloudChatCredentials, CloudClientError
    from config import AudioIOConfig
    from download_models import ModelSetupError, ensure_assets
    from keyboard_activation import SpacebarActivationDetector
    from recorder import SpeechRecorder
    from stt_whisper import WhisperCppTranscriber
    from tts_piper import PiperTTS, PiperTTSError


logger = logging.getLogger(__name__)

_AUTH_PROMPT = "Please scan your face to continue."
_AUTH_CONFIRMED_PROMPT = "Access confirmed."
_AUTH_TIMEOUT_PROMPT = "Face verification timed out. Please try again."
_AUTH_DENIAL_MARKERS = (
    "access denied",
    "not authorized",
    "authentication required",
    "permission",
    "protected document",
    "scan your face",
    "above visitor",
    "higher access",
    "authenticate",
    "re-authenticate",
    "face recognition",
)


def configure_logging(level: str) -> None:
    """Configure structured process logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


class AudioInteractionPipeline:
    """Coordinate one activate-record-transcribe-chat-speak interaction loop."""

    def __init__(
        self,
        config: AudioIOConfig | None = None,
        credential_provider: Callable[[], CloudChatCredentials | dict | str | None] | None = None,
        auth_required_handler: Callable[[str], bool] | None = None,
        activation_event: Event | None = None,
    ) -> None:
        self.config = config or AudioIOConfig()
        self.auth_required_handler = auth_required_handler
        self.activation_event = activation_event
        self.keyboard_activation = SpacebarActivationDetector()
        self.recorder = SpeechRecorder(self.config)
        self.transcriber = WhisperCppTranscriber(self.config)
        self.cloud = CloudChatClient(self.config, credential_provider=credential_provider)
        self.tts = PiperTTS(self.config)
        self.player = AudioPlayer(self.config)

    def prepare_assets(self) -> None:
        """Download required models and binaries unless disabled by configuration."""
        if self.config.skip_model_setup:
            logger.info("Skipping model setup because EDGE_AUDIO_SKIP_MODEL_SETUP is enabled")
            return
        results = ensure_assets(self.config)
        for result in results:
            path = str(result.path) if result.path else "package-managed"
            logger.info("Asset ready: %s (%s)", result.name, path)

    def run_forever(
        self,
        stop_event: Event | None = None,
        skip_activation: bool = False,
        once: bool = False,
        skip_wake_word: bool | None = None,
    ) -> None:
        """Run the audio pipeline until interrupted or a stop event is set."""
        if skip_wake_word is not None:
            skip_activation = skip_wake_word
        self.prepare_assets()
        logger.info("Audio I/O pipeline started")

        while stop_event is None or not stop_event.is_set():
            if not skip_activation:
                if not self._wait_for_activation(stop_event):
                    break
            self.handle_interaction()
            if once:
                break

    def _wait_for_activation(self, stop_event: Event | None = None) -> bool:
        if self.activation_event is None:
            print("Press SPACE to activate the chatbot, or q to quit.", flush=True)
            event = self.keyboard_activation.wait_for_key({" ", "q"}, stop_event)
            if event is None:
                return False
            return event.key != "q"

        logger.info("Waiting for space bar activation from access-control display")
        while stop_event is None or not stop_event.is_set():
            if self.activation_event.wait(timeout=0.1):
                if stop_event is not None and stop_event.is_set():
                    return False
                self.activation_event.clear()
                return True
        return False

    def handle_interaction(self) -> None:
        """Handle one user utterance and speak the cloud chatbot response."""
        recording_path: Path | None = None
        try:
            recording = self.recorder.record()
            recording_path = recording.path
            transcript = self.transcriber.transcribe(recording.path)
        finally:
            if recording_path is not None:
                recording_path.unlink(missing_ok=True)

        if not transcript:
            logger.info("No speech text detected; returning to activation wait")
            return

        logger.info("User transcript: %s", transcript)
        try:
            response = self._chat_and_speak(transcript)
            if self._response_requires_authentication(response):
                self._retry_after_authentication(transcript)
        except (CloudClientError, PiperTTSError, AudioPlaybackError) as exc:
            if self._error_requires_authentication(exc):
                self._retry_after_authentication(transcript)
            else:
                logger.error("Audio interaction failed: %s", exc)

    def _chat_and_speak(self, transcript: str) -> dict | None:
        response_chunks = self.cloud.stream_chat(transcript)
        for audio_path in self.tts.synthesize_stream(response_chunks):
            self.player.play_and_cleanup(audio_path)
        return self.cloud.last_response

    def _retry_after_authentication(self, transcript: str) -> None:
        if self.auth_required_handler is None:
            logger.info("Cloud requires authentication, but no authentication handler is configured")
            return

        self.speak_text(_AUTH_PROMPT)
        if not self.auth_required_handler(transcript):
            self.speak_text(_AUTH_TIMEOUT_PROMPT)
            return

        self.speak_text(_AUTH_CONFIRMED_PROMPT)
        try:
            self._chat_and_speak(transcript)
        except (CloudClientError, PiperTTSError, AudioPlaybackError) as exc:
            logger.error("Authenticated audio retry failed: %s", exc)

    def speak_text(self, text: str) -> None:
        """Speak a short local status message without contacting the cloud."""
        try:
            audio_path = self.tts.synthesize(text)
            self.player.play_and_cleanup(audio_path)
        except (PiperTTSError, AudioPlaybackError) as exc:
            logger.warning("Could not play local prompt: %s", exc)

    @staticmethod
    def _response_requires_authentication(response: dict | None) -> bool:
        if not response or response.get("access_granted") is not False:
            return False
        combined = " ".join(
            str(response.get(key) or "")
            for key in ("status_message", "answer")
        ).lower()
        return any(marker in combined for marker in _AUTH_DENIAL_MARKERS)

    @staticmethod
    def _error_requires_authentication(exc: BaseException) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {401, 403}:
            return True
        message = str(exc).lower()
        return any(marker in message for marker in _AUTH_DENIAL_MARKERS)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for local testing and runtime use."""
    parser = argparse.ArgumentParser(description="Run the edge local audio I/O pipeline")
    parser.add_argument("--once", action="store_true", help="Run one interaction and exit")
    parser.add_argument(
        "--skip-activation",
        action="store_true",
        help="Record immediately instead of waiting for the space bar",
    )
    parser.add_argument(
        "--skip-wake-word",
        dest="skip_activation",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--skip-model-setup", action="store_true", help="Do not run download_models before startup")
    parser.add_argument("--log-level", default=None, help="Override EDGE_AUDIO_LOG_LEVEL")
    return parser.parse_args()


def main() -> None:
    """CLI entry point for the edge audio I/O pipeline."""
    args = parse_args()
    config = AudioIOConfig()
    if args.skip_model_setup:
        config = AudioIOConfig(skip_model_setup=True)

    configure_logging(args.log_level or config.log_level)
    pipeline = AudioInteractionPipeline(config)
    try:
        pipeline.run_forever(skip_activation=args.skip_activation, once=args.once)
    except KeyboardInterrupt:
        logger.info("Audio I/O pipeline stopped by user")
    except ModelSetupError as exc:
        logger.error("Model setup failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
