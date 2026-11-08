"""The 世界 tab: which of the server's worlds is running, and switching to another one.

Only one world runs at a time (memory is the limit, disk is not). The host's `mc-world` script
does the actual stop/start; the list of worlds is its config (/etc/mc-worlds.json). Switching needs
the admin password, whose PBKDF2 hash is DASH_ADMIN_PASSWORD; make one with

    python3 -m mcdash.worlds hash        (reads the password from the terminal)

Who is online comes from a status ping to the game port, which works for any server software.
"""
import getpass
import hashlib
import hmac
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time

from . import config
from .util import load_json

PBKDF2_ROUNDS = 200000
_cache = {"at": 0, "value": None}
_lock = threading.Lock()


class SwitchError(Exception):
    pass


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return "pbkdf2_sha256:%d:%s:%s" % (PBKDF2_ROUNDS, salt, digest)    # no "$": env files may expand it


def check_admin(password):
    stored = config.ADMIN_PASSWORD
    try:
        algo, rounds, salt, digest = stored.split(":")
        rounds = int(rounds)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256" or not password:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return hmac.compare_digest(got, digest)


def enabled():
    return bool(config.ADMIN_PASSWORD) and os.path.exists(config.WORLDS_CONFIG)


# ---------- server list ping ----------

def _varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _read_varint(sock):
    n = shift = 0
    while True:
        b = sock.recv(1)
        if not b:
            raise OSError("closed")
        n |= (b[0] & 0x7F) << shift
        if not b[0] & 0x80:
            return n
        shift += 7
        if shift > 35:
            raise OSError("bad varint")


def ping(host="127.0.0.1", port=25565, timeout=2.0):
    """{online, max, names, version} from the game's status ping, or None if nothing answers."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            hp = host.encode()
            hs = _varint(0) + _varint(767) + _varint(len(hp)) + hp + struct.pack(">H", port) + _varint(1)
            s.sendall(_varint(len(hs)) + hs + _varint(1) + _varint(0))
            _read_varint(s)                       # packet length
            if _read_varint(s) != 0:
                return None
            size = _read_varint(s)
            data = b""
            while len(data) < size:
                chunk = s.recv(size - len(data))
                if not chunk:
                    return None
                data += chunk
        d = json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return None
    players = d.get("players") or {}
    return {
        "online": int(players.get("online") or 0), "max": int(players.get("max") or 0),
        "names": [p.get("name") for p in players.get("sample") or [] if p.get("name")],
        "version": (d.get("version") or {}).get("name"),
    }


# ---------- status and switching ----------

def _host_status():
    r = subprocess.run([config.MC_WORLD, "status"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise SwitchError((r.stderr or r.stdout).strip() or "mc-world status failed")
    return json.loads(r.stdout)


def status(max_age=2):
    """Everything the 世界 tab shows, cached for a couple of seconds."""
    with _lock:
        if _cache["value"] is not None and time.time() - _cache["at"] < max_age:
            return _cache["value"]
    conf = load_json(config.WORLDS_CONFIG, {"worlds": []})
    try:
        host = _host_status()
        error = None
    except (OSError, ValueError, subprocess.SubprocessError, SwitchError) as e:
        host, error = {"worlds": [], "switching": False, "last": None}, str(e)
    states = {w["id"]: w["state"] for w in host["worlds"]}
    worlds = [{
        "id": w["id"], "title": w.get("title") or w["id"], "game": w.get("game"), "client": w.get("client"),
        "dashboard": bool(w.get("dashboard")), "state": states.get(w["id"], "unknown"),
    } for w in conf["worlds"]]
    running = next((w["id"] for w in worlds if w["state"] in ("active", "activating", "deactivating")), None)
    p = ping(port=config.GAME_PORT) if running else None
    value = {
        "worlds": worlds, "running": running, "ready": p is not None, "ping": p,
        "switching": host.get("switching", False), "last": host.get("last"),
        "enabled": enabled(), "error": error,
    }
    with _lock:
        _cache.update(at=time.time(), value=value)
    return value


def switch(target):
    ids = [w["id"] for w in load_json(config.WORLDS_CONFIG, {"worlds": []})["worlds"]]
    if target not in ids:
        raise SwitchError("没有这个世界。")
    r = subprocess.run(["sudo", "-n", config.MC_WORLD, "switch", target], capture_output=True, text=True, timeout=20)
    with _lock:
        _cache["value"] = None
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        raise SwitchError("已经在切换了，等它完成。" if "already" in msg else "切换没能开始：" + (msg or "未知错误"))


def main():
    if sys.argv[1:] == ["hash"]:
        pw = getpass.getpass("管理员密码: ")
        if pw != getpass.getpass("再输一次: "):
            sys.exit("两次不一样")
        print("DASH_ADMIN_PASSWORD=" + hash_password(pw))
        return
    sys.exit("usage: python3 -m mcdash.worlds hash")


if __name__ == "__main__":
    main()
