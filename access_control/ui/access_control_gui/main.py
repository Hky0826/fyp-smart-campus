"""Launch the native PySide6/QML edge access-control kiosk."""

from __future__ import annotations

import argparse
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


def _str_to_bool(val: str | None) -> bool | None:
    if val is None:
        return None
    cleaned = val.strip().lower()
    if cleaned in ("1", "true", "yes", "on", "t"):
        return True
    if cleaned in ("0", "false", "no", "off", "f"):
        return False
    return None


def _resolve_window_config(argv: list[str] | None = None) -> tuple[bool, int, int]:
    """Resolve (is_windowed, width, height) from CLI flags, env vars, and platform defaults.

    Defaults to windowed mode (800x480) on non-Linux platforms (e.g. developer
    laptops running Windows/macOS) to simulate the Raspberry Pi kiosk display,
    while defaulting to fullscreen kiosk mode on Linux edge devices.
    """
    parser = argparse.ArgumentParser(description="Edge Access Control GUI", add_help=False)
    parser.add_argument("--windowed", dest="windowed", action="store_true", default=None,
                        help="Run in windowed mode simulating Raspberry Pi screen")
    parser.add_argument("--fullscreen", dest="windowed", action="store_false", default=None,
                        help="Run in fullscreen kiosk mode")
    parser.add_argument("--width", type=int, default=None, help="Window width (default: 800)")
    parser.add_argument("--height", type=int, default=None, help="Window height (default: 480)")

    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    # 1. Windowed vs FullScreen resolution
    is_windowed: bool | None = args.windowed
    if is_windowed is None:
        env_win = _str_to_bool(os.getenv("EDGE_GUI_WINDOWED"))
        if env_win is not None:
            is_windowed = env_win

    if is_windowed is None:
        env_full = _str_to_bool(os.getenv("EDGE_GUI_FULLSCREEN"))
        if env_full is not None:
            is_windowed = not env_full

    if is_windowed is None:
        # Default to windowed simulation on laptops (Windows / macOS),
        # fullscreen kiosk mode on Linux / Raspberry Pi.
        is_windowed = not sys.platform.startswith("linux")

    # 2. Window dimensions resolution (Raspberry Pi 7" touchscreen is 800x480)
    width = args.width
    if width is None:
        try:
            width = int(os.getenv("EDGE_GUI_WIDTH", "800"))
        except ValueError:
            width = 800

    height = args.height
    if height is None:
        try:
            height = int(os.getenv("EDGE_GUI_HEIGHT", "480"))
        except ValueError:
            height = 480

    return bool(is_windowed), max(320, width), max(240, height)


def main() -> int:
    _configure_qt_runtime()
    if QQuickStyle is not None:
        QQuickStyle.setStyle(os.getenv("EDGE_GUI_QT_STYLE", "Basic"))
    QCoreApplication.setApplicationName("Edge Access Control")
    QCoreApplication.setOrganizationName("EdgeMind")

    is_windowed, win_width, win_height = _resolve_window_config()

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
    context.setContextProperty("windowedMode", is_windowed)
    context.setContextProperty("simulatedWidth", win_width)
    context.setContextProperty("simulatedHeight", win_height)
    context.setContextProperty("cameraController", camera)
    context.setContextProperty("accessController", access)
    context.setContextProperty("chatbotController", chatbot)
    context.setContextProperty("deviceController", device)
    context.setContextProperty("apiBaseUrl", api.base_url)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 1

    root_window = engine.rootObjects()[0]
    if is_windowed:
        if hasattr(root_window, "showNormal"):
            root_window.showNormal()
        if hasattr(root_window, "resize"):
            root_window.resize(win_width, win_height)
        elif hasattr(root_window, "setWidth") and hasattr(root_window, "setHeight"):
            root_window.setWidth(win_width)
            root_window.setHeight(win_height)

        # Center the simulated kiosk window on the desktop
        screen = QGuiApplication.primaryScreen()
        if screen and hasattr(root_window, "setX") and hasattr(root_window, "setY"):
            screen_geo = screen.availableGeometry()
            x = max(0, (screen_geo.width() - win_width) // 2 + screen_geo.x())
            y = max(0, (screen_geo.height() - win_height) // 2 + screen_geo.y())
            root_window.setX(x)
            root_window.setY(y)
    else:
        if hasattr(root_window, "showFullScreen"):
            root_window.showFullScreen()

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
