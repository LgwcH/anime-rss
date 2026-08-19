from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from PySide6.QtWidgets import QApplication

from anirss.core.database import SQLiteRepository
from anirss.core.service import AniRSSService
from anirss.desktop_controller import DesktopController

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example</title><item>
  <guid>episode-1</guid><title>Example [01] [1080P] [CHS]</title>
  <enclosure url="https://media.invalid/example-01.mkv" type="video/x-matroska" />
</item></channel></rss>
"""


class DesktopControllerTests(unittest.TestCase):
    qt_app: ClassVar[QApplication]

    @classmethod
    def setUpClass(cls) -> None:
        existing = QApplication.instance()
        cls.qt_app = existing if isinstance(existing, QApplication) else QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteRepository(":memory:")
        self.service = AniRSSService(
            repository=self.repository,
            feed_fetcher=lambda _url, _settings: FEED,
        )
        self.controller = DesktopController(self.service)
        self.controller.save_settings(
            {
                "download_directory": self.temporary.name,
                "poll_interval_minutes": 20,
                "seed_after_complete": False,
                "theme": "dark",
            }
        )

    def tearDown(self) -> None:
        self.controller.close()
        self.repository.close()
        self.temporary.cleanup()

    def test_ui_fields_round_trip_and_default_show_directory(self) -> None:
        saved = self.controller.save_subscription(
            {
                "name": "Example Anime",
                "rss_url": "https://feeds.invalid/example.xml",
                "save_path": "",
                "include_keywords": ["1080P", "CHS"],
                "exclude_keywords": ["Preview"],
                "episode_regex": r"\[(\d+)\]",
                "auto_download": True,
                "enabled": True,
            }
        )

        self.assertEqual(saved["include_keywords"], ["1080P", "CHS"])
        self.assertEqual(saved["exclude_keywords"], ["Preview"])
        self.assertEqual(saved["save_path"], "")
        self.assertEqual(
            Path(saved["resolved_save_path"]),
            Path(self.temporary.name).resolve() / "Example Anime",
        )
        stored = self.service.list_subscriptions()[0]
        self.assertIsNone(stored.save_directory)
        self.assertTrue(Path(saved["resolved_save_path"]).is_dir())

    def test_refresh_task_mapping_and_real_removal(self) -> None:
        self.controller.save_subscription(
            {
                "name": "Example Anime",
                "rss_url": "https://feeds.invalid/example.xml",
                "include_keywords": ["1080P"],
                "auto_download": True,
                "download_existing": True,
            }
        )
        created = self.controller.refresh_all()
        self.assertEqual(len(created), 1)
        downloads = self.controller.list_downloads("queued")
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]["anime"], "Example Anime")
        self.assertEqual(downloads[0]["episode"], "01")
        self.assertTrue(self.controller.remove_download(downloads[0]["id"]))
        self.assertEqual(self.controller.list_downloads(), [])

    def test_subscription_details_and_manual_download_mapping(self) -> None:
        saved = self.controller.save_subscription(
            {
                "name": "Manual Anime",
                "rss_url": "https://feeds.invalid/manual.xml",
                "include_keywords": ["Never matches"],
                "auto_download": False,
            }
        )
        subscription_id = saved["id"]
        self.assertEqual(self.controller.refresh_subscription(subscription_id), [])

        items = self.controller.list_subscription_items(subscription_id)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["matches_rules"])
        self.assertEqual(items[0]["download_kind"], "http")
        self.assertIsNone(items[0]["task_id"])
        self.assertIsNone(items[0]["task_status"])

        task = self.controller.download_feed_item(subscription_id, items[0]["id"])
        self.assertEqual(task["anime"], "Manual Anime")
        self.assertEqual(task["status"], "queued")
        refreshed = self.controller.list_subscription_items(subscription_id)
        self.assertEqual(refreshed[0]["task_id"], task["id"])
        self.assertEqual(refreshed[0]["task_status"], "queued")

    def test_settings_aliases_map_to_core(self) -> None:
        settings = self.controller.load_settings()
        self.assertEqual(settings["poll_interval_minutes"], 20)
        self.assertEqual(settings["download_directory"], self.temporary.name)
        self.assertFalse(settings["seed_after_complete"])
        self.assertEqual(settings["theme"], "dark")

    def test_subscription_folders_define_default_root_and_support_move(self) -> None:
        first_root = Path(self.temporary.name) / "Seasonal"
        second_root = Path(self.temporary.name) / "Archive"
        first = self.controller.save_subscription_folder(
            {"name": "Seasonal", "download_directory": str(first_root)}
        )
        second = self.controller.save_subscription_folder(
            {"name": "Archive", "download_directory": str(second_root)}
        )
        saved = self.controller.save_subscription(
            {
                "name": "Folder Anime",
                "rss_url": "https://feeds.invalid/folder.xml",
                "folder_id": first["id"],
                "save_path": "",
            }
        )
        self.assertEqual(saved["folder_name"], "Seasonal")
        self.assertEqual(Path(saved["resolved_save_path"]), first_root.resolve() / "Folder Anime")
        self.assertTrue(Path(saved["resolved_save_path"]).is_dir())

        moved = self.controller.move_subscription(saved["id"], second["id"])
        self.assertEqual(moved["folder_name"], "Archive")
        self.assertEqual(Path(moved["resolved_save_path"]), second_root.resolve() / "Folder Anime")
        self.assertTrue(Path(moved["resolved_save_path"]).is_dir())
        self.assertTrue(first_root.is_dir())
        self.assertTrue(second_root.is_dir())

        self.assertTrue(self.controller.delete_subscription_folder(second["id"]))
        unfiled = next(
            item for item in self.controller.list_subscriptions() if item["id"] == saved["id"]
        )
        self.assertIsNone(unfiled["folder_id"])
        self.assertEqual(
            Path(unfiled["resolved_save_path"]),
            Path(self.temporary.name).resolve() / "Folder Anime",
        )


if __name__ == "__main__":
    unittest.main()
