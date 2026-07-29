from access_control.ui.access_control_gui.controllers.chatbot_controller import _has_voice


def test_silent_recording_is_not_sent_to_cloud():
    assert not _has_voice({"rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0})


def test_voice_recording_passes_audio_guard():
    assert _has_voice({"rms": 800.0, "peak": 2400.0, "voiced_ratio": 0.25})
