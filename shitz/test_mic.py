"""
Interactive Microphone Diagnostic & Auto-Tuning Calibration Tool.
Automatically tunes RMS energy & dB thresholds for your room noise & speech levels,
and saves the calibrated settings for the live voice assistant.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sounddevice as sd
import numpy as np

CONFIG_PATH = SCRIPT_DIR / "vad_config.json"


def calculate_rms(pcm_data: np.ndarray) -> float:
    """Calculate Root Mean Square (RMS) energy level of audio frames."""
    if pcm_data.size == 0:
        return 0.0
    pcm_float = pcm_data.astype(np.float32)
    return float(np.sqrt(np.mean(pcm_float ** 2)))


def calculate_db(rms: float) -> float:
    """Convert RMS to decibels relative to full scale (dBFS)."""
    if rms <= 1e-6:
        return -90.0
    # 32768 is max amplitude for 16-bit PCM
    db = 20 * math.log10(rms / 32768.0)
    return max(-90.0, db)


def auto_tune_microphone(sample_rate: int = 16000) -> dict:
    """
    Automatically calibrate ambient room noise floor and active speech levels.
    Calculates optimal RMS threshold and saves to vad_config.json.
    """
    print("\n" + "=" * 65)
    print("AUTOMATIC MICROPHONE & VAD AUTO-TUNING WIZARD")
    print("=" * 65)

    # ── Step 1: Ambient Room Noise Floor ──────────────────────────────────────
    noise_duration = 3.0
    print(f"\n[Step 1/2] Measuring Ambient Room Noise...")
    print(f">>> Please stay SILENT and quiet for {noise_duration} seconds...")
    for i in range(3, 0, -1):
        print(f"    Starting in {i}...", end="\r", flush=True)
        time.sleep(1)
    print("    [Measuring Room Silence Now] " + "." * 15, flush=True)

    noise_audio = sd.rec(int(noise_duration * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()

    # Split noise into 100ms chunks to evaluate noise peaks
    chunk_size = int(sample_rate * 0.1)
    noise_chunks = [noise_audio[i:i+chunk_size] for i in range(0, len(noise_audio), chunk_size) if len(noise_audio[i:i+chunk_size]) == chunk_size]
    noise_rms_list = [calculate_rms(c) for c in noise_chunks]
    
    noise_mean_rms = float(np.mean(noise_rms_list))
    noise_max_rms = float(np.max(noise_rms_list))
    noise_db = calculate_db(noise_mean_rms)

    print(f"  ✓ Noise Floor Measured:")
    print(f"    - Ambient Mean RMS: {noise_mean_rms:.1f} ({noise_db:.1f} dBFS)")
    print(f"    - Ambient Peak RMS: {noise_max_rms:.1f}")

    # ── Step 2: Active Speech Level ───────────────────────────────────────────
    speech_duration = 4.0
    print(f"\n[Step 2/2] Measuring Your Active Speech...")
    print(f">>> Press ENTER, then speak a normal sentence (e.g., 'Hello, tell me about QIU'):")
    input()

    print(f"    [Recording Speech Now - Speak Naturally] " + "." * 15, flush=True)
    speech_audio = sd.rec(int(speech_duration * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()

    speech_chunks = [speech_audio[i:i+chunk_size] for i in range(0, len(speech_audio), chunk_size) if len(speech_audio[i:i+chunk_size]) == chunk_size]
    speech_rms_list = [calculate_rms(c) for c in speech_chunks]
    
    # Filter top 50% loudest chunks to represent active speaking periods
    sorted_speech_rms = sorted(speech_rms_list, reverse=True)
    top_speech_rms = sorted_speech_rms[:max(1, len(sorted_speech_rms) // 2)]
    
    speech_mean_rms = float(np.mean(top_speech_rms))
    speech_peak_rms = float(np.max(speech_rms_list))
    speech_db = calculate_db(speech_mean_rms)

    print(f"  ✓ Speech Energy Measured:")
    print(f"    - Speech Mean RMS:  {speech_mean_rms:.1f} ({speech_db:.1f} dBFS)")
    print(f"    - Speech Peak RMS:  {speech_peak_rms:.1f}")

    # ── Step 3: Optimal Threshold Calculation ─────────────────────────────────
    snr_ratio = speech_mean_rms / max(1.0, noise_max_rms)
    print(f"\n[Calibration Analysis]")
    print(f"  - Signal-to-Noise Ratio (SNR): {snr_ratio:.1f}x")

    # Optimal threshold is placed above ambient peak noise with a margin towards speech
    if speech_mean_rms <= noise_max_rms * 1.2:
        print("  [Warning] Speech level is very close to background noise. Setting sensitive threshold.")
        tuned_threshold_rms = max(100.0, noise_max_rms * 1.5)
    else:
        # Place threshold at 30% between noise peak and speech mean
        tuned_threshold_rms = noise_max_rms + (speech_mean_rms - noise_max_rms) * 0.30

    tuned_threshold_rms = float(round(max(80.0, min(1500.0, tuned_threshold_rms)), 1))
    tuned_threshold_db = float(round(calculate_db(tuned_threshold_rms), 1))

    config = {
        "ambient_noise_rms": round(noise_mean_rms, 1),
        "ambient_peak_rms": round(noise_max_rms, 1),
        "speech_mean_rms": round(speech_mean_rms, 1),
        "speech_peak_rms": round(speech_peak_rms, 1),
        "speech_threshold_rms": tuned_threshold_rms,
        "speech_threshold_db": tuned_threshold_db,
        "silence_duration_sec": 0.75,
    }

    # Save to vad_config.json
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print("\n" + "=" * 65)
    print("✓ AUTO-TUNING COMPLETE & SAVED TO vad_config.json!")
    print(f"  - Auto-Tuned Speech Threshold RMS: {tuned_threshold_rms:.1f}")
    print(f"  - Auto-Tuned Speech Threshold dB:  {tuned_threshold_db:.1f} dBFS")
    print(f"  - Silence Cutoff Delay:            {config['silence_duration_sec']} seconds")
    print("=" * 65)

    return config


def run_live_vad_monitor(duration_seconds: int = 10, sample_rate: int = 16000, threshold_rms: float = 300.0):
    """Real-time live ASCII volume VU meter using tuned threshold."""
    print(f"\n[Live Verification Meter] Testing tuned threshold (RMS > {threshold_rms:.0f}) for {duration_seconds}s:")
    print("Speak and pause to see real-time state detection:")
    
    block_size = int(sample_rate * 0.1)  # 100ms chunks
    start_time = time.time()

    def callback(indata, frames, time_info, status):
        rms = calculate_rms(indata)
        db = calculate_db(rms)
        peak = int(np.max(np.abs(indata)))

        norm_level = min(1.0, rms / 3000.0)
        bar_len = int(norm_level * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)

        is_speaking = rms >= threshold_rms
        state_label = ">> [SPEAKING]    " if is_speaking else "   [SILENCE]     "

        sys.stdout.write(f"\r{state_label} |{bar}| RMS:{int(rms):4d} ({db:5.1f} dB)")
        sys.stdout.flush()

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", blocksize=block_size, callback=callback):
        while time.time() - start_time < duration_seconds:
            time.sleep(0.05)

    print("\n")


def main():
    print("=" * 65)
    print("Smart Campus Microphone Auto-Tuner & VAD Calibrator")
    print("=" * 65)

    devices = sd.query_devices()
    default_input = sd.default.device[0]
    default_output = sd.default.device[1]

    print(f"Active Audio Devices:")
    print(f"  - Input  Mic: [{default_input}] {devices[default_input]['name']}")
    print(f"  - Output Spk: [{default_output}] {devices[default_output]['name']}")

    # 1. Run Auto-Tuning Wizard
    config = auto_tune_microphone()

    # 2. Live verification meter using the calibrated threshold
    run_live_vad_monitor(duration_seconds=8, threshold_rms=config["speech_threshold_rms"])

    print("\nCalibration finished! The live voice assistant will now automatically use these tuned settings.")


if __name__ == "__main__":
    main()
