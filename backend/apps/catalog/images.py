"""Mirror product photos: download once, store small WebP variants, serve locally.

Why not hot-link the aggregator's images: originals are up to 700 KB each
(~9 MB for one catalog page), and their CDN answers 503 to some clients, so
browsers were left with half-loaded grids. A 360 px thumbnail is ~15 KB.
"""

from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError
from PIL import Image, UnidentifiedImageError

from .market import Fetcher, MarketError
from .models import Component, ProductImage

logger = logging.getLogger(__name__)

THUMB_SIZE = (360, 360)
LARGE_SIZE = (1000, 1000)
MAX_PHOTOS = 5  # upper bound; settings.MARKET_MAX_PHOTOS can lower it
MAX_BYTES = 8 * 1024 * 1024  # refuse absurdly large downloads


def _to_webp(image: Image.Image, size: tuple[int, int], quality: int) -> bytes:
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format="WEBP", quality=quality, method=5)
    return buffer.getvalue()


def make_variants(data: bytes) -> tuple[bytes, bytes]:
    """(thumbnail, large) WebP bytes. Transparent images get a white background,
    matching how shops present product photos."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"not an image: {exc}") from exc
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")
    return _to_webp(image, THUMB_SIZE, 78), _to_webp(image, LARGE_SIZE, 82)


def mirror_images(
    component: Component, urls: list[str], fetcher: Fetcher, limit: int | None = None
) -> int:
    """Download up to ``limit`` photos we don't have yet. Returns how many were added."""
    limit = min(limit or settings.MARKET_MAX_PHOTOS, MAX_PHOTOS)
    have = set(component.photos.values_list("source_url", flat=True))
    position = component.photos.count()
    added = 0
    for url in urls[:limit]:
        if url in have or position >= limit:
            continue
        try:
            data = fetcher.get_bytes(url, max_bytes=MAX_BYTES)
            thumb, large = make_variants(data)
        except (MarketError, ValueError) as exc:
            logger.warning("Photo %s for %s skipped: %s", url, component, exc)
            continue
        stem = f"{component.slug[:60]}-{position}"
        photo = ProductImage(component=component, source_url=url, position=position)
        photo.thumb.save(f"{stem}.webp", ContentFile(thumb), save=False)
        photo.large.save(f"{stem}.webp", ContentFile(large), save=False)
        try:
            photo.save()
        except IntegrityError:  # mirrored concurrently by another worker
            photo.thumb.delete(save=False)
            photo.large.delete(save=False)
            continue
        position += 1
        added += 1
    return added


def media_path(field) -> str | None:
    """Relative URL of a stored file ("/media/products/thumbs/x.webp")."""
    return field.url if field else None


def filename(url: str) -> str:
    return PurePosixPath(url).name
