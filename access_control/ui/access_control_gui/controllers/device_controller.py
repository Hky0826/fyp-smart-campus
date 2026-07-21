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
            self.success.emit({"database": database, "models": models})
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
        model_rows = models.get("models") or []
        self._database_ok = bool(database.get("ok", database.get("success", True)))
        self._models_ok = all(bool(row.get("exists")) for row in model_rows) if model_rows else True
        self._setup_required = not (self._database_ok and self._models_ok)
        self._error = ""
        self.setupChanged.emit()
        self.errorChanged.emit()

    @Slot(str)
    def _on_failure(self, message: str) -> None:
        self._error = message
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

    setupRequired = Property(bool, _get_setup_required, notify=setupChanged)
    databaseOk = Property(bool, _get_database_ok, notify=setupChanged)
    modelsOk = Property(bool, _get_models_ok, notify=setupChanged)
    error = Property(str, _get_error, notify=errorChanged)

