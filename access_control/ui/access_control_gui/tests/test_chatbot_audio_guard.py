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

