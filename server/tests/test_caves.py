import json
import os
import struct
import unittest
import zlib

import support  # noqa: F401  (sets up the environment first)
from mcdash import caves, config

# ---------- a tiny NBT writer for building region files ----------


def _name(n):
    b = n.encode()
    return struct.pack(">H", len(b)) + b


def _payload(v):
    """(tag type, payload bytes) for a Python value; tuples mark typed values."""
    if isinstance(v, tuple):
        kind, val = v
        if kind == "byte":
            return 1, struct.pack(">b", val)
        if kind == "longs":
            return 12, struct.pack(">i", len(val)) + b"".join(struct.pack(">Q", x) for x in val)
        if kind == "ints":
            return 11, struct.pack(">i", len(val)) + b"".join(struct.pack(">i", x) for x in val)
    if isinstance(v, bool) or isinstance(v, int):
        return 3, struct.pack(">i", v)
    if isinstance(v, str):
        return 8, _name(v)
    if isinstance(v, dict):
        out = b""
        for k, x in v.items():
            t, p = _payload(x)
            out += bytes([t]) + _name(k) + p
        return 10, out + b"\x00"
    if isinstance(v, list):
        items = [_payload(x) for x in v]
        t = items[0][0] if items else 0
        return 9, bytes([t]) + struct.pack(">i", len(items)) + b"".join(p for _, p in items)
    raise TypeError(v)


def nbt(root):
    t, p = _payload(root)
    return bytes([t]) + _name("") + p


def pack(indices, palette_len):
    bits = max(4, (palette_len - 1).bit_length())
    per = 64 // bits
    longs = []
    for i in range(0, 4096, per):
        v = 0
        for j, x in enumerate(indices[i:i + per]):
            v |= x << (bits * j)
        longs.append(v)
    return longs


def write_region(path, chunks):
    """chunks: {index: nbt bytes}"""
    header, body = bytearray(8192), bytearray()
    for i, data in chunks.items():
        comp = zlib.compress(data)
        blob = struct.pack(">IB", len(comp) + 1, 2) + comp
        blob += b"\x00" * (-len(blob) % 4096)
        sector = 2 + len(body) // 4096
        struct.pack_into(">I", header, i * 4, (sector << 8) | (len(blob) // 4096))
        body += blob
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(header) + bytes(body))


class CaveTest(unittest.TestCase):
    def setUp(self):
        caves._colors = {"minecraft:stone": (100, 100, 100), "minecraft:sculk": (10, 30, 40)}

    def test_floor_under_open_air_is_drawn_and_rock_stays_dark(self):
        # Section Y=-3 (y -48..-33): stone everywhere except an air pocket over x=0..3, z=0
        # from y=-36 down to y=-40, with a sculk floor at y=-41.
        pal = ["minecraft:stone", "minecraft:air", "minecraft:sculk"]
        idx = [0] * 4096
        for x in range(4):
            for y in range(-40, -35):
                idx[(y + 48) * 256 + x] = 1
            idx[(-41 + 48) * 256 + x] = 2
        sec = {"Y": ("byte", -3), "block_states": {"palette": [{"Name": n} for n in pal], "data": ("longs", pack(idx, 3))}}
        solid = {"Y": ("byte", -2), "block_states": {"palette": [{"Name": "minecraft:stone"}]}}
        deep = {"Y": ("byte", -4), "block_states": {"palette": [{"Name": "minecraft:stone"}]}}
        chunk = nbt({"DataVersion": 1, "Status": "minecraft:full", "sections": [solid, sec, deep]})
        write_region(caves.region_path("minecraft_overworld", 0, 0), {0: chunk})

        rgba = caves.render("minecraft_overworld", -32, 0, 0)
        px = lambda x, z: tuple(rgba[(z * 512 + x) * 4:(z * 512 + x) * 4 + 4])
        self.assertEqual(px(1, 0)[3], 255)
        self.assertNotEqual(px(1, 0)[:3], caves.ROCK)         # the sculk floor
        self.assertGreater(px(1, 0)[2], px(1, 0)[0])          # bluish, like sculk
        self.assertEqual(px(8, 8)[:3], caves.ROCK)            # solid stone
        self.assertEqual(px(20, 0)[3], 0)                     # chunk 1 does not exist
        self.assertTrue(caves.png(rgba).startswith(b"\x89PNG"))

        path = caves.tile("minecraft_overworld", -32, 0, 0)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(caves.cached("minecraft_overworld", -32, 0, 0), (path, True))
        self.assertIsNone(caves.tile("minecraft_overworld", -32, 5, 5))

    def test_structure_starts_are_indexed(self):
        start = {"id": "minecraft:ancient_city", "ChunkX": 3, "ChunkZ": 4,
                 "Children": [{"BB": ("ints", [10, -51, 20, 110, -20, 90])}, {"BB": ("ints", [0, -40, 30, 50, -30, 60])}]}
        chunk = nbt({"Status": "minecraft:full", "structures": {"starts": {"minecraft:ancient_city": start},
                                                               "References": {}}})
        empty = nbt({"Status": "minecraft:full", "structures": {"starts": {}, "References": {}}})
        write_region(caves.region_path("minecraft_overworld", 1, 0), {0: chunk, 1: empty})
        found = caves.region_structures(caves.region_path("minecraft_overworld", 1, 0))
        self.assertEqual(found, [{"id": "minecraft:ancient_city", "x": 55, "y": -51, "z": 55, "bb": [0, -51, 20, 110, -20, 90]}])

        caves.scan(log=lambda *a: None)
        shown = caves.structures()["worlds"]["minecraft_overworld"]
        self.assertEqual([s["x"] for s in shown], [55])
        data = json.load(open(caves.structures_path(), encoding="utf-8"))
        self.assertIn("minecraft_overworld/r.1.0.mca", data["regions"])

    def test_layer_bounds(self):
        self.assertTrue(caves.layer_ok(-40))
        self.assertFalse(caves.layer_ok(-41))
        self.assertFalse(caves.layer_ok(-64))
        self.assertFalse(caves.layer_ok(400))


if __name__ == "__main__":
    unittest.main()
