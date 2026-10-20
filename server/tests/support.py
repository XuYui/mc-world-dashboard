"""Test setup: a throwaway Paper server directory and data directory, configured through the
same environment variables production uses. Import this before anything from mcdash."""
import gzip
import json
import os
import tempfile

ROOT = tempfile.mkdtemp(prefix="mcdash-test-")
SERVER = os.path.join(ROOT, "server")
DATA = os.path.join(ROOT, "data")
PLUGIN = os.path.join(SERVER, "plugins", "WorldDashboard")
for d in (os.path.join(SERVER, "logs"), DATA, PLUGIN):
    os.makedirs(d, exist_ok=True)

os.environ.update({
    "DASH_SERVER_DIR": SERVER,
    "DASH_WORLD": "world",
    "DASH_DATA_DIR": DATA,
    "DASH_PLUGIN_DIR": PLUGIN,
    "DASH_TILE_DIR": os.path.join(ROOT, "tiles"),
    "DASH_DEFS": os.path.join(os.path.dirname(__file__), "fixtures", "defs.json"),
    "DASH_UTC_OFFSET": "8",
})


def write_log(name, lines):
    """Write a server log (gzipped if the name ends in .gz) under SERVER/logs."""
    path = os.path.join(SERVER, "logs", name)
    text = "".join("[%s] [Server thread/INFO]: %s\n" % (t, msg) for t, msg in lines)
    if name.endswith(".gz"):
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(text)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return path


def write_plugin_events(events, append=False):
    path = os.path.join(PLUGIN, "events.jsonl")
    with open(path, "a" if append else "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return path
