"""Underground map layers and structure locations, read straight from the save's region files.

Cave layers work like a cave mode in client map mods: pick a height Y, and each column shows
the first floor below open air within the 32 blocks under Y. Solid rock is dark, so tunnels,
caverns and buildings such as ancient cities show up as lit shapes. One tile is one region file
(512 x 512 blocks, the same grid as zoom 3 of the surface map); tiles are rendered on request,
cached under state/caves/, and redrawn when the region file changes.

The structure index lists where every structure (ancient cities, trial chambers, ...) starts,
from the structure starts the game stores in each chunk.

    python3 -m mcdash.caves scan      update state/structures.json (mc-structures.timer runs it daily)
    python3 -m mcdash.caves render <world> <y> <rx> <rz>     render one tile (for testing)

Only the standard library is used, so this is plain Python and a tile takes a few seconds.
"""
import json
import multiprocessing
import os
import struct
import sys
import threading
import time
import zlib
from concurrent.futures import ProcessPoolExecutor

from . import config
from .util import load_json, write_atomic

DEPTH = 32                              # how far below the chosen height a floor is looked for
LAYER_STEP = 8                          # allowed heights are multiples of this
Y_MIN, Y_MAX = -64, 320
DIMS = {                                # map world name -> dimension folder inside the save
    "minecraft_overworld": "overworld",
    "minecraft_the_nether": "the_nether",
}
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
ROCK = (14, 14, 17)                     # a column that is solid all the way down
VOID = (8, 10, 26)                      # open air with no floor within DEPTH

# ---------- region files and NBT ----------


def region_dir(world):
    dim = DIMS[world]
    return os.path.join(config.MC, config.SAVE, "dimensions", "minecraft", dim, "region")


def region_path(world, rx, rz):
    return os.path.join(region_dir(world), "r.%d.%d.mca" % (rx, rz))


