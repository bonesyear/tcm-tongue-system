"""图片清洗、暂存与提交事务；不接触真实照片或模型端点。"""
from __future__ import annotations

import io
import os
import struct
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def clean_image_bytes(data: bytes) -> bytes:
    """验证真实图片，按方向重排像素并无元数据编码为 JPEG。"""
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError(f"图片超过 {MAX_PHOTO_BYTES // 1024 // 1024} MiB 上限")
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("仅支持 JPEG、PNG、WebP 图片")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError(f"图片像素超过 {MAX_IMAGE_PIXELS} 上限")
            image = ImageOps.exif_transpose(image)
            image.load()
            if image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError,
            OSError, SyntaxError, struct.error) as error:
        raise ValueError(f"无法识别有效图片: {error}") from error


def stage_upload(file, photos_dir: str, date_str: str, part: str) -> str:
    data = file.stream.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError(f"图片超过 {MAX_PHOTO_BYTES // 1024 // 1024} MiB 上限")
    cleaned = clean_image_bytes(data)
    from io_utils import atomic_write_bytes
    directory = os.path.join(photos_dir, date_str, ".staging")
    filename = f"{part}-{uuid.uuid4().hex}.jpg"
    atomic_write_bytes(os.path.join(directory, filename), cleaned)
    return filename


def _rollback(moves):
    for target, staging, backups in reversed(moves):
        if os.path.exists(target):
            os.replace(target, staging)
        for original, backup in reversed(backups):
            if os.path.exists(backup):
                os.replace(backup, original)


def commit_photos(draft: dict, photos_dir: str, date_str: str,
                  allowed_parts, backup_dir: str) -> dict:
    """仅转正本轮真实识图的暂存图片；冲突可回滚到提交前状态。"""
    from io_utils import write_lock
    day_dir = os.path.join(photos_dir, date_str)
    os.makedirs(day_dir, exist_ok=True)
    moves = []
    try:
        with write_lock(day_dir):
            for part in allowed_parts:
                state = draft["parts"].get(part, {})
                staging_name = state.get("photo_staging")
                if not staging_name:
                    continue
                if os.path.basename(staging_name) != staging_name:
                    raise ValueError("暂存图片文件名不合法")
                staging = os.path.join(day_dir, ".staging", staging_name)
                if not os.path.isfile(staging):
                    raise ValueError(f"暂存图片不存在: {part}")
                target = os.path.join(day_dir, f"{part}.jpg")
                backup = os.path.join(backup_dir, "photos", date_str, uuid.uuid4().hex)
                os.makedirs(backup, exist_ok=True)
                backups = []
                # 先登记当前部位，备份或转正任一步失败都能恢复本轮已移动文件。
                moves.append((target, staging, backups))
                for extension in IMAGE_EXTENSIONS:
                    original = os.path.join(day_dir, part + extension)
                    if os.path.isfile(original):
                        destination = os.path.join(backup, part + extension)
                        os.replace(original, destination)
                        backups.append((original, destination))
                os.replace(staging, target)
    except Exception:
        _rollback(moves)
        raise
    return {"moves": moves}


def rollback_photos(transaction: dict) -> None:
    _rollback(transaction["moves"])
