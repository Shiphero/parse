"""Local assets use application-generated identifiers, never user filenames."""
import hashlib
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from routing_guides.config import get_settings


class InvalidUpload(ValueError):
    pass


def guide_directory(guide_id: UUID) -> Path:
    return get_settings().storage_root / "guides" / str(guide_id)


def save_original(guide_id: UUID, source: BinaryIO, max_upload_mb: int = 256) -> tuple[str, int]:
    directory = guide_directory(guide_id)
    directory.mkdir(parents=True, exist_ok=False)
    temporary = directory / "upload.part"
    digest = hashlib.sha256()
    size = 0
    limit = max_upload_mb * 1024 * 1024
    try:
        source.seek(0)
        if b"%PDF-" not in source.read(1024):
            raise InvalidUpload("This file is not a PDF. Choose the original PDF guide.")
        source.seek(0)
        with temporary.open("xb") as destination:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise InvalidUpload(f"This file exceeds the configured {max_upload_mb} MB upload limit.")
                digest.update(chunk)
                destination.write(chunk)
        temporary.rename(directory / "original.pdf")
        return digest.hexdigest(), size
    except BaseException:
        temporary.unlink(missing_ok=True)
        directory.rmdir()
        raise
