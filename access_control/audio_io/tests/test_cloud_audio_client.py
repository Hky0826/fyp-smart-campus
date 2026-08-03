import pytest

from access_control.audio_io.cloud_audio_client import LiveAudioClientError, LiveAudioSession


class _ClosedSocket:
    def __init__(self, code: int) -> None:
        self.code = code

    def recv(self, *, timeout: float):
        error = RuntimeError("socket closed")
        error.code = self.code
        raise error


def test_normal_socket_close_is_reported_as_incomplete_turn():
    session = LiveAudioSession("ws://localhost/chat/live")
    session._socket = _ClosedSocket(1000)

    events = list(session.receive_events())

    assert events == [{"event": "closed", "data": {"code": 1000}}]
    assert not session.connected


def test_abnormal_socket_close_remains_an_error_and_invalidates_session():
    session = LiveAudioSession("ws://localhost/chat/live")
    session._socket = _ClosedSocket(1006)

    with pytest.raises(LiveAudioClientError, match="receive failed"):
        list(session.receive_events())

    assert not session.connected
