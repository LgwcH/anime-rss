from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from anirss.core.models import FeedItem, Subscription
from anirss.core.naming import (
    NamingPolicy,
    UnsafePathError,
    create_series_directory,
    ensure_within_root,
    filename_for_item,
    recognize_episode,
    safe_download_path,
    sanitize_component,
)


class NamingTests(unittest.TestCase):
    def test_portable_component_cleaning(self) -> None:
        self.assertEqual(sanitize_component("../../CON: <show>?*."), "_.._CON_ _show_")
        self.assertEqual(sanitize_component("CON.txt"), "_CON.txt")
        self.assertEqual(sanitize_component("  番剧 名称  "), "番剧 名称")

    def test_episode_recognition(self) -> None:
        cases = {
            "Title S2E07 1080p": "S02E07",
            "动画 第12话": "12",
            "Title EP 12.5": "12.5",
            "[Group] Title [03] [1080p]": "03",
            "[Group] Title [1080]": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(recognize_episode(title), expected)
        self.assertEqual(recognize_episode("Show #42", r"#(?P<episode>\d+)"), "42")

    def test_filename_uses_url_basename_without_query(self) -> None:
        item = FeedItem(
            subscription_id=1,
            guid="g",
            title="Pretty title",
            download_url="https://cdn.example/Show%20-%2001.mkv?token=secret",
        )
        self.assertEqual(filename_for_item(item), "Pretty title.mkv")

    def test_traversal_stays_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "downloads"
            directory = create_series_directory(root, "../../outside")
            directory.relative_to(root.resolve())
            target = safe_download_path(directory, "../../episode.mkv")
            target.relative_to(directory.resolve())
            with self.assertRaises(UnsafePathError):
                ensure_within_root(root, Path(temporary) / "outside")

    @unittest.skipIf(os.name == "nt", "creating symlinks often requires Windows privileges")
    def test_existing_symlink_cannot_escape_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "Linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                create_series_directory(root, "Linked")

    def test_naming_policy_creates_subscription_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            subscription = Subscription(name="My / Show", feed_url="https://example.test/rss")
            folder = NamingPolicy(temporary).directory_for(subscription)
            self.assertEqual(folder.name, "My _ Show")
            self.assertTrue(folder.is_dir())


if __name__ == "__main__":
    unittest.main()
