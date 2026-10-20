"""Event store (SQLite). Two sources feed it:

- the WorldDashboard plugin's events.jsonl (joins, quits, deaths with position, server start/stop);
- server logs, for the time before the plugin was installed.

Once the plugin has written its first event, log events from that moment on are ignored, so
nothing is counted twice.
"""
import json
import os
import sqlite3
import threading

from . import config, logs
from .util import load_json

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,            -- unix seconds
    type TEXT NOT NULL,          -- join, quit, death, server_start, server_ready, server_stop
    level TEXT,                  -- save folder the server was running
    name TEXT, uuid TEXT,
    world TEXT, x REAL, y REAL, z REAL,
    data TEXT,                   -- JSON: message, killer, ...
    source TEXT NOT NULL,        -- 'plugin' or 'log'
    UNIQUE (source, type, name, ts)
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path=None):
        path = path or os.path.join(config.DATA, "dashboard.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    # ---------- meta ----------

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))

    # ---------- ingest ----------

    def _insert(self, e, source):
        cur = self.db.execute(
            "INSERT OR IGNORE INTO events (ts, type, level, name, uuid, world, x, y, z, data, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e["ts"], e["type"], e.get("level"), e.get("name"), e.get("uuid"), e.get("world"),
             e.get("x"), e.get("y"), e.get("z"), json.dumps(e["data"], ensure_ascii=False) if e.get("data") else None,
             source))
        return cur.rowcount

    def ingest_plugin(self):
        """Append new lines of the plugin's events.jsonl. Returns the number of new events."""
        path = os.path.join(config.PLUGIN_DIR, "events.jsonl")
        try:
            size = os.path.getsize(path)
        except OSError:
            return 0
        offset = self.meta("plugin_offset", 0)
        if size < offset:  # file was replaced or truncated
            offset = 0
        if size == offset:
            return 0
        added = 0
        with open(path, "rb") as f, self.lock:
            f.seek(offset)
            chunk = f.read(size - offset)
            end = chunk.rfind(b"\n") + 1  # only whole lines
            for line in chunk[:end].splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                e["ts"] = e["ts"] / 1000.0
                added += self._insert(e, "plugin")
                if self.meta("plugin_since") is None:
                    self.set_meta("plugin_since", e["ts"])
            self.set_meta("plugin_offset", offset + end)
            self.db.commit()
        return added

    def ingest_logs(self, players):
        """Import server logs: every rotated log once, latest.log on every call."""
        done = set(self.meta("logs_done", []))
        todo = [(d, p) for d, p in logs.log_files() if d is None or os.path.basename(p) not in done]
        if not todo:
            return 0
        added = 0
        with self.lock:
            for e in logs.events_from(todo, set(players)):
                added += self._insert(e, "log")
            done |= {os.path.basename(p) for d, p in todo if d is not None}
            self.set_meta("logs_done", sorted(done))
            self.db.commit()
        if added:
            self._attach_legacy_positions()
        return added

    def _attach_legacy_positions(self):
        """Death positions known before this backend: the old DeathMarkers file and the dashboard's
        last-death pins. Fills them into log deaths that have none."""
        known = []
        for g in load_json(os.path.join(config.MC, "plugins/DeathMarkers/deaths.json"), []) or []:
            known.append((g["name"], g["ts"] / 1000.0, g["world"], g["x"], g["y"], g["z"], 5))
        pins = (load_json(os.path.join(config.DATA, "death_coords.json"), {}) or {}).get("pins", {})
        for key, pin in pins.items():
            ts, name = int(key[:10]), key[10:]
            known.append((name, ts, pin["dim"], pin["pos"][0], pin["pos"][1], pin["pos"][2], 1))
        with self.lock:
            for name, ts, world, x, y, z, slack in known:
                self.db.execute(
                    "UPDATE events SET world = ?, x = ?, y = ?, z = ? WHERE type = 'death' AND source = 'log'"
                    " AND name = ? AND x IS NULL AND ABS(ts - ?) <= ?", (world, x, y, z, name, ts, slack))
            self.db.commit()

    # ---------- queries ----------

    def events(self, types=None):
        """Events in time order, logs only up to the moment the plugin took over."""
        since = self.meta("plugin_since")
        q = "SELECT * FROM events WHERE (source = 'plugin' OR ? IS NULL OR ts < ?)"
        args = [since, since]
        if types:
            q += " AND type IN (%s)" % ",".join("?" * len(types))
            args += list(types)
        q += " ORDER BY ts, id"
        out = []
        for r in self.db.execute(q, args):
            e = dict(r)
            e["data"] = json.loads(e["data"]) if e["data"] else {}
            out.append(e)
        return out

    def version(self):
        """Changes whenever an event is added (for cache invalidation)."""
        row = self.db.execute("SELECT COUNT(*), MAX(id) FROM events").fetchone()
        return (row[0], row[1], self.meta("plugin_since"))
