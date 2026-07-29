"""One-time migration of legacy public uploads into private object storage.

Run this during a maintenance window with the cloud backend environment loaded.
It updates database object keys and moves files atomically; it never follows
symlinks or accepts paths outside the legacy static upload root.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from app.core.private_storage import private_path
from app.core.database import SessionLocal
from app.models.models import UploadedDocument, UserImage, AuthenticationLog, SurveillanceLog


def move_one(old: Path, category: str, suffix: str) -> str | None:
    if not old.is_file() or old.is_symlink():
        return None
    key = f"{secrets.token_hex(24)}{suffix.lower()}"
    target = private_path(category, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    old.replace(target)
    return key


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    static = backend / "app" / "static"
    with SessionLocal() as db:
        for document in db.query(UploadedDocument).all():
            old = Path(document.file_path)
            if not old.is_absolute():
                old = static / old.relative_to("static") if str(old).startswith("static/") else static / old
            key = move_one(old, "documents", old.suffix)
            if key:
                document.filename = key
                document.file_path = key
        for image in db.query(UserImage).all():
            old = static / image.image_path.lstrip("/").removeprefix("static/")
            key = move_one(old, "faces", old.suffix)
            if key:
                image.image_path = key
        for log_model in (AuthenticationLog, SurveillanceLog):
            for log in db.query(log_model).all():
                if log.image_path and log.image_path.startswith("/static/"):
                    old = static / log.image_path.removeprefix("/static/")
                    key = move_one(old, "surveillance", old.suffix)
                    if key:
                        log.image_path = key
        db.commit()


if __name__ == "__main__":
    main()
