"""Launch the native PySide6/QML edge access-control kiosk."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import QCoreApplication, QLibraryInfo, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

try:
    from PySide6.QtQuickControls2 import QQuickStyle
except ImportError:  # pragma: no cover - depends on the installed Qt bundle
    QQuickStyle = None


def _configure_qt_runtime() -> None:
    """Choose conservative Qt settings before QApplication and cv2 import."""
    pyside_plugins = _pyside_plugin_root()
    pyside_platforms = pyside_plugins / "platforms"
    if pyside_plugins.exists():
        os.environ.setdefault("QT_PLUGIN_PATH", str(pyside_plugins))
    if pyside_platforms.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(pyside_platforms)

    if "EDGE_GUI_QPA_PLATFORM" in os.environ:
        os.environ["QT_QPA_PLATFORM"] = os.environ["EDGE_GUI_QPA_PLATFORM"]

    if sys.platform.startswith("linux"):
        if "QT_QPA_PLATFORM" not in os.environ:
            os.environ["QT_QPA_PLATFORM"] = "wayland" if os.getenv("WAYLAND_DISPLAY") else "linuxfb"
        backend = os.getenv("EDGE_GUI_QT_BACKEND", "software")
        os.environ.setdefault("QT_QUICK_BACKEND", backend)
        QQuickWindow.setSceneGraphBackend(backend)


def _pyside_plugin_root() -> Path:
    try:
        configured = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        if configured:
            return Path(configured)
    except Exception:
        pass
    return Path(PySide6.__file__).resolve().parent / "Qt" / "plugins"


def main() -> int:
    _configure_qt_runtime()
    if QQuickStyle is not None:
        QQuickStyle.setStyle(os.getenv("EDGE_GUI_QT_STYLE", "Basic"))
    QCoreApplication.setApplicationName("Edge Access Control")
    QCoreApplication.setOrganizationName("EdgeMind")

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    from .controllers.access_controller import AccessController
    from .controllers.api_client import KioskApiClient
    from .controllers.camera_controller import CameraController, CameraImageProvider
    from .controllers.chatbot_controller import ChatbotController
    from .controllers.device_controller import DeviceController

    api = KioskApiClient()
    provider = CameraImageProvider()
    camera = CameraController(provider)
    chatbot = ChatbotController(api)
    access = AccessController(api, camera, chatbot)
    device = DeviceController(api)

    # Keep Python-owned QObject wrappers alive for the full Qt application
    # lifetime. This is especially important for the setup controller, which
    # is otherwise observed as null by QML on some PySide6/Qt combinations.
    for controller in (camera, access, chatbot, device):
        controller.setParent(app)

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
