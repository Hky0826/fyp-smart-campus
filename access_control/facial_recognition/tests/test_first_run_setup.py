from pathlib import Path

from access_control.facial_recognition.src.api import main as edge_api
from access_control.facial_recognition.src.config import AccessControlConfig, default_cloud_url, detect_local_ip
from access_control.facial_recognition.src.face.database import DeviceUserRepository


def test_first_run_initializes_sqlite_without_environment_configuration(tmp_path: Path):
    database_path = tmp_path / "device_local.db"
    config = AccessControlConfig(
        database_path=database_path,
        sync_cloud_url="http://127.0.0.1:8000",
        allow_insecure_loopback=True,
    )

    assert edge_api._setup_is_pending(config)
    edge_api._ensure_local_database(config)

    assert database_path.is_file()
    assert DeviceUserRepository(database_path).get_status()["ok"] is True


def test_setup_status_returns_operator_instructions(monkeypatch, tmp_path: Path):
    config = AccessControlConfig(
        database_path=tmp_path / "device_local.db",
        sync_cloud_url="http://127.0.0.1:8000",
        allow_insecure_loopback=True,
    )
    monkeypatch.setattr(edge_api, "access_config", lambda: config)

    status = edge_api.setup_status()

    assert status["first_time_setup"] is True
    assert status["database_initialized"] is True
    assert any("SQLite" in instruction for instruction in status["instructions"])
    assert any("Device ID blank" in instruction for instruction in status["instructions"])


def test_stale_setup_marker_without_secret_keeps_setup_pending(tmp_path: Path):
    config = AccessControlConfig(database_path=tmp_path / "device_local.db", sync_device_secret="")
    edge_api._ensure_local_database(config)
    config.setup_marker_path.write_text("old-setup", encoding="utf-8")

    assert edge_api._setup_is_pending(config)


def test_development_defaults_allow_local_first_run_without_env(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("EDGE_ALLOW_INSECURE_LOOPBACK", raising=False)

    config = AccessControlConfig()

    assert default_cloud_url() == "https://127.0.0.1:8000"
    assert AccessControlConfig.__dataclass_fields__["allow_insecure_loopback"].default is True


def test_detect_local_ip_has_safe_loopback_fallback(monkeypatch):
    monkeypatch.setattr("socket.socket", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("socket.gethostbyname", lambda *_args: "127.0.0.1")

    assert detect_local_ip("http://192.168.1.25:8000") == "127.0.0.1"


def test_runtime_config_rebuild_reads_remote_sync_values(monkeypatch):
    monkeypatch.setenv("EDGE_SYNC_CLOUD_URL", "https://cloud.example.test")
    monkeypatch.setenv("EDGE_SYNC_DEVICE_ID", "edge-1")
    monkeypatch.setenv("EDGE_SYNC_DEVICE_SECRET", "secret")
    monkeypatch.setenv("EDGE_SYNC_LOCAL_IP", "192.168.1.50")
    monkeypatch.setenv("EDGE_REMOTE_API_ENABLED", "true")

    edge_api.access_config.cache_clear()
    edge_api.runtime_config.cache_clear()
    try:
        access_config = edge_api.access_config()
        runtime_config = edge_api.runtime_config()

        assert access_config.remote_api_enabled is True
        assert access_config.sync_local_ip == "192.168.1.50"
        assert runtime_config.remote_api_enabled is True
        assert runtime_config.sync_local_ip == "192.168.1.50"
    finally:
        edge_api.access_config.cache_clear()
        edge_api.runtime_config.cache_clear()
