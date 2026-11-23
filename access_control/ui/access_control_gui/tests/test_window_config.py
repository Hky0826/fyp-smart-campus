"""Tests for GUI window configuration and Raspberry Pi screen simulation mode."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from access_control.ui.access_control_gui.main import _resolve_window_config, _str_to_bool


def test_str_to_bool():
    assert _str_to_bool(None) is None
    assert _str_to_bool("") is None
    assert _str_to_bool("1") is True
    assert _str_to_bool("true") is True
    assert _str_to_bool("TRUE") is True
    assert _str_to_bool("yes") is True
    assert _str_to_bool("on") is True
    assert _str_to_bool("0") is False
    assert _str_to_bool("false") is False
    assert _str_to_bool("no") is False
    assert _str_to_bool("off") is False


def test_resolve_window_config_laptop_default(monkeypatch):
    """On developer laptops (Windows/macOS), default to windowed 800x480."""
    monkeypatch.delenv("EDGE_GUI_WINDOWED", raising=False)
    monkeypatch.delenv("EDGE_GUI_FULLSCREEN", raising=False)
    monkeypatch.delenv("EDGE_GUI_WIDTH", raising=False)
    monkeypatch.delenv("EDGE_GUI_HEIGHT", raising=False)

    with patch("sys.platform", "win32"):
        is_windowed, width, height = _resolve_window_config([])
        assert is_windowed is True
        assert width == 800
        assert height == 480

    with patch("sys.platform", "darwin"):
        is_windowed, width, height = _resolve_window_config([])
        assert is_windowed is True
        assert width == 800
        assert height == 480


def test_resolve_window_config_linux_kiosk_default(monkeypatch):
    """On Linux (Raspberry Pi kiosk), default to fullscreen 800x480."""
    monkeypatch.delenv("EDGE_GUI_WINDOWED", raising=False)
    monkeypatch.delenv("EDGE_GUI_FULLSCREEN", raising=False)
    monkeypatch.delenv("EDGE_GUI_WIDTH", raising=False)
    monkeypatch.delenv("EDGE_GUI_HEIGHT", raising=False)

    with patch("sys.platform", "linux"):
        is_windowed, width, height = _resolve_window_config([])
        assert is_windowed is False
        assert width == 800
        assert height == 480


def test_resolve_window_config_cli_flags(monkeypatch):
    monkeypatch.delenv("EDGE_GUI_WINDOWED", raising=False)
    monkeypatch.delenv("EDGE_GUI_FULLSCREEN", raising=False)

    # CLI flag --windowed on Linux forces windowed mode
    with patch("sys.platform", "linux"):
        is_windowed, width, height = _resolve_window_config(["--windowed"])
        assert is_windowed is True
        assert width == 800
        assert height == 480

    # CLI flag --fullscreen on Windows forces fullscreen mode
    with patch("sys.platform", "win32"):
        is_windowed, width, height = _resolve_window_config(["--fullscreen"])
        assert is_windowed is False

    # CLI flags for custom dimensions (e.g. 1024x600 display)
    is_windowed, width, height = _resolve_window_config(["--width", "1024", "--height", "600"])
    assert width == 1024
    assert height == 600


def test_resolve_window_config_env_vars(monkeypatch):
    # EDGE_GUI_WINDOWED env var
    monkeypatch.setenv("EDGE_GUI_WINDOWED", "1")
    monkeypatch.delenv("EDGE_GUI_FULLSCREEN", raising=False)
    with patch("sys.platform", "linux"):
        is_windowed, _, _ = _resolve_window_config([])
        assert is_windowed is True

    monkeypatch.setenv("EDGE_GUI_WINDOWED", "0")
    with patch("sys.platform", "win32"):
        is_windowed, _, _ = _resolve_window_config([])
        assert is_windowed is False

    # EDGE_GUI_FULLSCREEN env var
    monkeypatch.delenv("EDGE_GUI_WINDOWED", raising=False)
    monkeypatch.setenv("EDGE_GUI_FULLSCREEN", "1")
    with patch("sys.platform", "win32"):
        is_windowed, _, _ = _resolve_window_config([])
        assert is_windowed is False

    # Custom dimensions via env
    monkeypatch.setenv("EDGE_GUI_WIDTH", "1280")
    monkeypatch.setenv("EDGE_GUI_HEIGHT", "720")
    _, width, height = _resolve_window_config([])
    assert width == 1280
    assert height == 720


def test_main_qml_source_declarations():
    """Verify Main.qml contains the windowed simulation properties, flags, and F11 shortcut."""
    qml_path = Path(__file__).resolve().parents[1] / "qml" / "Main.qml"
    content = qml_path.read_text(encoding="utf-8")

    assert "readonly property bool isWindowed:" in content
    assert "simulatedWidth" in content
    assert "simulatedHeight" in content
    assert "visibility: isWindowed ? Window.Windowed : Window.FullScreen" in content
    assert "flags: isWindowed ? Qt.Window : (Qt.Window | Qt.FramelessWindowHint)" in content
    assert "sequence: \"F11\"" in content
