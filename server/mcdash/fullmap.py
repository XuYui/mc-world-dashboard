"""Stitch each dimension's full-resolution tiles (1 pixel = 1 block) into one PNG for download.

Browsers cannot hold a whole dimension at full size (hundreds of MB of pixels), so the page
links these files instead. libvips streams the image in strips, so memory stays small.
Needs the `vips` command (Debian/Ubuntu: libvips-tools).

    python3 -m mcdash.fullmap        (from the server/ directory; mc-fullmap.timer runs it daily)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from . import config
from .util import load_json, write_atomic

TILE = 512
ZOOM = "3"


def tiles_of(world_dir):
    coords = {}
    zdir = os.path.join(world_dir, ZOOM)
    for name in os.listdir(zdir) if os.path.isdir(zdir) else []:
        m = re.match(r"^(-?\d+)_(-?\d+)\.png$", name)
        if m:
            coords[(int(m.group(1)), int(m.group(2)))] = os.path.join(zdir, name)
    return coords


def stitch(world, tiles, out_dir, work):
    xs = [x for x, _ in tiles]
    zs = [z for _, z in tiles]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    across = x1 - x0 + 1
    blank = os.path.join(work, "blank.v")
    if not os.path.exists(blank):
        subprocess.run(["vips", "black", blank, str(TILE), str(TILE), "--bands", "4"], check=True)
    # row-major, a transparent tile wherever nothing has been explored
    images = [tiles.get((x, z), blank) for z in range(z0, z1 + 1) for x in range(x0, x1 + 1)]
    tmp = os.path.join(out_dir, world + ".tmp.png")  # vips picks the PNG saver from the suffix
    final = os.path.join(out_dir, world + ".png")
    subprocess.run(["vips", "arrayjoin", " ".join(images), tmp + "[compression=9,strip]", "--across", str(across)],
                   check=True, env={**os.environ, "VIPS_CONCURRENCY": "1"})
    os.chmod(tmp, 0o640)
    os.replace(tmp, final)
    return {
        "file": "fullmap/%s.png" % world,
        "bytes": os.path.getsize(final),
        "width": across * TILE,
        "height": (z1 - z0 + 1) * TILE,
        "x": [x0 * TILE, (x1 + 1) * TILE],   # block coordinates covered
        "z": [z0 * TILE, (z1 + 1) * TILE],
        "ts": int(time.time()),
    }


def main():
    if not shutil.which("vips"):
        sys.exit("the vips command is missing (install libvips-tools)")
    out_dir = os.path.join(config.DATA, "fullmap")
    os.makedirs(out_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "index.json")
    index = load_json(index_path, {})
    work = tempfile.mkdtemp(prefix="fullmap-")
    try:
        for world in sorted(os.listdir(config.TILES)):
            tiles = tiles_of(os.path.join(config.TILES, world))
            if not tiles:
                continue
            started = time.time()
            index[world] = stitch(world, tiles, out_dir, work)
            print("%s: %dx%d, %.1f MB in %.0f s" % (world, index[world]["width"], index[world]["height"],
                                                    index[world]["bytes"] / 1048576, time.time() - started))
            write_atomic(index_path, json.dumps(index))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
