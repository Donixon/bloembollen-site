from __future__ import annotations

import tempfile
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}
CHUNK_SIZE = 1024 * 1024


class InvalidImage(ValueError):
    pass


class ImageTooLarge(ValueError):
    pass


class ImageDimensionsTooLarge(ValueError):
    pass


def _copy_upload(source: BinaryIO, target: BinaryIO, max_bytes: int) -> None:
    total = 0
    while chunk := source.read(CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLarge
        target.write(chunk)


def prepare_images(
    source: BinaryIO,
    photos_dir: Path,
    thumbs_dir: Path,
    max_bytes: int,
) -> tuple[Path, Path]:
    upload_path: Path | None = None
    photo_path: Path | None = None
    thumb_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=photos_dir, delete=False) as upload:
            upload_path = Path(upload.name)
            _copy_upload(source, upload, max_bytes)

        try:
            with Image.open(upload_path) as opened:
                if (opened.format or "").upper() not in ALLOWED_FORMATS:
                    raise InvalidImage
                oriented = ImageOps.exif_transpose(opened)
                rgb = oriented.convert("RGB")
                rgb.info.clear()
                rgb.thumbnail((1600, 1600), Image.Resampling.LANCZOS)

                with tempfile.NamedTemporaryFile(
                    dir=photos_dir, suffix=".jpg", delete=False
                ) as photo_file:
                    photo_path = Path(photo_file.name)
                rgb.save(photo_path, "JPEG", quality=88, optimize=True)

                thumb = rgb.copy()
                thumb.thumbnail((480, 480), Image.Resampling.LANCZOS)
                with tempfile.NamedTemporaryFile(
                    dir=thumbs_dir, suffix=".jpg", delete=False
                ) as thumb_file:
                    thumb_path = Path(thumb_file.name)
                thumb.save(thumb_path, "JPEG", quality=82, optimize=True)
        except Image.DecompressionBombError as exc:
            raise ImageDimensionsTooLarge from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidImage from exc

        return photo_path, thumb_path
    except Exception:
        for path in (photo_path, thumb_path):
            if path is not None:
                path.unlink(missing_ok=True)
        raise
    finally:
        if upload_path is not None:
            upload_path.unlink(missing_ok=True)


def remove_files(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
