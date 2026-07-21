import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audio_io.access_feedback import AccessFeedbackPlayer, SOUND_DIR


def test_access_feedback_has_prerecorded_clips_for_final_modes():
    assert AccessFeedbackPlayer._CLIPS == {
        "access-granted": SOUND_DIR / "access_granted.wav",
        "access-denied": SOUND_DIR / "access_denied.wav",
    }
    assert all(Path(path).is_file() for path in AccessFeedbackPlayer._CLIPS.values())


def test_non_final_modes_do_not_start_playback():
    class FakePlayer:
        def play_wav(self, _path):
            raise AssertionError("non-final access modes must not play audio")

    feedback = AccessFeedbackPlayer(FakePlayer)
    feedback.play_for_mode("access-verifying")
    feedback.play_for_mode("idle")
    feedback.close()
