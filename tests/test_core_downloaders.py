from __future__ import annotations

import http.server
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from anirss.core.downloaders import (
    DownloadControl,
    DownloadError,
    HttpDownloader,
    LibtorrentDownloader,
    LibtorrentUnavailableError,
    classify_download,
)
from anirss.core.models import AppSettings, DownloadKind, DownloadTask

PAYLOAD = b"AniRSS download test\n" * 4096


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, _format: str, *args: object) -> None:
        return


class _WrongRangeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(206)
        self.send_header("Content-Range", "bytes 0-9/10")
        self.send_header("Content-Length", "10")
        self.end_headers()
        self.wfile.write(b"0123456789")

    def log_message(self, _format: str, *args: object) -> None:
        return


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        range_header = self.headers.get("Range", "")
        start = int(range_header.removeprefix("bytes=").removesuffix("-"))
        body = PAYLOAD[start:]
        self.send_response(206)
        self.send_header(
            "Content-Range",
            f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


class DownloaderTests(unittest.TestCase):
    def test_http_downloader_completes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                task = DownloadTask(
                    subscription_id=1,
                    feed_item_id=1,
                    title="Episode",
                    source_url=f"http://127.0.0.1:{port}/episode.mkv",
                    destination_directory=temporary,
                    filename="episode.mkv",
                )
                progress: list[float] = []
                result = HttpDownloader().download(
                    task,
                    AppSettings(download_root=temporary),
                    DownloadControl(),
                    lambda _done, _total, value: progress.append(value),
                )
                self.assertEqual(result.path.read_bytes(), PAYLOAD)
                self.assertFalse(Path(temporary, "episode.mkv.part").exists())
                self.assertEqual(progress[-1], 1.0)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_http_resume_rejects_a_mismatched_content_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _WrongRangeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            partial = Path(temporary, "episode.mkv.part")
            partial.write_bytes(b"01234")
            try:
                port = server.server_address[1]
                task = DownloadTask(
                    subscription_id=1,
                    feed_item_id=1,
                    title="Episode",
                    source_url=f"http://127.0.0.1:{port}/episode.mkv",
                    destination_directory=temporary,
                    filename="episode.mkv",
                )
                with self.assertRaisesRegex(DownloadError, "expected 5"):
                    HttpDownloader().download(
                        task,
                        AppSettings(download_root=temporary),
                        DownloadControl(),
                    )
                self.assertEqual(partial.read_bytes(), b"01234")
                self.assertFalse(Path(temporary, "episode.mkv").exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_http_resume_accepts_an_exact_content_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            partial = Path(temporary, "episode.mkv.part")
            partial.write_bytes(PAYLOAD[:1024])
            try:
                port = server.server_address[1]
                task = DownloadTask(
                    subscription_id=1,
                    feed_item_id=1,
                    title="Episode",
                    source_url=f"http://127.0.0.1:{port}/episode.mkv",
                    destination_directory=temporary,
                    filename="episode.mkv",
                )
                result = HttpDownloader().download(
                    task,
                    AppSettings(download_root=temporary),
                    DownloadControl(),
                )
                self.assertEqual(result.path.read_bytes(), PAYLOAD)
                self.assertEqual(result.total_bytes, len(PAYLOAD))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_download_kind_classification(self) -> None:
        self.assertEqual(classify_download("magnet:?xt=urn:btih:abc"), DownloadKind.MAGNET)
        self.assertEqual(
            classify_download("https://example.test/a.torrent?key=1"),
            DownloadKind.TORRENT,
        )
        self.assertEqual(classify_download("https://example.test/a.mkv"), DownloadKind.HTTP)
        self.assertEqual(
            classify_download(
                "https://example.test/download.php?id=1",
                "application/x-bittorrent; charset=binary",
            ),
            DownloadKind.TORRENT,
        )

    def test_libtorrent_import_error_is_actionable(self) -> None:
        with (
            patch(
                "anirss.core.downloaders.importlib.import_module",
                side_effect=ImportError("not installed"),
            ),
            self.assertRaisesRegex(LibtorrentUnavailableError, "optional 'libtorrent'"),
        ):
            LibtorrentDownloader._load_libtorrent()

    def test_torrent_url_is_fetched_and_loaded_for_libtorrent_2(self) -> None:
        class Params:
            save_path = ""

        class Status:
            progress = 1.0
            total_wanted_done = len(PAYLOAD)
            total_wanted = len(PAYLOAD)
            is_seeding = True
            errc = None

        class Handle:
            def status(self) -> Status:
                return Status()

            def pause(self) -> None:
                return None

            def resume(self) -> None:
                return None

        class Session:
            def __init__(self) -> None:
                self.added: object | None = None

            def apply_settings(self, _settings: object) -> None:
                return None

            def add_torrent(self, parameters: object) -> Handle:
                self.added = parameters
                return Handle()

            def remove_torrent(self, _handle: Handle) -> None:
                return None

        class FakeLibtorrent:
            last_session: Session | None = None

            @classmethod
            def session(cls) -> Session:
                cls.last_session = Session()
                return cls.last_session

            @staticmethod
            def load_torrent_buffer(data: bytes) -> Params:
                if data != PAYLOAD:
                    raise AssertionError("metadata was not fetched intact")
                return Params()

        with tempfile.TemporaryDirectory() as temporary:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                task = DownloadTask(
                    subscription_id=1,
                    feed_item_id=1,
                    title="Torrent",
                    source_url=f"http://127.0.0.1:{port}/download.php?id=1",
                    destination_directory=temporary,
                    filename="episode.torrent",
                    kind=DownloadKind.TORRENT,
                )
                with patch.object(
                    LibtorrentDownloader,
                    "_load_libtorrent",
                    return_value=FakeLibtorrent,
                ):
                    result = LibtorrentDownloader().download(
                        task,
                        AppSettings(download_root=temporary),
                        DownloadControl(),
                    )
                self.assertEqual(result.downloaded_bytes, len(PAYLOAD))
                session = FakeLibtorrent.last_session
                assert session is not None
                self.assertIsInstance(session.added, Params)
                parameters = session.added
                assert isinstance(parameters, Params)
                self.assertEqual(
                    parameters.save_path,
                    str(Path(temporary).resolve()),
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_torrent_tasks_share_one_libtorrent_session(self) -> None:
        class Params:
            save_path = ""

        class Status:
            progress = 1.0
            total_wanted_done = len(PAYLOAD)
            total_wanted = len(PAYLOAD)
            is_seeding = True
            errc = None
            num_peers = 1
            num_seeds = 1

        class Handle:
            def status(self) -> Status:
                return Status()

            def has_metadata(self) -> bool:
                return True

            def pause(self) -> None:
                return None

            def resume(self) -> None:
                return None

        class Session:
            def __init__(self) -> None:
                self.added = 0
                self.removed = 0

            def apply_settings(self, _settings: object) -> None:
                return None

            def add_torrent(self, _parameters: object) -> Handle:
                self.added += 1
                return Handle()

            def remove_torrent(self, _handle: Handle) -> None:
                self.removed += 1

        class FakeLibtorrent:
            session_calls = 0
            shared_session = Session()

            @classmethod
            def session(cls, _parameters: object | None = None) -> Session:
                cls.session_calls += 1
                return cls.shared_session

            @staticmethod
            def parse_magnet_uri(_url: str) -> Params:
                return Params()

        with tempfile.TemporaryDirectory() as temporary:
            downloader = LibtorrentDownloader()
            settings = AppSettings(download_root=temporary)
            with patch.object(
                LibtorrentDownloader,
                "_load_libtorrent",
                return_value=FakeLibtorrent,
            ):
                for item_id in (1, 2):
                    task = DownloadTask(
                        subscription_id=1,
                        feed_item_id=item_id,
                        title=f"Magnet {item_id}",
                        source_url=f"magnet:?xt=urn:btih:{item_id:040d}",
                        destination_directory=temporary,
                        filename=f"{item_id}.mkv",
                        kind=DownloadKind.MAGNET,
                    )
                    downloader.download(task, settings, DownloadControl())

            self.assertEqual(FakeLibtorrent.session_calls, 1)
            self.assertEqual(FakeLibtorrent.shared_session.added, 2)
            self.assertEqual(FakeLibtorrent.shared_session.removed, 2)

    def test_magnet_metadata_timeout_releases_handle(self) -> None:
        class Params:
            save_path = ""

        class Status:
            progress = 0.0
            total_wanted_done = 0
            total_wanted = 0
            is_seeding = False
            errc = None
            num_peers = 0
            num_seeds = 0

        class Handle:
            def status(self) -> Status:
                return Status()

            def has_metadata(self) -> bool:
                return False

            def pause(self) -> None:
                return None

            def resume(self) -> None:
                return None

        class Session:
            removed = 0

            def apply_settings(self, _settings: object) -> None:
                return None

            def add_torrent(self, _parameters: object) -> Handle:
                return Handle()

            def remove_torrent(self, _handle: Handle) -> None:
                self.removed += 1

        class FakeLibtorrent:
            shared_session = Session()

            @classmethod
            def session(cls, _parameters: object | None = None) -> Session:
                return cls.shared_session

            @staticmethod
            def parse_magnet_uri(_url: str) -> Params:
                return Params()

        with tempfile.TemporaryDirectory() as temporary:
            task = DownloadTask(
                subscription_id=1,
                feed_item_id=1,
                title="No metadata",
                source_url="magnet:?xt=urn:btih:0000000000000000000000000000000000000001",
                destination_directory=temporary,
                filename="episode.mkv",
                kind=DownloadKind.MAGNET,
            )
            settings = AppSettings(download_root=temporary)
            cast(Any, settings).bt_metadata_timeout_seconds = 0.01
            downloader = LibtorrentDownloader()
            downloader.poll_seconds = 0.005
            with (
                patch.object(
                    LibtorrentDownloader,
                    "_load_libtorrent",
                    return_value=FakeLibtorrent,
                ),
                self.assertRaisesRegex(DownloadError, "metadata timed out"),
            ):
                downloader.download(task, settings, DownloadControl())
            self.assertEqual(FakeLibtorrent.shared_session.removed, 1)


if __name__ == "__main__":
    unittest.main()
