import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from trading_helper.pip_stream import HEIGHT, WIDTH, PipStream, find_ffmpeg
from trading_helper.remote_control import MobileServer, RemoteStore
from trading_helper.remote_mobile import ASSETS, JS
import test_mobile_remote as phone_tests


class PipStreamTests(unittest.TestCase):
    def test_without_ffmpeg_nothing_is_offered(self):
        stream = PipStream(lambda: b"", ffmpeg="")
        self.assertEqual(stream.path, "")
        self.assertIsNone(stream.read(stream.token, "live.m3u8"))

    def test_only_its_own_token_and_file_names_are_served(self):
        stream = PipStream(lambda: b"", ffmpeg="ffmpeg")
        with patch.object(stream, "start") as start:
            self.assertIsNone(stream.read("0" * 32, "live.m3u8"))
            self.assertIsNone(stream.read(stream.token, "../secret.txt"))
            start.assert_not_called()
        self.assertEqual(stream.path, f"/pip/live/{stream.token}/live.m3u8")

    def test_stops_after_a_minute_without_requests(self):
        stream = PipStream(lambda: b"x", ffmpeg="ffmpeg")
        with patch.object(PipStream, "running", True), patch.object(stream, "stop") as stop:
            stream.last_request = time.monotonic() - 61
            stream.tick()
        stop.assert_called_once()

    def test_phone_prefers_the_computer_stream(self):
        self.assertIn("function pipUseStream(v)", JS)
        self.assertIn("v.src=url", JS)

    @unittest.skipUnless(find_ffmpeg(), "ffmpeg not installed")
    def test_real_ffmpeg_produces_a_live_playlist(self):
        stream = PipStream(lambda: b"\x20" * (WIDTH * HEIGHT * 4))
        stream.last_request = time.monotonic()
        stream.start()
        try:
            for _ in range(10):
                stream.tick()
                time.sleep(0.5)
            playlist = stream.read(stream.token, "live.m3u8")
            self.assertIn(b"#EXTM3U", playlist)
            segment = [line for line in playlist.decode().splitlines() if line.endswith(".ts")][-1]
            self.assertTrue(stream.read(stream.token, segment))
        finally:
            folder = stream.dir
            stream.stop()
        self.assertFalse(os.path.exists(folder))


class PipStreamRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RemoteStore(Path(self.temp.name) / "remote.db")
        self.server = MobileServer(self.store, ASSETS)
        self.server.start(port=0)

    def tearDown(self):
        self.server.stop()
        self.qtapp.processEvents()
        self.store.db.close()
        self.temp.cleanup()

    http = phone_tests.MobileTransportTests.http

    def test_stream_route_serves_playlist_with_media_types(self):
        class Fake:
            def read(self, token, name):
                return b"#EXTM3U" if token == "a" * 32 else None
        self.server.pip_stream = Fake()
        status, headers, body = self.http(path="/pip/live/" + "a" * 32 + "/live.m3u8")
        self.assertEqual((status, body), (200, b"#EXTM3U"))
        self.assertEqual(headers["Content-Type"], "application/vnd.apple.mpegurl")
        self.assertIn("media-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.http(path="/pip/live/" + "b" * 32 + "/live.m3u8")[0], 404)
        self.assertEqual(self.http(path="/pip/live/" + "a" * 32 + "/x.ts")[0], 404)


if __name__ == "__main__":
    unittest.main()
