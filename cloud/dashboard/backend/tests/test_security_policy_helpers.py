from cloud.sync.callback_security import validate_callback_url

import pytest


def test_callback_requires_https_and_blocks_reserved_addresses():
    with pytest.raises(ValueError):
        validate_callback_url("http://192.0.2.10:8001")
    with pytest.raises(ValueError):
        validate_callback_url("https://127.0.0.1:8001")
    assert validate_callback_url("https://10.0.0.10:8001", allowed_cidrs=("10.0.0.0/8",))