def chunks(path):
    """Yield (index, decompressed chunk NBT bytes) for every chunk stored in a region file."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 8192:
        return
    for i in range(1024):
        loc = struct.unpack_from(">I", data, i * 4)[0]
        off, count = (loc >> 8) * 4096, loc & 0xFF
        if not count or off + 5 > len(data):
            continue
        length, kind = struct.unpack_from(">IB", data, off)
        raw = data[off + 5:off + 4 + length]
        try:
            if kind == 2:
                yield i, zlib.decompress(raw)
            elif kind == 1:
                yield i, zlib.decompress(raw, 31)
            elif kind == 3:
                yield i, raw
            # 4 = LZ4 and 128+ = external .mcc files are not used by Paper's defaults; skipped
        except zlib.error:
            continue


_FIXED = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}
_ARRAY = {7: 1, 11: 4, 12: 8}


def _skip(b, p, t):
    """Return the offset just past a payload of tag type t starting at p."""
    if t in _FIXED:
        return p + _FIXED[t]
    if t in _ARRAY:
        n = struct.unpack_from(">i", b, p)[0]
        return p + 4 + n * _ARRAY[t]
    if t == 8:
        return p + 2 + struct.unpack_from(">H", b, p)[0]
    if t == 9:
        et, n = struct.unpack_from(">Bi", b, p)
        p += 5
        if et in _FIXED:
            return p + n * _FIXED[et]
        for _ in range(n):
            p = _skip(b, p, et)
        return p
    if t == 10:
        while True:
            et = b[p]
            p += 1
            if et == 0:
                return p
            p += 2 + struct.unpack_from(">H", b, p)[0]
            p = _skip(b, p, et)
    raise ValueError("bad NBT tag %d" % t)


def _read(b, p, t):
    """Parse a payload fully into Python values; returns (value, next offset)."""
    if t == 1:
        return struct.unpack_from(">b", b, p)[0], p + 1
    if t == 2:
        return struct.unpack_from(">h", b, p)[0], p + 2
    if t == 3:
        return struct.unpack_from(">i", b, p)[0], p + 4
    if t == 4:
        return struct.unpack_from(">q", b, p)[0], p + 8
    if t == 5:
        return struct.unpack_from(">f", b, p)[0], p + 4
    if t == 6:
        return struct.unpack_from(">d", b, p)[0], p + 8
    if t == 7:
        n = struct.unpack_from(">i", b, p)[0]
        return bytes(b[p + 4:p + 4 + n]), p + 4 + n
    if t == 8:
        n = struct.unpack_from(">H", b, p)[0]
        return bytes(b[p + 2:p + 2 + n]).decode("utf-8", "replace"), p + 2 + n
    if t == 9:
        et, n = struct.unpack_from(">Bi", b, p)
        p += 5
        out = []
        for _ in range(max(n, 0)):
            v, p = _read(b, p, et)
            out.append(v)
        return out, p
    if t == 10:
        out = {}
        while True:
            et = b[p]
            p += 1
            if et == 0:
                return out, p
            n = struct.unpack_from(">H", b, p)[0]
            name = bytes(b[p + 2:p + 2 + n]).decode("utf-8", "replace")
            out[name], p = _read(b, p + 2 + n, et)
    if t == 11:
        n = struct.unpack_from(">i", b, p)[0]
        return list(struct.unpack_from(">%di" % n, b, p + 4)), p + 4 + n * 4
    if t == 12:
        n = struct.unpack_from(">i", b, p)[0]
        return list(struct.unpack_from(">%dQ" % n, b, p + 4)), p + 4 + n * 8
    raise ValueError("bad NBT tag %d" % t)


def _compound_fields(b, p, wanted):
    """Walk a compound payload at p, parsing only the named fields; returns (dict, next offset)."""
    out = {}
    while True:
        t = b[p]
        p += 1
        if t == 0:
            return out, p
        n = struct.unpack_from(">H", b, p)[0]
        name = bytes(b[p + 2:p + 2 + n])
        p += 2 + n
        if name in wanted:
            out[name], p = wanted[name](b, p, t)
        else:
            p = _skip(b, p, t)


def _block_states(b, p, t):
    return _compound_fields(b, p, {b"palette": _palette, b"data": _read})


def _palette(b, p, t):
    et, n = struct.unpack_from(">Bi", b, p)
    p += 5
    names = []
    for _ in range(n):
        f, p = _compound_fields(b, p, {b"Name": _read})
        names.append(f.get(b"Name", "minecraft:air"))
    return names, p


def _sections(b, p, t, want_y):
    et, n = struct.unpack_from(">Bi", b, p)
    p += 5
    out = {}
    for _ in range(n):
        f, p = _compound_fields(b, p, {b"Y": _read, b"block_states": _block_states})
        if f.get(b"Y") in want_y and b"block_states" in f:
            out[f[b"Y"]] = f[b"block_states"]
    return out, p


def chunk_sections(nbt, want_y):
    """{section Y: (palette names, packed longs or None)} for the wanted section indices."""
    if nbt[0] != 10:
        return {}
    p = 3 + struct.unpack_from(">H", nbt, 1)[0]          # root tag type + name
    f, _ = _compound_fields(nbt, p, {b"sections": lambda b, p, t: _sections(b, p, t, want_y),
                                     b"Status": _read})
    status = f.get(b"Status", "")
    if status and status not in ("minecraft:full", "full"):
        return None                                        # not finished generating
    return {y: (s.get(b"palette", ["minecraft:air"]), s.get(b"data")) for y, s in f.get(b"sections", {}).items()}


def unpack(palette, longs):
    """The 4096 palette indices of a section (y*256 + z*16 + x order)."""
    if not longs or len(palette) <= 1:
        return None
    bits = max(4, (len(palette) - 1).bit_length())
    per, mask = 64 // bits, (1 << bits) - 1
    out = []
    for v in longs:
        for _ in range(per):
            out.append(v & mask)
            v >>= bits
    del out[4096:]
    return out

# ---------- block colours ----------


_colors = None


def block_colors():
    """Block id -> (r, g, b), made by tools/build_assets.py from the client's textures."""
    global _colors
    if _colors is None:
        raw = load_json(os.path.join(config.SERVER_ROOT, "blockcolors.json"), {}) or {}
        _colors = {k: tuple(v) for k, v in raw.items()}
    return _colors


def color_of(name):
    c = block_colors().get(name)
    if c is None:
        h = zlib.crc32(name.encode())                      # unknown block: a stable muted colour
        c = (90 + (h & 63), 90 + ((h >> 6) & 63), 90 + ((h >> 12) & 63))
        block_colors()[name] = c
    return c

