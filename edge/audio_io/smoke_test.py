"""No-JWT smoke test for edge audio I/O and cloud chatbot reachability."""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Iterable
from pathlib import Path

import requests

try:
    from .audio_player import AudioPlaybackError, AudioPlayer
    from .cloud_client import CloudChatClient, CloudClientError
    from .config import AudioIOConfig
    from .download_models import ModelSetupError, ensure_assets
    from .recorder import SpeechRecorder
    from .stt_whisper import WhisperCppTranscriber
    from .tts_piper import PiperTTS, PiperTTSError
    from .wake_word import WakeWordDetector
except ImportError:  # Allows `python edge/audio_io/smoke_test.py` from repo root.
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
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run edge audio and chatbot smoke checks without a JWT token."
    )
    parser.add_argument(
        "--query",
        default="What can you help me with?",
        help="Question used for the unauthenticated chatbot stream attempt.",
    )
    parser.add_argument(
        "--tts-text",
        default="Edge audio smoke test.",
        help="Text to synthesize and optionally play locally.",
    )
    parser.add_argument(
        "--setup-assets",
        action="store_true",
        help="Download or prepare audio assets before checks. Disabled by default.",
    )
    parser.add_argument("--skip-tts", action="store_true", help="Skip Piper TTS synthesis check")
    parser.add_argument("--skip-playback", action="store_true", help="Do not play the synthesized TTS WAV")
    parser.add_argument(
        "--record-stt",
        action="store_true",
        help="Record one utterance immediately and transcribe it with whisper.cpp",
    )
    parser.add_argument(
        "--wake-word",
        action="store_true",
        help="Listen for the configured wake word before continuing",
    )
    parser.add_argument(
        "--wake-timeout-seconds",
        type=float,
        default=20.0,
        help="Maximum wait time for --wake-word",
    )
    parser.add_argument("--skip-cloud", action="store_true", help="Skip cloud chatbot checks")
    parser.add_argument(
        "--public-rag-smoke",
        action="store_true",
        help="Call /api/chatbot/chat/public-smoke-test/stream instead of the protected stream endpoint.",
    )
    parser.add_argument(
        "--require-unauth-chat-success",
        action="store_true",
        help="Return failure if the cloud rejects the no-JWT chat request with 401/403.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    config = AudioIOConfig(cloud_bearer_token=None, cloud_session_id=None, cloud_retries=0)
    failures: list[str] = []
    warnings: list[str] = []

    print("Edge audio/chatbot no-JWT smoke test")
    print(f"Cloud stream URL: {config.cloud_api_url}")
    print(f"Device ID: {config.cloud_device_id}")

    if args.setup_assets:
        _run_step("asset setup", failures, lambda: _setup_assets(config))
    else:
        print("[SKIP] asset setup (pass --setup-assets to download/prepare models)")

    if args.wake_word:
        _run_step(
            "wake word",
            failures,
            lambda: _check_wake_word(config, args.wake_timeout_seconds),
        )

    if not args.skip_tts:
        _run_step(
            "tts/playback",
            failures,
            lambda: _check_tts(config, args.tts_text, play=not args.skip_playback),
        )

    if args.record_stt:
        _run_step("recording/stt", failures, lambda: _check_recording_stt(config))

    if not args.skip_cloud:
        _run_step("chatbot health", failures, lambda: _check_chatbot_health(config))
        _run_step(
            "chatbot stream without jwt",
            failures,
            lambda: _check_unauthenticated_chat(
                config,
                args.query,
                warnings,
                args.require_unauth_chat_success,
                args.public_rag_smoke,
            ),
        )

    _print_summary(failures, warnings)
    raise SystemExit(1 if failures else 0)


def _run_step(name: str, failures: list[str], action) -> None:
    print(f"[RUN ] {name}")
    try:
        action()
    except Exception as exc:
        failures.append(f"{name}: {exc}")
        print(f"[FAIL] {name}: {exc}")
    else:
        print(f"[OK  ] {name}")


def _setup_assets(config: AudioIOConfig) -> None:
    try:
        results = ensure_assets(config)
    except ModelSetupError:
        raise
    for result in results:
        path = str(result.path) if result.path else "package-managed"
        print(f"       asset ready: {result.name} ({path})")


def _check_wake_word(config: AudioIOConfig, timeout_seconds: float) -> None:
    detector = WakeWordDetector(config)
    stop_event = threading.Event()
    timer = threading.Timer(timeout_seconds, stop_event.set)
    timer.start()
    try:
        event = detector.wait_for_wake_word(stop_event)
    finally:
        timer.cancel()
    if event is None:
        raise RuntimeError(f"wake word not detected within {timeout_seconds:.1f}s")
    print(f"       detected {event.name} score={event.score:.3f}")


def _check_tts(config: AudioIOConfig, text: str, play: bool) -> None:
    path: Path | None = None
    try:
        path = PiperTTS(config).synthesize(text)
        print(f"       synthesized: {path}")
        if play:
            AudioPlayer(config).play(path)
    except (PiperTTSError, AudioPlaybackError):
        raise
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def _check_recording_stt(config: AudioIOConfig) -> None:
    recorder = SpeechRecorder(config)
    transcriber = WhisperCppTranscriber(config)
    recording_path: Path | None = None
    try:
        recording = recorder.record()
        recording_path = recording.path
        transcript = transcriber.transcribe(recording.path)
    finally:
        if recording_path is not None:
            recording_path.unlink(missing_ok=True)
    if not transcript:
        raise RuntimeError("recording completed but whisper returned an empty transcript")
    print(f"       transcript: {transcript}")


def _check_chatbot_health(config: AudioIOConfig) -> None:
    health_url = f"{_cloud_base_url(config.cloud_api_url)}/api/chatbot/health"
    response = requests.get(
        health_url,
        timeout=(config.cloud_connect_timeout_seconds, config.cloud_read_timeout_seconds),
    )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text.strip() or 'no details'}")
    print(f"       health: {response.json()}")


