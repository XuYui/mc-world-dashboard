import os
import tempfile
import unittest

import support

from mcdash.store import Store


class EventStore(unittest.TestCase):
    def setUp(self):
        # fresh logs and log archive for every test
        for d in (os.path.join(support.SERVER, "logs"), os.path.join(support.DATA, "logs")):
            for name in os.listdir(d) if os.path.isdir(d) else []:
                os.remove(os.path.join(d, name))
        for name in ("events.jsonl",):
            p = os.path.join(support.PLUGIN, name)
            if os.path.exists(p):
                os.remove(p)
        self.store = Store(os.path.join(tempfile.mkdtemp(dir=support.ROOT), "test.db"))
        self.store.set_meta("logs_done", [])

    def test_logs_import_once(self):
        support.write_log("2026-10-05-1.log.gz", [
            ('10:00:00', 'Preparing level "world"'),
            ("10:01:00", "alex joined the game"),
            ("10:02:00", "alex left the game"),
        ])
        self.assertEqual(self.store.ingest_logs(["alex"]), 2)
        self.assertEqual(self.store.ingest_logs(["alex"]), 0)  # rotated logs are read only once
        self.assertEqual([e["type"] for e in self.store.events()], ["join", "quit"])

    def test_plugin_events_take_over_from_logs(self):
        support.write_log("2026-10-06-1.log.gz", [
            ('10:00:00', 'Preparing level "world"'),
            ("10:01:00", "alex joined the game"),
            ("12:00:00", "alex joined the game"),  # after the plugin took over: must be ignored
        ])
        self.store.ingest_logs(["alex"])
        log_join = self.store.events()[0]["ts"]
        plugin_ts = (log_join + 3600) * 1000
        support.write_plugin_events([
            {"ts": plugin_ts, "type": "server_start", "level": "world"},
            {"ts": plugin_ts + 5000, "type": "death", "level": "world", "name": "alex", "uuid": "u",
             "world": "minecraft:overworld", "x": 1.5, "y": 64, "z": -2.5, "data": {"message": "alex died"}},
        ])
        self.assertEqual(self.store.ingest_plugin(), 2)
        types = [(e["source"], e["type"]) for e in self.store.events()]
        self.assertEqual(types, [("log", "join"), ("plugin", "server_start"), ("plugin", "death")])
        death = self.store.events(["death"])[0]
        self.assertEqual((death["world"], death["x"], death["z"]), ("minecraft:overworld", 1.5, -2.5))

    def test_partial_lines_wait_for_the_rest(self):
        path = support.write_plugin_events([{"ts": 1_800_000_000_000, "type": "server_start", "level": "world"}])
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"ts": 1800000001000, "type": "jo')  # still being written
        self.assertEqual(self.store.ingest_plugin(), 1)
        with open(path, "a", encoding="utf-8") as f:
            f.write('in", "level": "world", "name": "alex"}\n')
        self.assertEqual(self.store.ingest_plugin(), 1)
        self.assertEqual([e["type"] for e in self.store.events()], ["server_start", "join"])


if __name__ == "__main__":
    unittest.main()
