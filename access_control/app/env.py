"""Small .env loader for the standalone access-control app."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_LOADED = False


def load_dotenv() -> None:
    """Load access_control/.env automatically without overriding real env vars."""
    global _LOADED
    if _LOADED:
        return

    seen: set[Path] = set()
    for path in (ROOT / ".env", Path.cwd() / ".env"):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_file(resolved)
    _LOADED = True


def _load_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _clean_value(value.strip())
        os.environ.setdefault(key, value)
        if key.startswith("access_"):
            os.environ.setdefault(key.upper(), value)


def _clean_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
