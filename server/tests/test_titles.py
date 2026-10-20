import unittest

import support  # noqa: F401  (sets up the environment first)

from mcdash.titles import titles


def stats(logs=0, deaths=0, jumps=0):
    return {
        "minecraft:custom": {"minecraft:deaths": deaths, "minecraft:jump": jumps},
        "minecraft:mined": {"minecraft:oak_log": logs},
    }


def won(badges, name):
    return [b["title"] for b in badges[name]]


class Titles(unittest.TestCase):
    def test_clear_winner_gets_the_title(self):
        assigned, badges = titles({"alex": stats(logs=300), "bob": stats(logs=10)})
        self.assertIn("伐木工", won(badges, "alex"))
        self.assertNotIn("伐木工", won(badges, "bob"))

    def test_ties_and_zeros_give_no_title(self):
        _, badges = titles({"alex": stats(logs=50), "bob": stats(logs=50)})
        self.assertNotIn("伐木工", won(badges, "alex") + won(badges, "bob"))
        _, badges = titles({"alex": stats(), "bob": stats()})
        self.assertNotIn("跳跳虎", won(badges, "alex") + won(badges, "bob"))

    def test_fewest_deaths(self):
        _, badges = titles({"alex": stats(deaths=40), "bob": stats(deaths=3)})
        self.assertIn("苟王", won(badges, "bob"))
        self.assertIn("敢死队长", won(badges, "alex"))

    def test_headline_is_the_widest_lead(self):
        assigned, _ = titles({"alex": stats(logs=1000, jumps=110), "bob": stats(logs=10, jumps=100)})
        self.assertEqual(assigned["alex"], "伐木工")  # 1000 vs 10 beats 110 vs 100

    def test_single_player_gets_nothing(self):
        assigned, badges = titles({"alex": stats(logs=5)})
        self.assertEqual(assigned, {})
        self.assertEqual(badges["alex"], [])


if __name__ == "__main__":
    unittest.main()