def _check_unauthenticated_chat(
    config: AudioIOConfig,
    query: str,
    warnings: list[str],
    require_success: bool,
    public_smoke: bool,
) -> None:
    chat_config = config
    if public_smoke:
        chat_config = AudioIOConfig(
            cloud_api_url=f"{_cloud_base_url(config.cloud_api_url)}/api/chatbot/chat/public-smoke-test/stream",
            cloud_bearer_token=None,
            cloud_session_id=None,
            cloud_device_id=config.cloud_device_id,
            cloud_retries=0,
        )
        print(f"       public smoke URL: {chat_config.cloud_api_url}")

    client = CloudChatClient(chat_config)
    chunks: list[str] = []
    try:
        chunks.extend(client.stream_chat(query))
    except CloudClientError as exc:
        if public_smoke and exc.status_code == 404:
            raise RuntimeError(
                "public RAG smoke endpoint is disabled or missing. "
                "Set RAG_ENABLE_PUBLIC_SMOKE_TEST=1 on the cloud backend and restart it."
            ) from exc
        if exc.status_code in {401, 403} and not require_success:
            message = (
                "cloud chatbot is reachable but requires JWT for full RAG queries; "
                "this is expected unless a public smoke-test endpoint is enabled."
            )
            warnings.append(message)
            print(f"       auth required: {exc}")
            return
        raise

    print_streamed_text(chunks)
    if client.last_response is not None:
        print(f"       response metadata: {client.last_response}")


def print_streamed_text(chunks: Iterable[str]) -> None:
    text = " ".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
    if not text:
        raise RuntimeError("chatbot stream completed with no text chunks")
    print(f"       answer: {text}")


def _cloud_base_url(stream_url: str) -> str:
    marker = "/api/chatbot/chat/stream"
    url = stream_url.rstrip("/")
    if url.endswith(marker):
        return url[: -len(marker)]
    if "/api/" in url:
        return url.split("/api/", 1)[0]
    return url


def _print_summary(failures: list[str], warnings: list[str]) -> None:
    print()
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
    else:
        print("Smoke test completed.")


if __name__ == "__main__":
    main()
