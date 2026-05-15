from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, UnidentifiedImageError


class TileServer:
    def __init__(self, image_path: Path, tile_size: int = 256):
        self.image_path = image_path
        self.tile_size = tile_size

        if not self.image_path.exists():
            raise FileNotFoundError(f"Base image not found: {self.image_path}")

        try:
            with Image.open(self.image_path) as im:
                im.load()
                self.width, self.height = im.size
        except UnidentifiedImageError as e:
            raise RuntimeError(
                f"Base image is not a readable raster image (PNG/JPG). "
                f"Did you accidentally put an SVG/PDF here? Path: {self.image_path}"
            ) from e

        self.max_zoom = int(math.ceil(math.log(max(self.width, self.height) / self.tile_size, 2)))
        self.max_zoom = max(0, self.max_zoom)

        # disk cache folder
        self.cache_root = self.image_path.parent / "tile_cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _mtime(self) -> int:
        return int(self.image_path.stat().st_mtime)

    def _etag(self) -> str:
        h = hashlib.sha1(
            f"{self.image_path}:{self._mtime()}:{self.width}x{self.height}".encode("utf-8")
        ).hexdigest()
        return f'W/"{h}"'

    def manifest(self) -> dict:
        return {
            "image": {"width": self.width, "height": self.height},
            "tiling": {"tile_size": self.tile_size, "max_zoom": self.max_zoom},
            "coord_system": "pixel_at_max_zoom",
            "etag": self._etag(),
        }

    def tile_bounds(self, z: int) -> Tuple[int, int]:
        scale = 2 ** (self.max_zoom - z)
        sw = int(math.ceil(self.width / scale))
        sh = int(math.ceil(self.height / scale))
        tiles_x = int(math.ceil(sw / self.tile_size))
        tiles_y = int(math.ceil(sh / self.tile_size))
        return tiles_x, tiles_y

    def _cache_tile_path(self, mtime: int, z: int, x: int, y: int) -> Path:
        return self.cache_root / str(mtime) / str(z) / str(x) / f"{y}.png"

    def _render_scaled_image(self, z: int) -> Image.Image:
        scale = 2 ** (self.max_zoom - z)
        with Image.open(self.image_path) as im:
            im = im.convert("RGBA")
            if scale == 1:
                im.load()
                return im.copy()

            new_w = max(1, int(math.ceil(self.width / scale)))
            new_h = max(1, int(math.ceil(self.height / scale)))
            return im.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)

    def render_tile(self, z: int, x: int, y: int) -> Optional[Image.Image]:
        if z < 0 or z > self.max_zoom:
            return None

        tiles_x, tiles_y = self.tile_bounds(z)
        if x < 0 or y < 0 or x >= tiles_x or y >= tiles_y:
            return None

        src = self._render_scaled_image(z)

        left = x * self.tile_size
        upper = y * self.tile_size
        right = left + self.tile_size
        lower = upper + self.tile_size

        tile = Image.new("RGBA", (self.tile_size, self.tile_size), (0, 0, 0, 0))
        crop = src.crop((left, upper, right, lower))
        tile.paste(crop, (0, 0))
        return tile

    def render_tile_png_bytes(self, mtime: int, z: int, x: int, y: int) -> Optional[bytes]:
        cache_path = self._cache_tile_path(mtime, z, x, y)

        # serve existing tile from disk
        if cache_path.exists():
            return cache_path.read_bytes()

        im = self.render_tile(z, x, y)
        if im is None:
            return None

        cache_path.parent.mkdir(parents=True, exist_ok=True)

        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()

        cache_path.write_bytes(data)
        return data