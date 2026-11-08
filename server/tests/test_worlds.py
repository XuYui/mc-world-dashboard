import json
import socket
import threading
import unittest

import support  # noqa: F401  (sets up the environment first)
from mcdash import config, worlds


class AdminPasswordTest(unittest.TestCase):
    def tearDown(self):
        config.ADMIN_PASSWORD = ""

    def test_hash_round_trip(self):
        config.ADMIN_PASSWORD = worlds.hash_password("correct horse")
        self.assertTrue(worlds.check_admin("correct horse"))
        self.assertFalse(worlds.check_admin("wrong"))
        self.assertFalse(worlds.check_admin(""))

    def test_unset_or_malformed_hash_rejects_everything(self):
        for stored in ("", "plain", "md5:1:00:00"):
            config.ADMIN_PASSWORD = stored
            self.assertFalse(worlds.check_admin("plain"))


class PingTest(unittest.TestCase):
    def serve(self, status):
        """A one-shot fake game server answering the status ping with `status`."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)

        def run():
            conn, _ = srv.accept()
            with conn:
                conn.recv(1024)
                body = json.dumps(status).encode()
                packet = worlds._varint(0) + worlds._varint(len(body)) + body
                conn.sendall(worlds._varint(len(packet)) + packet)
            srv.close()

        threading.Thread(target=run, daemon=True).start()
        return srv.getsockname()[1]

    def test_reads_players_and_version(self):
        port = self.serve({"version": {"name": "1.21.1"},
                           "players": {"online": 2, "max": 4, "sample": [{"name": "xu"}, {"name": "why"}]}})
        self.assertEqual(worlds.ping(port=port),
                         {"online": 2, "max": 4, "names": ["xu", "why"], "version": "1.21.1"})

    def test_nothing_listening(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertIsNone(worlds.ping(port=port, timeout=0.5))


if __name__ == "__main__":
    unittest.main()