# ---------- rendering a layer ----------


def layer_ok(y):
    return Y_MIN + 8 <= y <= Y_MAX and y % LAYER_STEP == 0


def render(world, top, rx, rz):
    """RGBA bytes (512*512*4) of one cave tile, or None when the region file does not exist."""
    path = region_path(world, rx, rz)
    if not os.path.isfile(path):
        return None
    bottom = max(Y_MIN, top - DEPTH + 1)
    want = set(range(bottom >> 4, (top >> 4) + 1))
    order = sorted(want, reverse=True)
    heights = [None] * (512 * 512)       # floor Y per pixel, for shading
    colors = [None] * (512 * 512)
    for i, nbt in chunks(path):
        try:
            secs = chunk_sections(nbt, want)
        except (ValueError, IndexError, struct.error):
            continue
        if secs is None:
            continue
        cx, cz = i & 31, i >> 5
        # One column list per section: (air flags, colours, indices), top section first.
        stack = []
        for sy in order:
            pal, longs = secs.get(sy, (["minecraft:air"], None))
            air = [n in AIR for n in pal]
            cols = [color_of(n) for n in pal]
            stack.append((sy, air, cols, unpack(pal, longs)))
        for lz in range(16):
            row = (cz * 16 + lz) * 512 + cx * 16
            for lx in range(16):
                col = lz * 16 + lx
                opened, hit, hy = False, None, None
                y = top
                for sy, air, cols, idx in stack:
                    ly = min(15, y - sy * 16)
                    lo = max(0, bottom - sy * 16)
                    while ly >= lo:
                        k = idx[ly * 256 + col] if idx is not None else 0
                        if air[k]:
                            opened = True
                        elif opened:
                            hit, hy = cols[k], sy * 16 + ly
                            break
                        ly -= 1
                    if hit is not None:
                        break
                    y = sy * 16 - 1
                px = row + lx
                if hit is not None:
                    colors[px], heights[px] = hit, hy
                else:
                    colors[px] = VOID if opened else ROCK
    return shade(colors, heights, top)


def shade(colors, heights, top):
    out = bytearray(512 * 512 * 4)
    for px in range(512 * 512):
        c = colors[px]
        if c is None:
            continue                                         # chunk not generated: transparent
        h = heights[px]
        if h is not None:
            # deeper floors are darker; a step up from the north-west neighbour is lit
            # floors are lifted off black so dark blocks (sculk, deepslate tiles) still read as floor
            f = 1.0 - 0.5 * (top - h) / DEPTH
            n = heights[px - 513] if px >= 513 and px % 512 else None
            if n is not None:
                f *= 1.15 if h > n else (0.82 if h < n else 1.0)
            c = tuple(min(255, int((40 + v * 0.85) * f)) for v in c)
        o = px * 4
        out[o], out[o + 1], out[o + 2], out[o + 3] = c[0], c[1], c[2], 255
    return bytes(out)


def png(rgba, w=512, h=512):
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def cache_path(world, top, rx, rz):
    return os.path.join(config.DATA, "caves", world, str(top), "%d_%d.png" % (rx, rz))


def cached(world, top, rx, rz):
    """(path, fresh): fresh is True when the cached tile is newer than its region file,
    None when the region does not exist (nothing to draw)."""
    out = cache_path(world, top, rx, rz)
    try:
        src_mtime = os.stat(region_path(world, rx, rz)).st_mtime
    except OSError:
        return out, None
    try:
        return out, os.stat(out).st_mtime >= src_mtime
    except OSError:
        return out, False


def tile(world, top, rx, rz):
    """Path of the cached tile, rendering it first when missing or older than its region file.
    None when there is no such region."""
    out, fresh = cached(world, top, rx, rz)
    if fresh is None:
        return None
    if fresh:
        return out
    rgba = render(world, top, rx, rz)
    if rgba is None:
        return None
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp%d" % os.getpid()
    with open(tmp, "wb") as f:
        f.write(png(rgba))
    os.replace(tmp, out)
    return out


# Rendering is CPU-bound Python, so the web server hands it to a small pool of low-priority
# processes (the game server shares the machine). Requests for a tile already being drawn wait
# for that one render.
WORKERS = 2
_pool, _inflight, _lock = None, {}, threading.Lock()


