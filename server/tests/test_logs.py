import unittest
from datetime import datetime

from support import write_log  # noqa: F401  (sets up the environment first)
import support

from mcdash import config, logs


def ts(day, hms):
    return int(datetime.strptime("2026-10-%02d %s" % (day, hms), "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.TZ).timestamp())


class LogParsing(unittest.TestCase):
    def test_events_from_a_rotated_log(self):
        path = support.write_log("2026-10-01-1.log.gz", [
            ("21:59:58", "Starting minecraft server version 26.1.2"),
            ("21:59:59", 'Preparing level "world"'),
            ("22:00:00", 'Done (3.2s)! For help, type "help"'),
            ("22:00:05", "alex joined the game"),
            ("22:00:06", "<alex> alex was slain by Zombie"),  # chat, not a death
            ("22:10:00", "alex was slain by Zombie"),
            ("22:11:00", "stranger fell from a high place"),  # not a known player
            ("22:30:00", "alex left the game"),
            ("22:31:00", "Stopping server"),
        ])
        events = logs.events_from([("2026-10-01", path)], {"alex"})
        self.assertEqual([e["type"] for e in events],
                         ["server_start", "server_ready", "join", "death", "quit", "server_stop"])
        death = events[3]
        self.assertEqual(death["ts"], ts(1, "22:10:00"))
        self.assertEqual(death["data"]["message"], "alex被僵尸杀死了")
        self.assertEqual(death["data"]["killer"], "僵尸")
        self.assertEqual(events[2]["level"], "world")

    def test_midnight_rollover(self):
        path = support.write_log("2026-10-02-1.log.gz", [
            ('23:59:00', 'Preparing level "world"'),
            ("23:59:30", "alex joined the game"),
            ("00:00:30", "alex left the game"),
        ])
        events = logs.events_from([("2026-10-02", path)], {"alex"})
        self.assertEqual(events[0]["ts"], ts(2, "23:59:30"))
        self.assertEqual(events[1]["ts"], ts(3, "00:00:30"))

    def test_other_saves_are_tagged_with_their_level(self):
        path = support.write_log("2026-10-04-1.log.gz", [
            ('10:00:00', 'Preparing level "other_world"'),
            ("10:01:00", "alex joined the game"),
        ])
        events = logs.events_from([("2026-10-04", path)], {"alex"})
        self.assertEqual(events[0]["level"], "other_world")


if __name__ == "__main__":
    unittest.main()
