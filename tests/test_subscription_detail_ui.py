from __future__ import annotations

import threading
import time
import unittest
from typing import ClassVar

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QApplication, QPushButton

from anirss.ui.controller import DemoController
from anirss.ui.main_window import MainWindow
from anirss.ui.subscription_detail import SubscriptionDetailView
from anirss.ui.subscriptions import SubscriptionsPage
from anirss.ui.widgets import BadgeLabel
from anirss.ui.worker import FunctionWorker


class _SlowDownloadController(DemoController):
    def __init__(self) -> None:
        super().__init__()
        self.download_started = threading.Event()
        self.release_download = threading.Event()

    def download_feed_item(self, subscription_id: object, item_id: object) -> dict[str, object]:
        self.download_started.set()
        if not self.release_download.wait(2):
            raise TimeoutError("test did not release manual download")
        return super().download_feed_item(subscription_id, item_id)


class SubscriptionDetailUiTests(unittest.TestCase):
    qt_app: ClassVar[QApplication]

    @classmethod
    def setUpClass(cls) -> None:
        existing = QApplication.instance()
        cls.qt_app = existing if isinstance(existing, QApplication) else QApplication([])

    def setUp(self) -> None:
        self.controller = DemoController()
        self.page = SubscriptionsPage(self.controller)
        self.page.resize(1100, 720)
        self.page.show()
        self.page.reload()
        self.qt_app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        self.qt_app.processEvents()

    def test_open_detail_and_manually_download_recorded_item(self) -> None:
        routes: list[str] = []
        self.page.route_changed.connect(routes.append)
        self.page.open_subscription(0)
        self.qt_app.processEvents()

        detail = self.page.detail_view
        self.assertIs(self.page.route_stack.currentWidget(), detail)
        self.assertEqual(detail.subscription_name, "葬送的芙莉莲")
        self.assertEqual(detail.table.rowCount(), 2)
        self.assertEqual(routes[-1], "葬送的芙莉莲")

        target_row = -1
        for row in range(detail.table.rowCount()):
            episode_item = detail.table.item(row, 0)
            if (
                episode_item is not None
                and episode_item.data(Qt.ItemDataRole.UserRole) == "frieren-27"
            ):
                target_row = row
                break
        self.assertGreaterEqual(target_row, 0)
        action_cell = detail.table.cellWidget(target_row, 5)
        assert action_cell is not None
        action = action_cell.findChild(QPushButton)
        assert action is not None
        self.assertEqual(action.text(), "下载")
        action.click()
        deadline = time.monotonic() + 2
        while True:
            self.qt_app.processEvents()
            item = next(
                entry
                for entry in self.controller.list_subscription_items("frieren")
                if entry["id"] == "frieren-27"
            )
            if item["task_id"] is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        self.assertIsNotNone(item["task_id"])
        self.assertEqual(item["task_status"], "queued")
        self.assertEqual(len(self.controller.list_downloads()), 4)

        self.page.show_subscription_list()
        self.assertIs(self.page.route_stack.currentWidget(), self.page.list_view)
        self.assertEqual(routes[-1], "")

    def test_manual_download_does_not_block_the_ui_thread(self) -> None:
        controller = _SlowDownloadController()
        page = SubscriptionsPage(controller)
        page.resize(1100, 720)
        page.show()
        page.reload()
        page.open_subscription(0)
        self.qt_app.processEvents()
        detail = page.detail_view
        target_row = -1
        for row in range(detail.table.rowCount()):
            episode_item = detail.table.item(row, 0)
            if (
                episode_item is not None
                and episode_item.data(Qt.ItemDataRole.UserRole) == "frieren-27"
            ):
                target_row = row
                break
        self.assertGreaterEqual(target_row, 0)
        action_cell = detail.table.cellWidget(target_row, 5)
        assert action_cell is not None
        action = action_cell.findChild(QPushButton)
        assert action is not None

        started_at = time.monotonic()
        action.click()
        elapsed = time.monotonic() - started_at
        try:
            self.assertLess(elapsed, 0.25)
            self.assertTrue(controller.download_started.wait(1))
            pending_cell = detail.table.cellWidget(target_row, 5)
            assert pending_cell is not None
            pending_action = pending_cell.findChild(QPushButton)
            assert pending_action is not None
            self.assertFalse(pending_action.isEnabled())
            self.assertEqual(pending_action.text(), "处理中…")
        finally:
            controller.release_download.set()
            QThreadPool.globalInstance().waitForDone(2000)
            self.qt_app.processEvents()
            page.close()
            page.deleteLater()

    def _isolated_detail(self, width: int = 1100) -> SubscriptionDetailView:
        detail = SubscriptionDetailView()
        self.addCleanup(detail.deleteLater)
        self.addCleanup(detail.close)
        detail.resize(width, 720)
        detail.set_subscription({"id": "test", "name": "Test"}, reload_items=False)
        detail.set_items(
            [{"id": "item", "title": "Episode", "download_url": "https://example.test/x.mkv"}]
        )
        return detail

    def test_success_after_task_reload_restores_pending_action(self) -> None:
        detail = self._isolated_detail()
        key = ("test", "item")
        detail._download_workers[key] = FunctionWorker(lambda: None)
        queued = {**detail._items[0], "task_id": "task", "task_status": "queued"}
        # A service update can reach the GUI before the worker's success signal.
        detail.set_items([queued])
        cell = detail.table.cellWidget(0, 5)
        assert cell is not None
        action = cell.findChild(QPushButton)
        assert action is not None
        self.assertFalse(action.isEnabled())

        detail._download_finished(key)
        detail.set_items([queued])

        cell = detail.table.cellWidget(0, 5)
        assert cell is not None
        action = cell.findChild(QPushButton)
        assert action is not None
        self.assertTrue(action.isEnabled())
        self.assertEqual(action.text(), "查看任务")

    def test_status_refresh_preserves_compact_action_layout(self) -> None:
        detail = self._isolated_detail(600)
        detail.set_items([{**detail._items[0], "task_id": "task", "task_status": "queued"}])

        cell = detail.table.cellWidget(0, 5)
        assert cell is not None
        action = cell.findChild(QPushButton)
        assert action is not None
        self.assertEqual(action.text(), "")
        self.assertEqual(action.width(), 26)
        self.assertEqual(action.toolTip(), "查看任务")
        self.assertLessEqual(action.width(), detail.table.columnWidth(5))
        detail._update_table_columns(1100)
        self.assertEqual(action.text(), "查看任务")
        self.assertGreaterEqual(action.minimumWidth(), 100)

    def test_pending_and_failed_refresh_preserve_compact_action_layout(self) -> None:
        detail = self._isolated_detail(600)
        key = ("test", "item")
        detail._download_workers[key] = FunctionWorker(lambda: None)
        detail._refresh_item_row("item")
        cell = detail.table.cellWidget(0, 5)
        assert cell is not None
        action = cell.findChild(QPushButton)
        assert action is not None
        self.assertFalse(action.isEnabled())
        self.assertEqual(action.width(), 26)

        detail._download_failed(key, "temporary failure")

        cell = detail.table.cellWidget(0, 5)
        assert cell is not None
        action = cell.findChild(QPushButton)
        assert action is not None
        self.assertTrue(action.isEnabled())
        self.assertEqual(action.text(), "")
        self.assertEqual(action.width(), 26)
        self.assertEqual(action.toolTip(), "下载")

    def test_theme_change_updates_existing_rows_and_preserves_selection(self) -> None:
        detail = self._isolated_detail()
        detail.set_items(
            [
                {"id": "first", "title": "First", "download_url": "https://example.test/1"},
                {"id": "second", "title": "Second", "download_url": "https://example.test/2"},
            ],
            selected_id="second",
        )
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                detail.set_theme(theme)
                self.assertEqual(detail._selected_item_id(), "second")
                for row in range(2):
                    cell = detail.table.cellWidget(row, 4)
                    assert cell is not None
                    badge = cell.findChild(BadgeLabel)
                    assert badge is not None
                    self.assertEqual(badge._theme, theme)

    def test_empty_filter_clears_hidden_selection_and_details(self) -> None:
        self.page.open_subscription(0)
        detail = self.page.detail_view
        detail.search_edit.setText("definitely-no-matching-feed-item")
        self.qt_app.processEvents()

        self.assertEqual(detail._first_visible_row(), -1)
        self.assertEqual(detail.table.currentRow(), -1)
        self.assertEqual(detail.detail_title.text(), "没有符合当前筛选的条目")
        self.assertEqual(detail.article_url.text(), "")
        self.assertEqual(detail.download_url.text(), "")

    def test_refresh_state_is_bound_to_the_requested_subscription(self) -> None:
        self.page.set_detail_refreshing("frieren", True)
        self.page.open_subscription(1)
        self.assertFalse(self.page.detail_view.refresh_button.isEnabled())
        self.assertEqual(self.page.detail_view.refresh_button.text(), "其他订阅刷新中…")

        self.page.set_detail_refreshing("frieren", False)
        self.assertTrue(self.page.detail_view.refresh_button.isEnabled())
        self.assertEqual(self.page.detail_view.refresh_button.text(), "刷新此订阅")

    def test_active_detail_rename_updates_route_and_uses_plain_text(self) -> None:
        routes: list[str] = []
        self.page.route_changed.connect(routes.append)
        self.page.open_subscription(0)
        updated = self.controller.list_subscriptions()
        updated[0]["name"] = "<b>只是标题</b>"

        self.page.set_subscriptions(updated)

        self.assertEqual(routes[-1], "<b>只是标题</b>")
        self.assertEqual(self.page.detail_view.header.title.text(), "<b>只是标题</b>")
        self.assertEqual(
            self.page.detail_view.header.title.textFormat(),
            Qt.TextFormat.PlainText,
        )

    def test_main_window_updates_breadcrumb_and_focuses_existing_task(self) -> None:
        window = MainWindow(self.controller)
        window.show()
        window.sidebar.select(1)
        window.subscriptions_page.open_subscription(0)
        self.qt_app.processEvents()
        self.assertIn("订阅  /  葬送的芙莉莲", window.breadcrumb.text())

        window.subscriptions_page.detail_view.show_download_requested.emit("dl-1")
        self.qt_app.processEvents()
        self.assertIs(window.pages.currentWidget(), window.downloads_page)
        selected = window.downloads_page.table.currentRow()
        self.assertGreaterEqual(selected, 0)
        self.assertEqual(window.downloads_page._visible_items[selected]["id"], "dl-1")

        window.sidebar.select(1)
        window.subscriptions_page.show_subscription_list()
        window.sidebar.select(2)
        window.sidebar.select(1)
        self.assertEqual(window.breadcrumb.text(), "工作台  /  订阅")

        window._force_quit = True
        window.close()
        window.deleteLater()
        self.qt_app.processEvents()


if __name__ == "__main__":
    unittest.main()
