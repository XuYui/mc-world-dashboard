"""The dashboard's web server: the page, its JSON API and the map tiles.

    python3 -m mcdash            (from the server/ directory)

Standard library only. A background thread refreshes everything every DASH_REFRESH seconds;
requests are answered from that cache, compressed when the browser accepts it, with ETags so an
unchanged response costs a 304.
"""
import gzip
import hashlib
import json
import mimetypes
import os
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, report, saves
from .gamedata import skin_for
from .store import Store
from .util import load_json

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("application/javascript", ".js")
COMPRESSIBLE = ("application/json", "application/javascript", "text/", "image/svg+xml")
TILE_RE = re.compile(r"^/tiles/([a-z0-9_]+)/(\d)/(-?\d+)_(-?\d+)\.png$")
LIVE_STALE = 30           # seconds without a live.json update before the server counts as paused/stopped


class Body:
    """A cached response body with its ETag and a gzip copy."""

    def __init__(self, data, ctype="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        self.raw, self.ctype = data, ctype
        self.etag = '"%s"' % hashlib.sha1(data).hexdigest()[:20]
        self.gz = gzip.compress(data, 6) if len(data) > 1024 and ctype.startswith(COMPRESSIBLE) else None


class State:
    def __init__(self):
        self.store = Store()
        self.summary = Body({"loading": True})
        self.sessions = []
        self.graves = Body([])
        self.tiles = Body({})
        self.checks = []
        self.refreshed = 0
        self.changed = 0
        self.error = None
        self.lock = threading.Lock()
        self._last_version = None

    def refresh(self):
        people = [p["name"] for p in saves.roster()]
        self.store.ingest_logs(people)
        self.store.ingest_plugin()
        summary, sessions, graves = report.build(self.store)
        summary["fullmap"] = load_json(os.path.join(config.DATA, "fullmap", "index.json"), {})
        tiles = tile_index()
        checks = self_checks(tiles)
        body = Body(summary)
        with self.lock:
            if body.etag != self.summary.etag:
                self.changed = int(time.time())
            self.summary, self.sessions = body, sessions
            self.graves, self.tiles, self.checks = Body(graves), Body(tiles), checks
            self.refreshed = int(time.time())
            self.error = None

    def loop(self):
        while True:
            try:
                self.refresh()
            except Exception:
                self.error = traceback.format_exc(limit=3)
                print(self.error, flush=True)
            # plugin events arrive often; check them more frequently than the full rebuild
            for _ in range(config.REFRESH_SECONDS // 5):
                time.sleep(5)
                try:
                    if self.store.ingest_plugin():
                        break
                except Exception:
                    pass


def tile_index():
    """{world: {zoom: [[x, z], ...]}} of existing tiles (the export stitches these)."""
    out = {}
    root = config.TILES
    for world in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        zooms = {}
        for z in sorted(os.listdir(os.path.join(root, world))) if os.path.isdir(os.path.join(root, world)) else []:
            if z.isdigit():
                coords = []
                for name in os.listdir(os.path.join(root, world, z)):
                    m = re.match(r"^(-?\d+)_(-?\d+)\.png$", name)
                    if m:
                        coords.append([int(m.group(1)), int(m.group(2))])
                zooms[z] = sorted(coords)
        if zooms:
            out[world] = zooms
    return out


def read_live():
    """The plugin's live.json (players, server load), or None."""
    path = os.path.join(config.PLUGIN_DIR, "live.json")
    live = load_json(path)
    if live is not None:
        live["age"] = max(0, time.time() - live.get("ts", 0) / 1000.0)
    return live


def self_checks(tiles):
    """Problems worth showing on the page (a list of short messages)."""
    out = []
    if not tiles:
        out.append("找不到地图图块（%s），地图会是空白。" % config.TILES)
    else:
        newest = 0
        for world in tiles:
            d = os.path.join(config.TILES, world, "3")
            try:
                newest = max(newest, os.path.getmtime(d))
            except OSError:
                pass
        live = read_live()
        playing = live and live["age"] < LIVE_STALE and live.get("players")
        if playing and time.time() - newest > 6 * 3600:
            out.append("有人在玩，但地图图块已经 %d 小时没更新，地图渲染可能停了。" % ((time.time() - newest) // 3600))
    if not os.path.exists(os.path.join(config.PLUGIN_DIR, "live.json")):
        out.append("没有 WorldDashboard 插件的数据：在线玩家、死亡位置和服务器负载不可用。")
    if not os.path.exists(config.DEFS):
        out.append("缺少 defs.json：先运行 tools/build_assets.py。")
    return out


STATE = None


class Handler(BaseHTTPRequestHandler):
    server_version = "mc-world-dashboard"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def send_body(self, body, cache="no-cache"):
        if self.headers.get("If-None-Match") == body.etag:
            self.send_response(304)
            self.send_header("ETag", body.etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data, enc = body.raw, None
        if body.gz is not None and "gzip" in self.headers.get("Accept-Encoding", ""):
            data, enc = body.gz, "gzip"
        self.send_response(200)
        self.send_header("Content-Type", body.ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", body.etag)
        self.send_header("Cache-Control", cache)
        if enc:
            self.send_header("Content-Encoding", enc)
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_file(self, path, ctype=None):
        try:
            st = os.stat(path)
        except OSError:
            return self.send_error(404)
        etag = '"%x-%x"' % (st.st_mtime_ns, st.st_size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        gz = ctype.startswith(COMPRESSIBLE) and st.st_size > 1024 and "gzip" in self.headers.get("Accept-Encoding", "")
        data = open(path, "rb").read() if (gz or st.st_size < 1 << 20) else None
        if gz:
            data = gzip.compress(data, 6)
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(data) if data is not None else st.st_size))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if self.command == "HEAD":
            return
        if data is not None:
            self.wfile.write(data)
        else:
            with open(path, "rb") as f:
                while chunk := f.read(1 << 16):
                    self.wfile.write(chunk)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        try:
            if path == "/api/summary":
                return self.send_body(STATE.summary)
            if path == "/api/sessions":
                q = parse_qs(url.query)
                offset = max(0, int(q.get("offset", ["0"])[0]))
                limit = min(100, max(1, int(q.get("limit", ["20"])[0])))
                return self.send_body(Body({"total": len(STATE.sessions), "offset": offset,
                                            "items": STATE.sessions[offset:offset + limit]}))
            if path == "/api/graves":
                return self.send_body(STATE.graves)
            if path == "/api/tiles":
                return self.send_body(STATE.tiles)
            if path == "/api/live":
                live = read_live()
                return self.send_body(Body({
                    "now": int(time.time()), "refreshed": STATE.refreshed, "changed": STATE.changed,
                    "checks": STATE.checks + (["后台刷新出错：" + STATE.error.strip().splitlines()[-1]] if STATE.error else []),
                    "live": live, "paused": live is None or live["age"] > LIVE_STALE,
                }))
            m = TILE_RE.match(path)
            if m:
                world, z, x, y = m.groups()
                return self.send_file(os.path.join(config.TILES, world, z, "%s_%s.png" % (x, y)), "image/png")
            m = re.match(r"^/heads/([0-9a-f-]{32,36})\.png$", path)
            if m:
                skin = skin_for(m.group(1)).replace("/", "_")
                return self.send_file(os.path.join(config.WEB, "assets", "heads", skin + ".png"), "image/png")
            m = re.match(r"^/fullmap/([a-z0-9_]+)\.png$", path)
            if m:
                return self.send_file(os.path.join(config.DATA, "fullmap", m.group(1) + ".png"), "image/png")
            # the page and its assets
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(config.WEB, rel))
            if not full.startswith(os.path.realpath(config.WEB) + os.sep) or not os.path.isfile(full):
                return self.send_error(404)
            return self.send_file(full)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    global STATE
    STATE = State()
    try:
        STATE.refresh()
    except Exception:
        STATE.error = traceback.format_exc(limit=3)
        print(STATE.error, flush=True)
    threading.Thread(target=STATE.loop, daemon=True).start()
    host, port = config.BIND.rsplit(":", 1)
    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    httpd.daemon_threads = True
    print("serving on http://%s:%s/" % (host, port), flush=True)
    httpd.serve_forever()
