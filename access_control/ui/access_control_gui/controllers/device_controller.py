"""Device/setup status checks for the native kiosk UI."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot, Property

from .api_client import KioskApiClient


class _DeviceCheckWorker(QThread):
    success = Signal(dict)
    failure = Signal(str)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api

    def run(self) -> None:
        try:
            database = self._api.get_database_status()
            models = self._api.get_models_status()
            setup = self._api.get_setup_status()
            self.success.emit({"database": database, "models": models, "setup": setup})
        except Exception as exc:  # pragma: no cover - exercised in GUI runtime
            self.failure.emit(str(exc))


class DeviceController(QObject):
    setupChanged = Signal()
    errorChanged = Signal()

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._setup_required = False
        self._database_ok = True
        self._models_ok = True
        self._first_time_setup = False
        self._setup_device_id = ""
        self._setup_secret = ""
        self._setup_local_address = ""
        self._setup_detected_lan_address = ""
        self._setup_cloud_url = ""
        self._error = ""
        self._workers: list[QThread] = []

    @Slot()
    def refresh(self) -> None:
        worker = _DeviceCheckWorker(self._api)
        worker.success.connect(self._on_success)
        worker.failure.connect(self._on_failure)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    @Slot(dict)
    def _on_success(self, payload: dict[str, Any]) -> None:
        database = payload.get("database") or {}
        models = payload.get("models") or {}
        setup = payload.get("setup") or {}
        model_rows = models.get("models") or []
        self._database_ok = bool(database.get("ok", database.get("success", True)))
        self._models_ok = all(bool(row.get("exists")) for row in model_rows) if model_rows else True
        self._first_time_setup = bool(setup.get("first_time_setup", False))
        self._setup_device_id = str(setup.get("device_id") or "")
        self._setup_secret = str(setup.get("device_secret") or "")
        self._setup_local_address = str(setup.get("local_address") or "")
        self._setup_detected_lan_address = str(setup.get("detected_lan_address") or "")
        self._setup_cloud_url = str(setup.get("cloud_url") or "")
        self._setup_required = self._first_time_setup or not (self._database_ok and self._models_ok)
        self._error = ""
        self.setupChanged.emit()
        self.errorChanged.emit()

    @Slot(str)
    def _on_failure(self, message: str) -> None:
        self._error = message
        self.errorChanged.emit()

    @Slot()
    def completeSetup(self) -> None:
        try:
            self._api.complete_setup()
        except Exception as exc:  # pragma: no cover - exercised in GUI runtime
            self._error = str(exc)
            self.errorChanged.emit()
            return
        self._first_time_setup = False
        self._setup_secret = ""
        self._setup_required = not (self._database_ok and self._models_ok)
        self.setupChanged.emit()

    @Slot(str, str, str, bool)
    def applySetup(self, cloud_url: str, device_id: str, device_secret: str, remote_push: bool = False) -> None:
        try:
            result = self._api.provision_setup(
                cloud_url.strip(), device_id.strip(), device_secret.strip(), remote_push
            )
        except Exception as exc:  # pragma: no cover - exercised in GUI runtime
            self._error = str(exc)
            self.errorChanged.emit()
            return
        self._first_time_setup = False
        self._setup_secret = ""
        self._setup_device_id = str(result.get("device_id") or device_id.strip())
        self._setup_cloud_url = str(result.get("cloud_url") or cloud_url.strip())
        self._setup_local_address = str(result.get("local_address") or self._setup_local_address)
        self._setup_required = not (self._database_ok and self._models_ok)
        self._error = ""
        self.setupChanged.emit()
        self.errorChanged.emit()

    def _cleanup_worker(self, worker: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _get_setup_required(self) -> bool:
        return self._setup_required

    def _get_database_ok(self) -> bool:
        return self._database_ok

    def _get_models_ok(self) -> bool:
        return self._models_ok

    def _get_error(self) -> str:
        return self._error

    def _get_first_time_setup(self) -> bool:
        return self._first_time_setup

    def _get_setup_device_id(self) -> str:
        return self._setup_device_id

    def _get_setup_secret(self) -> str:
        return self._setup_secret

    def _get_setup_local_address(self) -> str:
        return self._setup_local_address

    def _get_setup_cloud_url(self) -> str:
        return self._setup_cloud_url

    def _get_setup_detected_lan_address(self) -> str:
        return self._setup_detected_lan_address

    setupRequired = Property(bool, _get_setup_required, notify=setupChanged)
    databaseOk = Property(bool, _get_database_ok, notify=setupChanged)
    modelsOk = Property(bool, _get_models_ok, notify=setupChanged)
    error = Property(str, _get_error, notify=errorChanged)
    firstTimeSetup = Property(bool, _get_first_time_setup, notify=setupChanged)
    setupDeviceId = Property(str, _get_setup_device_id, notify=setupChanged)
    setupSecret = Property(str, _get_setup_secret, notify=setupChanged)
    setupLocalAddress = Property(str, _get_setup_local_address, notify=setupChanged)
    setupCloudUrl = Property(str, _get_setup_cloud_url, notify=setupChanged)
    setupDetectedLanAddress = Property(str, _get_setup_detected_lan_address, notify=setupChanged)
