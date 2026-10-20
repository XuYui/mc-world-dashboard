"""Small helpers: NBT reading, JSON files."""
import gzip
import io
import json
import os
import struct


def read_nbt(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    f = io.BytesIO(raw)
    t = f.read(1)[0]
    f.read(struct.unpack(">H", f.read(2))[0])
    return _nbt(f, t)


def _nbt(f, t):
    u = lambda fmt, n: struct.unpack(fmt, f.read(n))[0]
    if t == 1: return u(">b", 1)
    if t == 2: return u(">h", 2)
    if t == 3: return u(">i", 4)
    if t == 4: return u(">q", 8)
    if t == 5: return u(">f", 4)
    if t == 6: return u(">d", 8)
    if t == 7: return f.read(u(">i", 4))
    if t == 8: return f.read(u(">H", 2)).decode("utf-8", "replace")
    if t == 9:
        et, n = f.read(1)[0], u(">i", 4)
        return [_nbt(f, et) for _ in range(n)]
    if t == 10:
        d = {}
        while True:
            et = f.read(1)[0]
            if et == 0:
                return d
            k = f.read(u(">H", 2)).decode("utf-8", "replace")
            d[k] = _nbt(f, et)
    if t == 11:
        n = u(">i", 4)
        return list(struct.unpack(">%di" % n, f.read(4 * n)))
    if t == 12:
        n = u(">i", 4)
        return list(struct.unpack(">%dq" % n, f.read(8 * n)))
    raise ValueError("bad nbt tag %d" % t)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def short(id_):
    return id_.split(":", 1)[-1]
