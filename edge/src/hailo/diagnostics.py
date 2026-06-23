"""Runtime diagnostics for the HailoRT Python environment."""

from __future__ import annotations

import importlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

from .hailo_runner import hailort_import_error_message


def collect_diagnostics() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hailo_device": Path("/dev/hailo0").exists(),
        "hailo_platform_importable": False,
    }

    try:
        hailo_platform = importlib.import_module("hailo_platform")
    except Exception as exc:  # pragma: no cover - depends on Hailo device image
        result["error"] = hailort_import_error_message(exc)
        return result

    result["hailo_platform_importable"] = True
    result["hailo_platform_file"] = getattr(hailo_platform, "__file__", None)
    result["hailo_platform_version"] = getattr(hailo_platform, "__version__", None)
    return result


def main() -> None:
    diagnostics = collect_diagnostics()
    print(json.dumps(diagnostics, indent=2, sort_keys=True))
    raise SystemExit(0 if diagnostics["hailo_platform_importable"] else 1)


if __name__ == "__main__":
    main()
