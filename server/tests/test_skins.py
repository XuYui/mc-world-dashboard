import base64
import json
import os
import sqlite3
import struct
import unittest
import zlib

import support  # noqa: F401  (sets up the environment first)
from mcdash import auth, config, skins

UUID = "8f2e1bd3-efc7-3cfa-aa54-dfcb5864eede"
TEX = "http://textures.minecraft.net/texture/a3bca425b06c13b6125a6bd87c6f48c8efaf87d74953a7d7567843339ff17c7f"


def png(w, h):
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\0" + b"\0\0\0\0" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def value(url, slim=False):
    skin = {"url": url}
    if slim:
        skin["metadata"] = {"model": "slim"}
    return base64.b64encode(json.dumps({"textures": {"SKIN": skin}}).encode()).decode()


class PngTest(unittest.TestCase):
    def test_size(self):
        self.assertEqual(skins.png_size(png(64, 64)), (64, 64))
        self.assertIsNone(skins.png_size(b"GIF89a" + b"\0" * 30))

    def test_check(self):
        skins.check_png(png(64, 64))
        with self.assertRaises(skins.SkinError):
            skins.check_png(png(64, 32))
        with self.assertRaises(skins.SkinError):
            skins.check_png(b"not a png at all, really not")


class StorageTest(unittest.TestCase):
    def setUp(self):
        try:
            os.remove(os.path.join(config.SKINSRESTORER, "players", UUID + ".player"))
        except OSError:
            pass

    def test_decode_texture(self):
        self.assertEqual(skins.decode_texture(value(TEX, slim=True)), (TEX, True))
        self.assertEqual(skins.decode_texture("!!"), (None, False))

    def test_store_and_describe(self):
        self.assertEqual(skins.describe(UUID)["kind"], "unset")
        skins.store(UUID, "dash-xu", {"value": value(TEX), "signature": "sig"})
        p = json.load(open(os.path.join(config.SKINSRESTORER, "players", UUID + ".player")))
        self.assertEqual(p["skinIdentifier"], {"identifier": "dash-xu", "type": "CUSTOM"})
        prop = skins.stored_property(UUID)
        self.assertEqual((prop["value"], prop["signature"]), (value(TEX), "sig"))
        d = skins.describe(UUID)
        self.assertEqual((d["kind"], d["slim"], d["file"]), ("custom", False, None))  # texture not fetched yet
        self.assertTrue(os.path.exists(os.path.join(config.PLUGIN_DIR, "skin-apply", UUID)))

    def test_store_keeps_history(self):
        path = os.path.join(config.SKINSRESTORER, "players", UUID + ".player")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump({"uniqueId": UUID, "history": [{"timestamp": 1}], "dataVersion": 2}, open(path, "w"))
        skins.store(UUID, "dash-xu", {"value": value(TEX), "signature": "sig"})
        self.assertEqual(json.load(open(path))["history"], [{"timestamp": 1}])

    def test_signed_default_counts_as_default(self):
        model, name = skins.default_skin(UUID)
        os.makedirs(skins.DIR, exist_ok=True)
        json.dump({"%s/%s" % (model, name): {"value": value(TEX), "signature": "s", "url": TEX}}, open(skins.DEFAULTS, "w"))
        try:
            skins.store(UUID, "dash-xu", {"value": value(TEX), "signature": "s"})
            d = skins.describe(UUID)
            self.assertEqual(d["kind"], "default")
            self.assertTrue(d["file"].endswith("%s_%s.png" % (model, name)))
        finally:
            os.remove(skins.DEFAULTS)


class AuthTest(unittest.TestCase):
    def test_rate_limit(self):
        for _ in range(auth.FAIL_LIMIT):
            self.assertEqual(auth.blocked("someone", "1.2.3.4"), 0)
            auth.failed("someone", "1.2.3.4")
        self.assertGreater(auth.blocked("someone", "5.6.7.8"), 0)   # the account is locked
        self.assertGreater(auth.blocked("other", "1.2.3.4"), 0)     # and so is the address

    def test_sessions(self):
        t = auth.login("xu", UUID)
        self.assertEqual(auth.who(t), ("xu", UUID))
        auth.logout(t)
        self.assertIsNone(auth.who(t))
        self.assertIsNone(auth.who("nope"))

    @unittest.skipUnless(auth.available(), "bcrypt not installed")
    def test_password(self):
        import bcrypt
        db = config.AUTHME_DB
        os.makedirs(os.path.dirname(db), exist_ok=True)
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE IF NOT EXISTS authme (username TEXT, password TEXT)")
        h = bcrypt.hashpw(b"hunter22", bcrypt.gensalt(4)).decode().replace("$2b$", "$2y$", 1)
        con.execute("INSERT INTO authme VALUES ('xu', ?)", (h,))
        con.commit()
        con.close()
        self.assertTrue(auth.check_password("XU", "hunter22"))
        self.assertFalse(auth.check_password("xu", "wrong"))
        self.assertFalse(auth.check_password("nobody", "hunter22"))


if __name__ == "__main__":
    unittest.main()
