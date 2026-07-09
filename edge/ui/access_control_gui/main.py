"""Launch the native PySide6/QML edge access-control kiosk."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from .controllers.access_controller import AccessController
from .controllers.api_client import KioskApiClient
from .controllers.camera_controller import CameraController, CameraImageProvider
from .controllers.chatbot_controller import ChatbotController
from .controllers.device_controller import DeviceController


def _configure_qt_runtime() -> None:
    """Choose a conservative Qt Quick backend before the GUI is created."""
    if "EDGE_GUI_QPA_PLATFORM" in os.environ:
        os.environ.setdefault("QT_QPA_PLATFORM", os.environ["EDGE_GUI_QPA_PLATFORM"])

    if sys.platform.startswith("linux"):
        backend = os.getenv("EDGE_GUI_QT_BACKEND", "software")
        os.environ.setdefault("QT_QUICK_BACKEND", backend)
        QQuickWindow.setSceneGraphBackend(backend)


def main() -> int:
    _configure_qt_runtime()
    QCoreApplication.setApplicationName("Edge Access Control")
    QCoreApplication.setOrganizationName("EdgeMind")

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    api = KioskApiClient()
    provider = CameraImageProvider()
    camera = CameraController(provider)
    chatbot = ChatbotController(api)
    access = AccessController(api, camera, chatbot)
    device = DeviceController(api)

    engine.addImageProvider("camera", provider)
    context = engine.rootContext()
    context.setContextProperty("cameraController", camera)
    context.setContextProperty("accessController", access)
    context.setContextProperty("chatbotController", chatbot)
    context.setContextProperty("deviceController", device)
    context.setContextProperty("apiBaseUrl", api.base_url)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 1

    camera.start()
    access.start()
    device.refresh()

    try:
        return app.exec()
    finally:
        access.stop()
        camera.stop()


if __name__ == "__main__":
    raise SystemExit(main())
