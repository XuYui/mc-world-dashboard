import unittest

import support  # noqa: F401  (sets up the environment first)

from mcdash import report

T0 = 1_800_000_000


def ev(t, type_, name=None, level="world"):
    return {"ts": T0 + t, "type": type_, "name": name, "level": level}


class Sessions(unittest.TestCase):
    def build(self, events, names=("alex", "bob"), now=T0 + 100_000):
        intervals, online = report.presence(events, list(names))
        return report.build_sessions(intervals, [], {}, {}, {}, now), online

    def test_short_gaps_merge_and_long_gaps_split(self):
        sessions, _ = self.build([
            ev(0, "join", "alex"), ev(600, "quit", "alex"),
            ev(600 + 14 * 60, "join", "alex"), ev(3000, "quit", "alex"),     # 14 min gap: same session
            ev(3000 + 16 * 60, "join", "alex"), ev(6000, "quit", "alex"),    # 16 min gap: new session
        ])
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["start"], T0)
        self.assertEqual(sessions[0]["players"][0]["secs"], 600 + (3000 - 600 - 14 * 60))

    def test_multi_player_and_solo(self):
        sessions, _ = self.build([
            ev(0, "join", "alex"), ev(100, "join", "bob"), ev(500, "quit", "bob"), ev(900, "quit", "alex"),
            ev(10_000, "join", "bob"), ev(11_000, "quit", "bob"),
        ])
        self.assertTrue(sessions[0]["multi"])
        self.assertFalse(sessions[1]["multi"])
        self.assertEqual(sessions[1]["headline"], "bob 独自游玩")

    def test_server_stop_closes_open_visits(self):
        sessions, online = self.build([ev(0, "join", "alex"), ev(300, "server_stop", level=None)])
        self.assertEqual(sessions[0]["end"], T0 + 300)
        self.assertFalse(online)

    def test_still_online_is_ongoing(self):
        sessions, online = self.build([ev(0, "join", "alex")], now=T0 + 120)
        self.assertTrue(sessions[0]["ongoing"])
        self.assertIsNone(sessions[0]["end"])
        self.assertIn("alex", online)

    def test_other_saves_are_ignored(self):
        sessions, _ = self.build([ev(0, "join", "alex", level="other"), ev(60, "quit", "alex", level="other")])
        self.assertEqual(sessions, [])


class Killers(unittest.TestCase):
    def test_killer_is_read_back_from_plugin_messages(self):
        from mcdash.gamedata import killer_from_message
        self.assertEqual(killer_from_message("alex被僵尸杀死了", {"alex"}), "僵尸")
        self.assertIsNone(killer_from_message("alex从高处摔了下来", {"alex"}))


if __name__ == "__main__":
    unittest.main()
