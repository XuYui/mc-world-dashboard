"""Server logs -> events, for the history before the WorldDashboard plugin was installed.

Rotated logs are copied into DATA/logs because the server deletes old ones.
"""
import glob
import gzip
import os
import re
import shutil
from datetime import datetime, timedelta

from . import config
from .gamedata import DEATHS, zh_name

LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\] \[Server thread/INFO\]: (.*)$")


def archive_dir():
    d = os.path.join(config.DATA, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def log_files():
    """[(date or None for latest.log, path)] oldest first; copies rotated logs into the archive."""
    archive = archive_dir()
    by_name = {}
    for p in glob.glob(os.path.join(archive, "*.log.gz")) + glob.glob(os.path.join(config.MC, "logs/*.log.gz")):
        by_name.setdefault(os.path.basename(p), p)
    for name, p in list(by_name.items()):
        if os.path.dirname(p) != archive:
            dst = os.path.join(archive, name)
            shutil.copyfile(p, dst)
            os.chmod(dst, 0o640)
            by_name[name] = dst
    files = []
    for name, p in by_name.items():
        m = re.match(r"(\d{4}-\d\d-\d\d)-(\d+)\.log\.gz$", name)
        if m:
            files.append((m.group(1), int(m.group(2)), p))
    files.sort()
    out = [(d, p) for d, _, p in files]
    latest = os.path.join(config.MC, "logs/latest.log")
    if os.path.exists(latest):
        out.append((None, latest))
    return out


def _timed_lines(date, path):
    """(unix_ts, message) for server-thread lines, handling midnight rollover."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        rows = []
        for line in f:
            m = LINE.match(line.rstrip("\n"))
            if m:
                rows.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), m.group(4)))
    if not rows:
        return []
    tz = config.TZ
    if date is None:
        # latest.log has no date in its name: anchor its last line to the file's mtime.
        mt = datetime.fromtimestamp(os.path.getmtime(path), tz)
        day = mt.date()
        if rows[-1][0] > mt.hour * 3600 + mt.minute * 60 + mt.second + 60:
            day -= timedelta(days=1)
        rolls = sum(1 for a, b in zip(rows, rows[1:]) if b[0] < a[0])
        start = day - timedelta(days=rolls)
    else:
        start = datetime.strptime(date, "%Y-%m-%d").date()
    out, day, prev = [], start, -1
    for sec, msg in rows:
        if sec < prev:
            day += timedelta(days=1)
        prev = sec
        base = datetime(day.year, day.month, day.day, tzinfo=tz).timestamp()
        out.append((int(base) + sec, msg))
    return out


def _death_text(msg, first, players):
    for rx, d in DEATHS:
        mm = rx.match(msg)
        if mm and mm.group("a1") == first:
            args = mm.groupdict()
            text = d["zh"]
            for i in range(1, 4):
                v = args.get("a%d" % i)
                if v is not None:
                    v = v if v in players else zh_name(v.strip("[]"))
                    text = text.replace("%%%d$s" % i, v)
            killer = args.get("a2")
            return text.replace("%s", ""), (zh_name(killer) if killer and killer not in players else killer)
    return None, None


def events_from(files, players):
    """Events (dicts with ts in seconds) from the given log files. `players` are known names;
    only their joins, quits and deaths are recognised."""
    level = None
    out = []
    for date, path in files:
        for ts, msg in _timed_lines(date, path):
            if msg.startswith("Preparing level "):
                level = msg.split('"')[1] if '"' in msg else None
                continue
            if msg.startswith("Starting minecraft server"):
                out.append({"ts": ts, "type": "server_start", "level": level})
                continue
            if msg.startswith("Done (") and "For help" in msg:
                out.append({"ts": ts, "type": "server_ready", "level": level})
                continue
            if msg.startswith("Stopping server"):
                out.append({"ts": ts, "type": "server_stop", "level": level})
                continue
            m = re.match(r"^(\S+) (joined|left) the game$", msg)
            if m and m.group(1) in players:
                out.append({"ts": ts, "type": "join" if m.group(2) == "joined" else "quit",
                            "level": level, "name": m.group(1)})
                continue
            first = msg.split(" ", 1)[0]
            if first in players:
                text, killer = _death_text(msg, first, players)
                if text:
                    out.append({"ts": ts, "type": "death", "level": level, "name": first,
                                "data": {"message": text, "killer": killer}})
    return out
