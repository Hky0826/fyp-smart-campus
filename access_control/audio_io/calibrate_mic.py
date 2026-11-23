"""Interactive microphone calibration script for Edge Live duplex voice kiosk.

Measures ambient noise floor and user speech levels to recommend optimal
near-field proximity VAD and adaptive barge-in threshold values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

try:
    from scipy.signal import butter, sosfilt, sosfilt_zi
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


def _record_rms_samples(
    duration_sec: float,
    sample_rate: int = 16000,
    block_size: int = 1600,
    device: str | int | None = None,
) -> list[float]:
    """Record microphone audio for duration_sec and return a list of block RMS values."""
    rms_values: list[float] = []

    sos = None
    zi = None
    if _SCIPY_AVAILABLE:
        try:
            sos = butter(2, 150.0, btype="highpass", fs=sample_rate, output="sos")
            zi = sosfilt_zi(sos)
        except Exception:
            sos = None
            zi = None

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        nonlocal zi
        samples = indata[:, 0].astype(np.float32)
        if samples.size == 0:
            return
        if _SCIPY_AVAILABLE and sos is not None and zi is not None:
            try:
                filtered, zi = sosfilt(sos, samples, zi=zi)
                rms = float(np.sqrt(np.mean(filtered * filtered)))
                rms_values.append(rms)
                return
            except Exception:
                pass
        rms = float(np.sqrt(np.mean(samples * samples)))
        rms_values.append(rms)

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=block_size,
        device=device,
        callback=callback,
    ):
        time.sleep(duration_sec)

    return rms_values


def run_calibration(
    duration: float = 5.0,
    device: str | int | None = None,
    save_path: Path | None = None,
    interactive: bool = True,
) -> dict[str, float]:
    """Run two-phase calibration: ambient noise and active speech."""
    print("=" * 60)
    print("  Kiosk Microphone Calibration Tool")
    print("=" * 60)
    print(f"Sample Rate: 16,000 Hz | High-Pass Filter: 150 Hz Butterworth")
    print(f"Sampling Duration per Phase: {duration:.1f} seconds")
    if device is not None:
        print(f"Microphone Device: {device}")
    print("-" * 60)

    # Phase 1: Ambient Noise Floor
    if interactive:
        input("\n[Phase 1] Remain SILENT. Normal background noise should be present.\nPress Enter when ready to sample ambient noise...")
    else:
        print("\n[Phase 1] Sampling ambient noise floor...")

    print(f"Sampling ambient noise for {duration:.1f}s...")
    ambient_rms = _record_rms_samples(duration, device=device)
    if not ambient_rms:
        ambient_rms = [100.0]

    ambient_mean = float(np.mean(ambient_rms))
    ambient_p95 = float(np.percentile(ambient_rms, 95))
    ambient_max = float(np.max(ambient_rms))

    print(f"  Ambient Mean RMS : {ambient_mean:.1f}")
    print(f"  Ambient 95th %ile: {ambient_p95:.1f}")
    print(f"  Ambient Peak RMS : {ambient_max:.1f}")

    # Phase 2: User Speech
    if interactive:
        input("\n[Phase 2] Speak naturally at normal kiosk distance (~30-60cm):\n  'Where can I find the student library?'\nPress Enter and begin speaking...")
    else:
        print("\n[Phase 2] Sampling speech...")

    print(f"Sampling speech for {duration:.1f}s...")
    speech_rms = _record_rms_samples(duration, device=device)
    if not speech_rms:
        speech_rms = [800.0]

    speech_mean = float(np.mean(speech_rms))
    speech_p95 = float(np.percentile(speech_rms, 95))
    speech_max = float(np.max(speech_rms))

    print(f"  Speech Mean RMS  : {speech_mean:.1f}")
    print(f"  Speech 95th %ile : {speech_p95:.1f}")
    print(f"  Speech Peak RMS  : {speech_max:.1f}")

    # Calculations
    # Proximity speech threshold: safely above ambient 95th percentile, but below speech mean
    recommended_speech_thresh = max(ambient_p95 + 150.0, ambient_p95 * 1.5, 300.0)
    if speech_mean > recommended_speech_thresh:
        recommended_speech_thresh = (recommended_speech_thresh + speech_mean * 0.5) / 2.0
    recommended_speech_thresh = round(recommended_speech_thresh, 1)

    recommended_barge_thresh = max(speech_mean * 1.4, 1150.0)
    recommended_barge_thresh = round(recommended_barge_thresh, 1)

    recommended_cooling_off = 400.0
    recommended_silence_hold = 0.70
    recommended_barge_ratio = 1.40

    print("\n" + "=" * 60)
    print("  RECOMMENDED LIVE DUPLEX CONFIGURATION")
    print("=" * 60)
    print(f"  speech_threshold_rms       : {recommended_speech_thresh}")
    print(f"  barge_in_threshold_rms     : {recommended_barge_thresh}")
    print(f"  cooling_off_ms             : {recommended_cooling_off}")
    print(f"  silence_hold_sec           : {recommended_silence_hold}")
    print(f"  barge_ratio                : {recommended_barge_ratio}")
    print("=" * 60)

    config_data = {
        "speech_threshold_rms": recommended_speech_thresh,
        "barge_in_threshold_rms": recommended_barge_thresh,
        "cooling_off_ms": recommended_cooling_off,
        "silence_hold_sec": recommended_silence_hold,
        "barge_ratio": recommended_barge_ratio,
        "ambient_noise_mean_rms": round(ambient_mean, 1),
        "ambient_noise_p95_rms": round(ambient_p95, 1),
        "speech_mean_rms": round(speech_mean, 1),
    }

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        print(f"\nSaved calibrated configuration to: {save_path.resolve()}")

    return config_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Microphone calibration tool for kiosk hands-free duplex voice.")
    parser.add_argument("--duration", type=float, default=5.0, help="Sampling duration per phase (default: 5.0s)")
    parser.add_argument("--device", type=str, default=None, help="Audio input device name or index")
    parser.add_argument("--save", type=str, default="vad_config.json", help="Path to save config JSON (default: vad_config.json)")
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive / automated mode")
    args = parser.parse_args()

    device = int(args.device) if args.device and args.device.isdigit() else args.device
    save_path = Path(args.save) if args.save else None

    run_calibration(
        duration=args.duration,
        device=device,
        save_path=save_path,
        interactive=not args.non_interactive,
    )


if __name__ == "__main__":
    main()
