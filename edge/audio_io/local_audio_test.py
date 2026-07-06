"""Local audio hardware test without chatbot or cloud requests."""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

try:
    from .audio_player import AudioPlaybackError, AudioPlayer
    from .config import AudioIOConfig
    from .download_models import ModelSetupError, ensure_assets
    from .keyboard_activation import SpacebarActivationDetector
    from .recorder import SpeechRecorder
    from .stt_whisper import WhisperCppTranscriber
    from .tts_piper import PiperTTS, PiperTTSError
except ImportError:  # Allows `python edge/audio_io/local_audio_test.py` from repo root.
    from audio_player import AudioPlaybackError, AudioPlayer
    from config import AudioIOConfig
    from download_models import ModelSetupError, ensure_assets
    from keyboard_activation import SpacebarActivationDetector
    from recorder import SpeechRecorder
    from stt_whisper import WhisperCppTranscriber
    from tts_piper import PiperTTS, PiperTTSError


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test local keyboard activation, microphone input, whisper.cpp STT, "
            "and Piper TTS without calling the chatbot or cloud."
        )
    )
    parser.add_argument(
        "--setup-assets",
        action="store_true",
        help="Download or prepare local STT and TTS assets before checks.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print PortAudio devices before running checks.",
    )
    parser.add_argument(
        "--microphone-device",
        default=None,
        type=_audio_device_arg,
        help="PortAudio microphone device name or index, used only with EDGE_AUDIO_RECORDING_BACKEND=sounddevice.",
    )
    parser.add_argument(
        "--alsa-capture-device",
        default=None,
        help="ALSA capture device for arecord, for example hw:1,0 or plughw:1,0.",
    )
    parser.add_argument(
        "--whisper-binary-path",
        type=Path,
        default=None,
        help="whisper.cpp CLI binary path used by this local test.",
    )
    parser.add_argument(
        "--tts-text",
        default="Edge audio local test. Press the space bar after this message.",
        help="Text to synthesize for the TTS check.",
    )
    parser.add_argument("--skip-tts", action="store_true", help="Skip Piper TTS synthesis")
    parser.add_argument("--skip-playback", action="store_true", help="Do not play the synthesized TTS WAV")
    parser.add_argument(
        "--skip-activation",
        action="store_true",
        help="Record immediately instead of waiting for the space bar.",
    )
    parser.add_argument(
        "--keep-audio-files",
        action="store_true",
        help="Keep generated TTS and microphone WAV files for manual inspection.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def _audio_device_arg(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    base_config = AudioIOConfig(cloud_bearer_token=None, cloud_session_id=None, cloud_retries=0)
    whisper_binary_path = args.whisper_binary_path or base_config.whisper_binary_path
    config = AudioIOConfig(
        cloud_bearer_token=None,
        cloud_session_id=None,
        cloud_retries=0,
        microphone_device=args.microphone_device,
        alsa_capture_device=args.alsa_capture_device or base_config.alsa_capture_device,
        whisper_binary_path=whisper_binary_path,
    )
    failures: list[str] = []

    print("Edge audio local hardware test")
    print("Cloud chatbot: disabled")
    print("Activation: space bar")
    print(f"Recording backend: {config.recording_backend}")
    print(f"ALSA capture device: {config.alsa_capture_device or 'default'}")
    print(f"PortAudio device: {config.microphone_device if config.microphone_device is not None else 'default'}")
    print(f"Sample rate: {config.sample_rate} Hz")
    print(f"Whisper binary: {config.whisper_binary_path}")

    if args.list_devices:
        _run_step("audio devices", failures, _list_audio_devices)

    if args.setup_assets:
        _run_step("asset setup", failures, lambda: _setup_assets(config))
    else:
        print("[SKIP] asset setup (pass --setup-assets to download/prepare models)")

    if not args.skip_tts:
        _run_step(
            "tts/playback",
            failures,
            lambda: _check_tts(
                config,
                args.tts_text,
                play=not args.skip_playback,
                keep_audio_files=args.keep_audio_files,
            ),
        )
    else:
        print("[SKIP] tts/playback")

    if not args.skip_activation:
        _run_step(
            "keyboard activation",
            failures,
            _check_keyboard_activation,
        )
    else:
        print("[SKIP] keyboard activation")

    _run_step(
        "microphone/stt",
        failures,
        lambda: _check_microphone_stt(config, keep_audio_files=args.keep_audio_files),
    )

    _print_summary(failures)
    raise SystemExit(1 if failures else 0)


def _run_step(name: str, failures: list[str], action: Callable[[], None]) -> None:
    print(f"[RUN ] {name}")
    try:
        action()
    except Exception as exc:
        failures.append(f"{name}: {exc}")
        print(f"[FAIL] {name}: {exc}")
    else:
        print(f"[OK  ] {name}")


def _list_audio_devices() -> None:
    if shutil.which("arecord") is None:
        raise RuntimeError("arecord is required to list ALSA capture devices. Install alsa-utils first.")
    result = subprocess.run(["arecord", "-l"], check=False, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "arecord -l failed")
    print(result.stdout)


def _setup_assets(config: AudioIOConfig) -> None:
    try:
        results = ensure_assets(config)
    except ModelSetupError:
        raise
    for result in results:
        path = str(result.path) if result.path else "package-managed"
        print(f"       asset ready: {result.name} ({path})")


def _check_tts(config: AudioIOConfig, text: str, play: bool, keep_audio_files: bool) -> None:
    path: Path | None = None
    try:
        path = PiperTTS(config).synthesize(text)
        print(f"       synthesized: {path}")
        if play:
            AudioPlayer(config).play(path)
    except (PiperTTSError, AudioPlaybackError):
        raise
    finally:
        if path is not None and not keep_audio_files:
            path.unlink(missing_ok=True)


def _check_keyboard_activation() -> None:
    print("       press SPACE to continue")
    event = SpacebarActivationDetector().wait_for_spacebar()
    if event is None:
        raise RuntimeError("space bar activation was not detected")
    print("       detected space bar activation")


def _check_microphone_stt(config: AudioIOConfig, keep_audio_files: bool) -> None:
    print("       speak a short sentence now; recording stops after silence")
    recorder = SpeechRecorder(config)
    transcriber = WhisperCppTranscriber(config)
    recording_path: Path | None = None
    try:
        recording = recorder.record()
        recording_path = recording.path
        print(f"       recorded: {recording.path} ({recording.duration_seconds:.2f}s)")
        if recording.path.stat().st_size <= 44:
            raise RuntimeError("recording completed but the WAV file contains no audio samples")
        transcript = transcriber.transcribe(recording.path)
    finally:
        if recording_path is not None and not keep_audio_files:
            recording_path.unlink(missing_ok=True)

    if not transcript:
        raise RuntimeError("recording completed but whisper returned an empty transcript")
    print(f"       transcript: {transcript}")


def _print_summary(failures: list[str]) -> None:
    print()
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
    else:
        print("Local audio hardware test completed.")


if __name__ == "__main__":
    main()
