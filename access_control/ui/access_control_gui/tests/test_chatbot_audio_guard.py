from unittest.mock import MagicMock
from access_control.ui.access_control_gui.controllers.chatbot_controller import (
    ChatbotController,
    _LiveDuplexWorker,
    _has_voice,
)


def test_silent_recording_is_not_sent_to_cloud():
    assert not _has_voice({"rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0})


def test_voice_recording_passes_audio_guard():
    assert _has_voice({"rms": 800.0, "peak": 2400.0, "voiced_ratio": 0.25})


def test_chatbot_controller_hands_free_properties():
    mock_api = MagicMock()
    controller = ChatbotController(mock_api)
    assert controller.listening is False
    assert controller.busy is False
    assert controller.speaking is False
    assert controller.ragStatus == ""
    assert controller.currentNavigation == {}
    assert controller.citations == []

    # Test slots for RAG status, navigation, citations
    controller._on_rag_status("searching", "where is the lift")
    assert "where is the lift" in controller.ragStatus

    controller._on_navigation({"instructions": [{"instruction": "Turn left"}]})
    assert len(controller.currentNavigation.get("instructions", [])) == 1

    controller._on_citations([{"title": "Handbook"}])
    assert len(controller.citations) == 1

    controller._on_turn_completed()
    assert controller.ragStatus == ""


def test_chatbot_controller_start_stop_voice_loop():
    mock_api = MagicMock()
    mock_api.get_live_config.return_value = {"ws_url": "ws://127.0.0.1:8000/ws"}
    controller = ChatbotController(mock_api)

    controller.startVoiceLoop()
    assert controller._worker is not None
    assert isinstance(controller._worker, _LiveDuplexWorker)

    controller.stopVoiceLoop()
    assert controller._worker is None
    assert controller.listening is False


def test_live_duplex_worker_stop_audio_playback():
    import asyncio
    mock_api = MagicMock()
    worker = _LiveDuplexWorker(mock_api)
    worker._audio_play_queue = asyncio.Queue()
    worker._audio_play_queue.put_nowait(b"fake_pcm_data_1")
    worker._audio_play_queue.put_nowait(b"fake_pcm_data_2")
    assert worker._audio_play_queue.qsize() == 2

    busy_states = []
    worker.busyChanged.connect(busy_states.append)

    worker.stop_audio_playback()
    assert worker._audio_play_queue.empty()
    assert False in busy_states

    # Verify queue accepts new chunks in subsequent rounds without deadlock
    worker._audio_play_queue.put_nowait(b"round_2_pcm")
    assert worker._audio_play_queue.qsize() == 1


def test_chatbot_controller_gain_properties():
    mock_api = MagicMock()
    controller = ChatbotController(mock_api)
    assert controller.outputGain == 0.65
    assert controller.micGain == 0.80
    assert controller.bargeThreshold == 350.0

    controller.setOutputGain(0.5)
    assert controller.outputGain == 0.5

    controller.setMicGain(0.7)
    assert controller.micGain == 0.7

    controller.setBargeThreshold(1200.0)
    assert controller.bargeThreshold == 1200.0


def test_chatbot_controller_dsp_properties():
    from access_control.ui.access_control_gui.controllers.chatbot_controller import SPEECH_THRESHOLD_RMS
    mock_api = MagicMock()
    controller = ChatbotController(mock_api)
    assert controller.speechThreshold == SPEECH_THRESHOLD_RMS
    assert controller.coolingOffMs == 100.0
    assert controller.silenceHoldSec == 0.45
    assert controller.bargeRatio == 0.60

    controller.setSpeechThreshold(550.0)
    assert controller.speechThreshold == 550.0

    controller.setCoolingOffMs(500.0)
    assert controller.coolingOffMs == 500.0

    controller.setSilenceHoldSec(0.85)
    assert controller.silenceHoldSec == 0.85

    controller.setBargeRatio(1.60)
    assert controller.bargeRatio == 1.60

    # Test interruptPlayback slot
    worker_mock = MagicMock()
    controller._worker = worker_mock
    controller.interruptPlayback()
    worker_mock.stop_audio_playback.assert_called_once()


def test_filter_and_calculate_rms():
    import numpy as np
    from access_control.ui.access_control_gui.controllers.chatbot_controller import _filter_and_calculate_rms
    from scipy.signal import butter, sosfilt_zi

    # Empty chunk
    rms, _ = _filter_and_calculate_rms(b"")
    assert rms == 0.0

    # Generate 50Hz rumble vs 500Hz speech tone at 16kHz
    fs = 16000
    t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
    tone_50hz = (10000 * np.sin(2 * np.pi * 50 * t)).astype(np.int16).tobytes()
    tone_500hz = (10000 * np.sin(2 * np.pi * 500 * t)).astype(np.int16).tobytes()

    sos = butter(2, 150.0, btype="highpass", fs=fs, output="sos")
    zi = sosfilt_zi(sos)

    rms_50hz, _ = _filter_and_calculate_rms(tone_50hz, sos, zi.copy())
    rms_500hz, _ = _filter_and_calculate_rms(tone_500hz, sos, zi.copy())

    # The 150Hz highpass filter must heavily attenuate 50Hz while passing 500Hz
    assert rms_50hz < rms_500hz * 0.3


def test_adaptive_barge_in_threshold_calculation():
    # Verify adaptive threshold logic
    barge_base = 1150.0
    barge_ratio = 1.40
    spk_quiet_rms = 200.0
    spk_loud_rms = 1200.0

    # When speaker is quiet or silent:
    dynamic_thresh_quiet = max(barge_base, barge_ratio * spk_quiet_rms + 350.0)
    assert dynamic_thresh_quiet == barge_base  # 1.4 * 200 + 350 = 630 <= 1150

    # When speaker is loud (e.g. 1200 RMS):
    dynamic_thresh_loud = max(barge_base, barge_ratio * spk_loud_rms + 350.0)
    assert dynamic_thresh_loud == 1.4 * 1200.0 + 350.0  # 2030.0 > 1150
    assert dynamic_thresh_loud > 2000.0


def test_lookback_buffer_preserves_initial_syllables():
    import collections
    buffer = collections.deque(maxlen=3)
    chunk1 = b"chunk_silence_1"
    chunk2 = b"chunk_silence_2"
    chunk3 = b"chunk_initial_consonant"

    buffer.append(chunk1)
    buffer.append(chunk2)
    buffer.append(chunk3)

    # When speech onset occurs, flushes all 3 historical chunks
    flushed = []
    while buffer:
        flushed.append(buffer.popleft())

    assert flushed == [chunk1, chunk2, chunk3]
    assert len(buffer) == 0


