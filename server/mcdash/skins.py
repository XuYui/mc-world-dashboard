"""Player skins: what each player wears, and changing it.

The server runs offline-mode, so the game only shows skins that carry a Mojang signature. The
SkinsRestorer plugin hands those to every client; we read and write its file storage directly:

    <SkinsRestorer>/players/<uuid>.player      which skin a player wears
    <SkinsRestorer>/skins/<name>.customskin    a signed texture (value + signature)

A new PNG is signed by uploading it to MineSkin. Without a stored choice SkinsRestorer would give a
player the skin of the paid account with the same name (usually a stranger), so "default" is stored
explicitly too: the game's own default skin for that UUID, signed the same way.

Copies of the textures are kept under <DATA>/skins/ for the page's previews and heads. When the
WorldDashboard plugin is running it picks up <PLUGIN_DIR>/skin-apply/<uuid> and re-applies the
skin of a player who is online; otherwise the new skin shows on their next join.
"""
import base64
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid as uuidlib

from . import config
from .gamedata import skin_for
from .util import load_json, write_atomic

DIR = os.path.join(config.DATA, "skins")
DEFAULTS = os.path.join(DIR, "defaults.json")          # signed copies of the game's default skins
MINESKIN = "https://api.mineskin.org/v2/generate"
USER_AGENT = "mc-world-dashboard/2.1"
TEXTURE_HOST = re.compile(r"^https?://textures\.minecraft\.net/texture/([0-9a-f]{16,80})$")
MAX_PNG = 64 * 1024

_mineskin_lock = threading.Lock()
_mineskin_next = 0.0


class SkinError(Exception):
    """A problem worth showing to the person changing their skin."""


# ---------- PNG checks ----------

def png_size(data):
    """(width, height) of a PNG, or None if it is not one."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def check_png(data):
    if len(data) > MAX_PNG:
        raise SkinError("文件太大了，皮肤图片应该只有几 KB。")
    size = png_size(data)
    if size is None:
        raise SkinError("这不是 PNG 图片。")
    if size != (64, 64):
        raise SkinError("皮肤必须是 64×64 像素（这张是 %d×%d）。" % size)


# ---------- reading SkinsRestorer's storage ----------

def decode_texture(value):
    """(texture url, slim) from a signed textures property value, or (None, False)."""
    try:
        d = json.loads(base64.b64decode(value))
        skin = d["textures"]["SKIN"]
        return skin["url"], (skin.get("metadata") or {}).get("model") == "slim"
    except (ValueError, KeyError, TypeError):
        return None, False


def _player_file(uuid):
    return os.path.join(config.SKINSRESTORER, "players", uuid + ".player")


def stored_property(uuid):
    """The signed value SkinsRestorer applies to this player, with the stored skin's name, or None."""
    p = load_json(_player_file(uuid))
    ident = (p or {}).get("skinIdentifier") or {}
    name, kind = ident.get("identifier"), ident.get("type")
    if not name:
        return None
    if kind == "CUSTOM":
        path = os.path.join(config.SKINSRESTORER, "skins", name.lower() + ".customskin")
    elif kind == "PLAYER":
        path = os.path.join(config.SKINSRESTORER, "skins", name + ".playerskin")
    else:
        return None
    d = load_json(path)
    if not d or not d.get("value"):
        return None
    return {"value": d["value"], "signature": d.get("signature"), "skin": name}


def texture_hash(url):
    m = TEXTURE_HOST.match(url or "")
    return m.group(1) if m else None


def cached_png(texhash):
    return os.path.join(DIR, texhash + ".png")


