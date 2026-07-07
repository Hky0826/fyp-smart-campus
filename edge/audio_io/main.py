"""Run the audio I/O pipeline on the edge device: record, send, receive, play."""

from __future__ import annotations

import argparse
import faulthandler
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event

try:
    from .audio_player import AudioPlaybackError, AudioPlayer
    from .cloud_audio_client import (
        CloudAudioClient,
        CloudAudioClientError,
        CloudChatCredentials,
    )
    from .config import AudioIOConfig
    from .keyboard_activation import SpacebarActivationDetector
    from .recorder import AudioRecorder, RecordingResult
except ImportError:  # Allows `python edge/audio_io/main.py` from repo root.
    from audio_player import AudioPlaybackError, AudioPlayer
    from cloud_audio_client import (
        CloudAudioClient,
        CloudAudioClientError,
        CloudChatCredentials,
    )
    from config import AudioIOConfig
    from keyboard_activation import SpacebarActivationDetector
    from recorder import AudioRecorder, RecordingResult


logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    """Configure structured process logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


class AudioInteractionPipeline:
    """Record audio -> send to cloud -> receive text+audio -> play audio.

    This is the core interaction loop for the edge device. It waits for
    keyboard activation (space bar), records audio, uploads it to the
    cloud chatbot API, and plays back the received audio response.
    """

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
        self.recorder = AudioRecorder(self.config)
        self.cloud = CloudAudioClient(self.config, credential_provider=credential_provider)
        self.player = AudioPlayer(self.config)

    def run_forever(
        self,
        stop_event: Event | None = None,
        skip_activation: bool = False,
        once: bool = False,
    ) -> None:
        """Run the audio pipeline until interrupted or a stop event is set.

        Args:
            stop_event: Optional threading.Event to signal shutdown.
            skip_activation: If True, start recording immediately.
            once: If True, run one interaction and exit.
        """
        logger.info("Audio I/O pipeline started")

        while stop_event is None or not stop_event.is_set():
            if not skip_activation:
                if not self._wait_for_activation(stop_event):
                    break
            self.handle_interaction()
            if once:
                break

    def handle_interaction(self) -> None:
        """Record, upload to cloud, receive response, and play audio.

        This method orchestrates one complete interaction cycle:
        1. Record audio from the microphone
        2. Upload the WAV to the cloud chatbot API
        3. Handle the response status
        4. Play back received audio if present
        """
        recording_path: Path | None = None
        try:
            # Step 1: Record audio
            recording = self.recorder.record()
            recording_path = recording.path
            logger.info("Recorded %.2fs of audio", recording.duration_seconds)

            # Step 2: Upload to cloud
            response = self.cloud.send_audio(recording_path)

            # Step 3: Handle response
            if response.status == "blocked":
                logger.info("Query blocked: %s", response.error_message or "potential injection detected")
                if response.text:
                    logger.info("Response text: %s", response.text)
                return

            if response.status == "auth_required":
                logger.info("Authentication required, triggering face auth flow")
                if self.auth_required_handler:
                    self._retry_after_authentication(recording_path)
                return

            if response.status == "no_access":
                logger.info("No relevant documents found for access level")
                if response.text:
                    logger.info("Response text: %s", response.text)
                return

            if response.status in ("ok", "validation_failed"):
                if response.text:
                    logger.info("Response text: %s", response.text)

                # Step 4: Play audio response if available
                if response.audio_bytes:
                    self.player.play_pcm(response.audio_bytes)
                elif response.text:
                    logger.info("No audio response to play (text-only response)")

                return

            if response.status == "error":
                logger.error("Cloud returned error: %s", response.error_message or "unknown error")
                return

        except CloudAudioClientError as exc:
            if exc.status_code in (401, 403) and self.auth_required_handler:
                self._retry_after_authentication(recording_path)
            else:
                logger.error("Cloud communication failed: %s", exc)
        except AudioPlaybackError as exc:
            logger.error("Audio playback failed: %s", exc)
        except RuntimeError as exc:
            logger.error("Audio interaction failed: %s", exc)
        finally:
            if recording_path is not None:
                recording_path.unlink(missing_ok=True)

    def _wait_for_activation(self, stop_event: Event | None = None) -> bool:
        """Wait for space bar press or external activation event.

        Returns:
            True if activation received, False if stop requested.
        """
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

    def _retry_after_authentication(self, recording_path: Path | None = None) -> None:
        """Retry the audio query after face authentication succeeds.

        Logs the authentication requirement and re-uploads the recorded
        audio after authentication completes.
        """
        if self.auth_required_handler is None:
            logger.info("Cloud requires authentication, but no authentication handler is configured")
            return

        logger.info("Authentication required — triggering face auth flow")
        # We can no longer do local TTS; just log and let the handler manage UI
        if recording_path and recording_path.exists():
            try:
                response = self.cloud.send_audio(recording_path)
                if response.audio_bytes:
                    self.player.play_pcm(response.audio_bytes)
                elif response.text:
                    logger.info("Authenticated response text: %s", response.text)
            except (CloudAudioClientError, AudioPlaybackError) as exc:
                logger.error("Authenticated retry failed: %s", exc)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for local testing and runtime use."""
    parser = argparse.ArgumentParser(description="Run the edge audio I/O pipeline")
    parser.add_argument("--once", action="store_true", help="Run one interaction and exit")
    parser.add_argument(
        "--skip-activation",
        action="store_true",
        help="Record immediately instead of waiting for the space bar",
    )
    parser.add_argument("--log-level", default=None, help="Override EDGE_AUDIO_LOG_LEVEL")
    return parser.parse_args()


def main() -> None:
    """CLI entry point for the edge audio I/O pipeline."""
    faulthandler.enable(all_threads=True)
    args = parse_args()
    config = AudioIOConfig()

    configure_logging(args.log_level or config.log_level)
    pipeline = AudioInteractionPipeline(config)
    try:
        pipeline.run_forever(skip_activation=args.skip_activation, once=args.once)
    except KeyboardInterrupt:
        logger.info("Audio I/O pipeline stopped by user")


if __name__ == "__main__":
    main()
