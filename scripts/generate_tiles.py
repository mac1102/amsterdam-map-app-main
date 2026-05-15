from pathlib import Path
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.tile_server import TileServer

DATA_DIR = ROOT / "backend" / "data"
MAP_PATH = DATA_DIR / "map.png"
OUT_DIR = DATA_DIR / "tiles"

tile_server = TileServer(MAP_PATH, tile_size=256)
mtime = tile_server._mtime()

OUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"Generating tiles into: {OUT_DIR}")
print(f"Max zoom: {tile_server.max_zoom}")

count = 0

for z in range(tile_server.max_zoom + 1):
    tiles_x, tiles_y = tile_server.tile_bounds(z)
    print(f"Zoom {z}: {tiles_x} x {tiles_y}")

    for x in range(tiles_x):
        for y in range(tiles_y):
            png_bytes = tile_server.render_tile_png_bytes(mtime=mtime, z=z, x=x, y=y)
            if png_bytes is None:
                continue

            out_path = OUT_DIR / str(z) / str(x) / f"{y}.png"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(png_bytes)
            count += 1

print(f"Done. Wrote {count} tiles.")