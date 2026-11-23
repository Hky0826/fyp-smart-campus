import pytest
from unittest.mock import MagicMock, patch

from access_control.audio_io.cloud_audio_client import (
    AudioResponseData,
    CloudAudioClient,
    CloudAudioClientError,
    CloudChatCredentials,
)
from access_control.audio_io.config import AudioIOConfig


def test_cloud_audio_client_credentials_coercion():
    config = AudioIOConfig(
        cloud_api_url="https://127.0.0.1:8000/api/chatbot/chat/audio",
        cloud_stream_api_url="https://127.0.0.1:8000/api/chatbot/chat/audio/stream",
        cloud_bearer_token="default_tok",
        cloud_session_id=10,
    )
    client = CloudAudioClient(config=config)

    creds = client._credentials()
    assert creds.bearer_token == "default_tok"
    assert creds.session_id == 10

    # Coerce dict
    dict_creds = client._coerce_credentials({"bearer_token": "dict_tok", "session_id": "20"})
    assert dict_creds.bearer_token == "dict_tok"
    assert dict_creds.session_id == 20

    # Coerce string
    str_creds = client._coerce_credentials("raw_token")
    assert str_creds.bearer_token == "raw_token"
    assert str_creds.session_id is None


def test_cloud_audio_client_error_formatting():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"detail": "Invalid WAV header"}
    msg = CloudAudioClient._error_message(mock_resp)
    assert "HTTP 400: Invalid WAV header" in msg
