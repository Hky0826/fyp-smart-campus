from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

ALLOWED_DOCUMENT_EXTENSIONS = {
    ".txt", ".md", ".csv",
    ".pdf",
    ".docx", ".doc",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def private_path(category: str, object_key: str) -> Path:
    clean_key = (object_key or "").lstrip("/").removeprefix("uploads/").lstrip("/")
    if not clean_key or ".." in Path(clean_key).parts:
        raise HTTPException(status_code=404, detail="Private object not found")
    root = (settings.PRIVATE_STORAGE_ROOT / category).resolve()
    path = (root / clean_key).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=404, detail="Private object not found")
    return path


async def save_upload(upload: UploadFile, category: str, allowed_extensions: set[str], max_bytes: int) -> tuple[str, Path]:
    original = Path(upload.filename or "")
    extension = original.suffix.lower()
    if extension not in allowed_extensions:
        raise HTTPException(status_code=415, detail="Unsupported file extension")
    object_key = f"{secrets.token_hex(24)}{extension}"
    target = private_path(category, object_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{object_key}.{secrets.token_hex(8)}.tmp")
    total = 0
    try:
        with temp.open("xb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(target)  # atomic and target is a fresh no-overwrite key
    except HTTPException:
        temp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Unable to store uploaded file") from exc
    return object_key, target


def safe_existing_path(category: str, object_key: str) -> Path:
    path = private_path(category, object_key)
    if not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="Private object not found")
    return path