def fetch_texture(url):
    """Keep a local copy of a texture from Mojang's texture server; returns the path or None."""
    h = texture_hash(url)
    if not h:
        return None
    path = cached_png(h)
    if os.path.exists(path):
        return path
    req = urllib.request.Request(url.replace("http://", "https://", 1), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read(MAX_PNG + 1)
    if png_size(data) is None or len(data) > MAX_PNG:
        return None
    _save_png(path, data)
    return path


def _save_png(path, data):
    os.makedirs(DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def default_skin(uuid):
    """('wide'|'slim', name) of the default skin the game picks for this UUID."""
    model, name = skin_for(uuid).split("/")
    return model, name


def default_png(uuid):
    model, name = default_skin(uuid)
    return os.path.join(config.WEB, "assets", "skins", "%s_%s.png" % (model, name))


def describe(uuid):
    """What the page shows for one player: kind ('custom' | 'default'), arm model, texture file."""
    prop = stored_property(uuid)
    url, slim = decode_texture(prop["value"]) if prop else (None, False)
    h = texture_hash(url)
    defaults = load_json(DEFAULTS, {})
    model, name = default_skin(uuid)
    signed_default = defaults.get("%s/%s" % (model, name), {})
    if h and h != texture_hash(signed_default.get("url")):
        path = cached_png(h)
        return {"kind": "custom", "slim": slim, "file": path if os.path.exists(path) else None, "url": url}
    # nothing stored (SkinsRestorer would fall back to the same-name paid account) or the default
    return {"kind": "default" if h else "unset", "slim": model == "slim", "file": default_png(uuid), "url": url}


def refresh(roster):
    """Fetch any texture we have no copy of yet (run from the background loop)."""
    for p in roster:
        d = describe(p["uuid"])
        if d["kind"] == "custom" and d["file"] is None:
            try:
                fetch_texture(d["url"])
            except Exception as e:
                print("skin texture for %s: %s" % (p["name"], e), flush=True)


def png_for(uuid):
    """Path of the skin texture to serve for this player (custom, else the game's default)."""
    d = describe(uuid)
    return d["file"] if d["file"] and os.path.exists(d["file"]) else default_png(uuid)


# ---------- signing (MineSkin) ----------

def _multipart(fields, file_field, filename, data):
    boundary = "----mcdash" + uuidlib.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
    out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
            % (boundary, file_field, filename)).encode() + data + ("\r\n--%s--\r\n" % boundary).encode()
    return out, "multipart/form-data; boundary=" + boundary


def mineskin_sign(png, slim, label):
    """Upload a skin to MineSkin (unlisted) and return {value, signature, url}."""
    global _mineskin_next
    body, ctype = _multipart({"variant": "slim" if slim else "classic", "name": label[:20], "visibility": "unlisted"},
                             "file", "skin.png", png)
    headers = {"User-Agent": USER_AGENT, "Content-Type": ctype, "Accept": "application/json"}
    if config.MINESKIN_KEY:
        headers["Authorization"] = "Bearer " + config.MINESKIN_KEY
    with _mineskin_lock:
        for attempt in range(3):
            wait = _mineskin_next - time.time()
            if wait > 0:
                time.sleep(min(wait, 30))
            req = urllib.request.Request(MINESKIN, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.loads(r.read())
            except urllib.error.HTTPError as e:
                try:
                    d = json.loads(e.read())
                except ValueError:
                    raise SkinError("签名服务 MineSkin 出错（HTTP %d），稍后再试。" % e.code)
            except OSError:
                raise SkinError("连不上签名服务 MineSkin，稍后再试。")
            delay = ((d.get("rateLimit") or {}).get("delay") or {}).get("millis", 6000)
            _mineskin_next = time.time() + delay / 1000.0
            if d.get("success"):
                t = d["skin"]["texture"]
                return {"value": t["data"]["value"], "signature": t["data"]["signature"], "url": t["url"]["skin"]}
            codes = [e.get("code") for e in d.get("errors") or []]
            if "rate_limit" in codes and attempt < 2:
                continue
            msg = "; ".join(e.get("message", "") for e in d.get("errors") or []) or "未知错误"
            raise SkinError("MineSkin 拒绝了这张皮肤：" + msg)
    raise SkinError("MineSkin 太忙了，稍后再试。")


# ---------- writing SkinsRestorer's storage ----------

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_atomic(path, json.dumps(obj, ensure_ascii=False))


def store(uuid, skin_name, signed):
    """Make SkinsRestorer give this player the signed skin, and ask the plugin to re-apply it now."""
    skin_name = skin_name.lower()
    _write_json(os.path.join(config.SKINSRESTORER, "skins", skin_name + ".customskin"),
                {"skinName": skin_name, "value": signed["value"], "signature": signed["signature"], "dataVersion": 1})
    path = _player_file(uuid)
    p = load_json(path) or {"uniqueId": uuid, "history": [], "favourites": []}
    p["skinIdentifier"] = {"identifier": skin_name, "type": "CUSTOM"}
    p["offlineModeWarningDismissed"] = True
    p["dataVersion"] = 2
    _write_json(path, p)
    req = os.path.join(config.PLUGIN_DIR, "skin-apply", uuid)
    try:
        os.makedirs(os.path.dirname(req), exist_ok=True)
        open(req, "w").close()
    except OSError:
        pass


def set_custom(uuid, name, png, slim):
    check_png(png)
    signed = mineskin_sign(png, slim, name)
    h = texture_hash(signed["url"])
    if h:
        _save_png(cached_png(h), png)
    store(uuid, "dash-" + name, signed)
    return signed


def set_default(uuid, name):
    """Back to the game's default skin for this UUID (signed once per default skin, then reused)."""
    model, skin = default_skin(uuid)
    key = "%s/%s" % (model, skin)
    defaults = load_json(DEFAULTS, {})
    signed = defaults.get(key)
    if not signed:
        with open(default_png(uuid), "rb") as f:
            png = f.read()
        signed = mineskin_sign(png, model == "slim", "default-" + skin)
        defaults = load_json(DEFAULTS, {})
        defaults[key] = signed
        _write_json(DEFAULTS, defaults)
    store(uuid, "dash-" + name, signed)
    return signed


def main(argv):
    """python3 -m mcdash.skins default <name>...   give these players the game's default skin"""
    from . import saves
    if len(argv) < 2 or argv[0] != "default":
        print(main.__doc__)
        return 2
    people = {p["name"].lower(): p for p in saves.roster()}
    for n in argv[1:]:
        p = people.get(n.lower())
        if not p:
            print("%s: not on this save's roster" % n)
            continue
        set_default(p["uuid"], p["name"])
        print("%s: default skin %s" % (p["name"], "/".join(default_skin(p["uuid"]))))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
