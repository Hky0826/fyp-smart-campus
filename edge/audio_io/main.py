"""Run the local audio interaction pipeline on the edge device."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from threading import Event

try:
    from .audio_player import AudioPlaybackError, AudioPlayer
    from .cloud_client import CloudChatClient, CloudClientError
    from .config import AudioIOConfig
    from .download_models import ModelSetupError, ensure_assets
    from .recorder import SpeechRecorder
    from .stt_whisper import WhisperCppTranscriber
    from .tts_piper import PiperTTS, PiperTTSError
    from .wake_word import WakeWordDetector
except ImportError:  # Allows `python edge/audio_io/main.py` from repo root.
    from audio_player import AudioPlaybackError, AudioPlayer
    from cloud_client import CloudChatClient, CloudClientError
    from config import AudioIOConfig
    from download_models import ModelSetupError, ensure_assets
    from recorder import SpeechRecorder
    from stt_whisper import WhisperCppTranscriber
    from tts_piper import PiperTTS, PiperTTSError
    from wake_word import WakeWordDetector


logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    """Configure structured process logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


class AudioInteractionPipeline:
    """Coordinate one wake-record-transcribe-chat-speak interaction loop."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()
        self.wake_word = WakeWordDetector(self.config)
        self.recorder = SpeechRecorder(self.config)
        self.transcriber = WhisperCppTranscriber(self.config)
        self.cloud = CloudChatClient(self.config)
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

    def run_forever(self, stop_event: Event | None = None, skip_wake_word: bool = False, once: bool = False) -> None:
        """Run the audio pipeline until interrupted or a stop event is set."""
        self.prepare_assets()
        logger.info("Audio I/O pipeline started")

        while stop_event is None or not stop_event.is_set():
            if not skip_wake_word:
                event = self.wake_word.wait_for_wake_word(stop_event)
                if event is None:
                    break
            self.handle_interaction()
            if once:
                break

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
            logger.info("No speech text detected; returning to wake word listening")
            return

        logger.info("User transcript: %s", transcript)
        try:
            response_chunks = self.cloud.stream_chat(transcript)
            for audio_path in self.tts.synthesize_stream(response_chunks):
                self.player.play_and_cleanup(audio_path)
        except (CloudClientError, PiperTTSError, AudioPlaybackError) as exc:
            logger.error("Audio interaction failed: %s", exc)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for local testing and runtime use."""
    parser = argparse.ArgumentParser(description="Run the edge local audio I/O pipeline")
    parser.add_argument("--once", action="store_true", help="Run one interaction and exit")
    parser.add_argument("--skip-wake-word", action="store_true", help="Record immediately instead of waiting for wake word")
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
        pipeline.run_forever(skip_wake_word=args.skip_wake_word, once=args.once)
    except KeyboardInterrupt:
        logger.info("Audio I/O pipeline stopped by user")
    except ModelSetupError as exc:
        logger.error("Model setup failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