def _lower_priority():
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass


def tile_for_request(world, top, rx, rz, timeout=25):  # under the proxy's 30 s; the page retries
    out, fresh = cached(world, top, rx, rz)
    if fresh is None:
        return None
    if fresh:
        return out
    global _pool
    key = (world, top, rx, rz)
    with _lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(WORKERS, mp_context=multiprocessing.get_context("spawn"), initializer=_lower_priority)
        fut = _inflight.get(key)
        if fut is None:
            fut = _inflight[key] = _pool.submit(tile, world, top, rx, rz)
            fut.add_done_callback(lambda _f: _inflight.pop(key, None))
    return fut.result(timeout)

# ---------- structure index ----------


STARTS = b"\x0a\x00\x06starts"


def region_structures(path):
    """Structures that start in this region file: [{id, x, y, z, bb}]."""
    found = []
    for _, nbt in chunks(path):
        p = nbt.find(STARTS)
        if p < 0 or nbt[p + 9] == 0:                       # no starts tag, or an empty one
            continue
        try:
            starts, _ = _read(nbt, p + 9, 10)
        except (ValueError, IndexError, struct.error):
            continue
        for sid, s in starts.items():
            if not isinstance(s, dict) or s.get("id") == "INVALID":
                continue
            boxes = [c["BB"] for c in s.get("Children", []) if isinstance(c, dict) and len(c.get("BB", [])) == 6]
            if boxes:
                bb = [min(b[0] for b in boxes), min(b[1] for b in boxes), min(b[2] for b in boxes),
                      max(b[3] for b in boxes), max(b[4] for b in boxes), max(b[5] for b in boxes)]
            else:
                x, z = s.get("ChunkX", 0) * 16 + 8, s.get("ChunkZ", 0) * 16 + 8
                bb = [x, 0, z, x, 0, z]
            found.append({"id": s.get("id", sid), "x": (bb[0] + bb[3]) // 2, "y": bb[1], "z": (bb[2] + bb[5]) // 2, "bb": bb})
    return found


def structures_path():
    return os.path.join(config.DATA, "structures.json")


def scan(log=print):
    """Refresh the structure index, re-reading only region files that changed since last time."""
    out_path = structures_path()
    old = load_json(out_path, {}) or {}
    prev = old.get("regions", {})
    result = {"ts": int(time.time()), "regions": {}}
    for world in DIMS:
        d = region_dir(world)
        names = sorted(n for n in os.listdir(d) if n.endswith(".mca")) if os.path.isdir(d) else []
        t0, read = time.time(), 0
        for n in names:
            key = world + "/" + n
            path = os.path.join(d, n)
            try:
                mtime = int(os.stat(path).st_mtime)
            except OSError:
                continue
            if prev.get(key, {}).get("mtime") == mtime:
                result["regions"][key] = prev[key]
                continue
            result["regions"][key] = {"mtime": mtime, "found": region_structures(path)}
            read += 1
        log("%s: %d region files, %d re-read in %.0f s" % (world, len(names), read, time.time() - t0))
    write_atomic(out_path, json.dumps(result, separators=(",", ":")))
    return result


SHOWN = {"minecraft:ancient_city"}      # structures the page marks
_shown = (None, None)


def structures():
    """{ts, worlds: {world: [{id, x, y, z, bb}]}} of the marked structures from the last scan,
    re-read only when the index file changes."""
    global _shown
    try:
        mtime = os.stat(structures_path()).st_mtime_ns
    except OSError:
        return {"ts": None, "worlds": {}}
    if _shown[0] != mtime:
        data = load_json(structures_path(), {}) or {}
        out = {}
        for key, r in data.get("regions", {}).items():
            out.setdefault(key.split("/")[0], []).extend(s for s in r.get("found", []) if s["id"] in SHOWN)
        _shown = (mtime, {"ts": data.get("ts"), "worlds": out})
    return _shown[1]


if __name__ == "__main__":
    if sys.argv[1:2] == ["scan"]:
        scan()
    elif sys.argv[1:2] == ["render"]:
        w, y, x, z = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
        t = time.time()
        print(tile(w, y, x, z), "%.1f s" % (time.time() - t))
    else:
        print(__doc__)
