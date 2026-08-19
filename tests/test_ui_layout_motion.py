from __future__ import annotations

import os
import unittest
from typing import ClassVar
from unittest.mock import patch

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from anirss.ui.controller import DemoController
from anirss.ui.downloads import DownloadsPage
from anirss.ui.main_window import MainWindow
from anirss.ui.motion import AnimatedStackedWidget, JellySnapshotOverlay
from anirss.ui.overview import OverviewPage
from anirss.ui.settings import SettingsPage
from anirss.ui.subscription_detail import SubscriptionDetailView
from anirss.ui.subscriptions import SubscriptionsPage
from anirss.ui.widgets import BadgeLabel, ElidedLabel, JellyButton, ToggleSwitch


class UiLayoutMotionTests(unittest.TestCase):
    qt_app: ClassVar[QApplication]

    @classmethod
    def setUpClass(cls) -> None:
        existing = QApplication.instance()
        cls.qt_app = existing if isinstance(existing, QApplication) else QApplication([])

    def test_elided_label_keeps_full_plain_text_available(self) -> None:
        value = "<b>这是一段非常长但只能作为纯文本显示的番剧名称</b>"
        label = ElidedLabel(value)
        label.resize(96, 28)
        label.show()
        self.qt_app.processEvents()

        self.assertEqual(label.text(), value)
        self.assertNotEqual(label.displayed_text(), value)
        self.assertIn("…", label.displayed_text())
        self.assertEqual(
            label.toolTip(),
            "&lt;b&gt;这是一段非常长但只能作为纯文本显示的番剧名称&lt;/b&gt;",
        )
        self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)
        self.assertLessEqual(
            label.fontMetrics().horizontalAdvance(label.displayed_text()),
            label.contentsRect().width(),
        )
        label.close()

    def test_badge_reserves_enough_room_for_its_text(self) -> None:
        for text in ("下载中", "自动下载", "下载失败"):
            badge = BadgeLabel(text, "info")
            badge.show()
            self.qt_app.processEvents()
            required_width = badge.fontMetrics().horizontalAdvance(text)
            self.assertGreaterEqual(badge.contentsRect().width(), required_width)
            self.assertGreaterEqual(badge.contentsRect().height(), badge.fontMetrics().height())
            badge.close()

    def test_programmatic_toggle_change_never_rebounds(self) -> None:
        toggle = ToggleSwitch()
        toggle.setChecked(True)
        self.assertEqual(toggle._animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(toggle._get_offset(), 21.0)
        toggle.setChecked(False)
        self.assertEqual(toggle._animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(toggle._get_offset(), 3.0)

    @patch.dict(os.environ, {"ANIRSS_REDUCE_MOTION": "0"})
    def test_mouse_button_feedback_squashes_and_elastically_settles(self) -> None:
        button = JellyButton("Action")
        button.resize(120, 42)
        button.show()
        self.qt_app.processEvents()

        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        QTest.qWait(130)
        self.assertGreater(button._get_deform(), 0.9)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        QTest.qWait(80)
        self.assertLess(button._get_deform(), 0.0)
        QTest.qWait(140)
        self.assertAlmostEqual(button._get_deform(), 0.0, places=2)
        button.close()

    @patch.dict(os.environ, {"ANIRSS_REDUCE_MOTION": "0"})
    def test_mouse_button_feedback_is_interruptible(self) -> None:
        button = JellyButton("Action")
        button.resize(120, 42)
        button.show()
        self.qt_app.processEvents()

        for _ in range(4):
            QTest.mousePress(button, Qt.MouseButton.LeftButton)
            QTest.qWait(24)
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
            QTest.qWait(24)
        QTest.qWait(220)

        self.assertAlmostEqual(button._get_deform(), 0.0, places=2)
        self.assertIsNone(button._press_motion)
        button.close()

    def test_reduced_motion_removes_button_and_toggle_deformation(self) -> None:
        button = JellyButton("Action")
        toggle = ToggleSwitch()
        button.show()
        toggle.show()
        self.qt_app.processEvents()
        with patch.dict(os.environ, {"ANIRSS_REDUCE_MOTION": "1"}):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
            self.qt_app.processEvents()
        self.assertEqual(button._get_deform(), 0.0)
        self.assertEqual(toggle._get_deform(), 0.0)
        self.assertEqual(toggle._animation.state(), QAbstractAnimation.State.Stopped)
        button.close()
        toggle.close()

    def test_reduced_motion_switches_pages_without_animation(self) -> None:
        stack = AnimatedStackedWidget()
        stack.addWidget(QWidget())
        stack.addWidget(QWidget())
        stack.resize(320, 220)
        stack.show()
        self.qt_app.processEvents()

        with patch.dict(os.environ, {"ANIRSS_REDUCE_MOTION": "1"}):
            stack.transition_to(1)

        self.assertEqual(stack.currentIndex(), 1)
        self.assertIsNone(stack._animation_group)
        self.assertIsNone(stack._overlay)
        stack.close()

    def test_page_transition_is_interruptible_and_cleans_up(self) -> None:
        stack = AnimatedStackedWidget()
        for _index in range(3):
            stack.addWidget(QWidget())
        stack.resize(320, 220)
        stack.show()
        self.qt_app.processEvents()

        with patch.dict(os.environ, {"ANIRSS_REDUCE_MOTION": "0"}):
            stack.transition_to(1)
            stack.transition_to(2)
        self.assertEqual(stack.currentIndex(), 2)
        self.assertIsNotNone(stack._animation_group)
        self.assertIsNotNone(stack._overlay)
        self.assertIsInstance(stack._overlay, JellySnapshotOverlay)
        QTest.qWait(260)

        self.assertIsNone(stack._animation_group)
        self.assertIsNone(stack._overlay)
        current_widget = stack.currentWidget()
        assert current_widget is not None
        self.assertIsNone(current_widget.graphicsEffect())
        stack.close()

    def test_main_window_compacts_without_topbar_overlap(self) -> None:
        window = MainWindow(DemoController())
        window._poll_timer.stop()
        window.show()
        window.resize(900, 600)
        self.qt_app.processEvents()
        self.assertEqual(window.sidebar.width(), 88)
        self.assertFalse(window.refresh_status.isVisible())

        window.resize(1260, 800)
        long_name = "超长番剧名称" * 80
        window.breadcrumb.setText(f"工作台  /  订阅  /  {long_name}")
        self.qt_app.processEvents()
        self.assertEqual(window.sidebar.width(), 206)
        self.assertTrue(window.refresh_status.isVisible())
        self.assertGreater(window.refresh_status.width(), 0)
        self.assertTrue(window.refresh_status.displayed_text())
        self.assertGreater(window.overview_page.next_refresh.width(), 0)
        for card in window.overview_page.cards.values():
            self.assertGreater(card.caption.width(), 0)
            self.assertTrue(card.caption.displayed_text())
        self.assertLess(
            window.breadcrumb.geometry().right(),
            window.refresh_button.geometry().left(),
        )
        self.assertIn("…", window.breadcrumb.displayed_text())
        self.assertTrue(window.breadcrumb.toolTip())

        window._force_quit = True
        window.close()

    def test_detail_actions_and_long_path_stay_inside_their_cells(self) -> None:
        controller = DemoController()
        detail = SubscriptionDetailView(controller)
        detail.resize(612, 534)
        detail.show()
        subscription = controller.list_subscriptions()[0]
        subscription["resolved_save_path"] = "D:/" + "/非常长的保存目录" * 80
        detail.set_subscription(subscription)
        self.qt_app.processEvents()

        self.assertIn("…", detail.metadata.displayed_text())
        self.assertTrue(detail.metadata.toolTip())
        for label in (detail.count_metadata, detail.refresh_metadata, detail.metadata):
            self.assertGreater(label.width(), 0)
            self.assertTrue(label.displayed_text())
        for row in range(detail.table.rowCount()):
            action_cell = detail.table.cellWidget(row, 5)
            assert action_cell is not None
            action = action_cell.findChild(QPushButton)
            assert action is not None
            self.assertLessEqual(action.geometry().right(), action_cell.contentsRect().right())
            status_cell = detail.table.cellWidget(row, 4)
            assert status_cell is not None
            badge = status_cell.findChild(BadgeLabel)
            assert badge is not None
            self.assertGreaterEqual(
                badge.contentsRect().width(),
                badge.fontMetrics().horizontalAdvance(badge.text()),
            )

        with patch.dict(os.environ, {"ANIRSS_REDUCE_MOTION": "0"}):
            detail._set_details_expanded(True)
            self.qt_app.processEvents()
        self.assertEqual(detail.content_splitter.count(), 2)
        self.assertGreaterEqual(detail.table.height(), 100)
        self.assertEqual(detail.table.horizontalScrollBar().maximum(), 0)
        overlay = detail._detail_overlay
        assert overlay is not None
        self.assertIs(overlay.parentWidget(), detail.table_container)

        detail._set_details_expanded(False, animate=False)
        detail.resize(413, 354)
        detail.search_edit.setText("definitely-no-match")
        self.qt_app.processEvents()
        self.assertIs(detail.content_stack.currentWidget(), detail.filter_empty_card)
        self.assertFalse(detail.filter_empty.detail_label.isVisible())
        self.assertGreaterEqual(
            detail.filter_empty.title_label.height(),
            detail.filter_empty.title_label.fontMetrics().height(),
        )

        detail.close()

    def test_short_overview_uses_compact_cards_without_hiding_values(self) -> None:
        page = OverviewPage(DemoController())
        page.resize(750, 385)
        page.show()
        page.reload()
        self.qt_app.processEvents()

        self.assertEqual(page.height(), 385)
        for card in page.cards.values():
            self.assertFalse(card.hint.isVisible())
            self.assertGreaterEqual(card.caption.height(), card.caption.fontMetrics().height())
            self.assertGreaterEqual(
                card.value_label.height(),
                card.value_label.fontMetrics().height(),
            )
        page.close()

    def test_compact_downloads_hide_progress_without_horizontal_scroll(self) -> None:
        page = DownloadsPage(DemoController())
        page.resize(413, 354)
        page.show()
        page.set_downloads(
            [
                {
                    "id": "long-speed",
                    "title": "一条很长的下载任务",
                    "anime": "测试番剧",
                    "progress": 1.0,
                    "speed": "X" * 20000,
                    "status": "downloading",
                }
            ]
        )
        self.qt_app.processEvents()

        self.assertTrue(page.table.isColumnHidden(1))
        self.assertEqual(page.table.columnWidth(3), 0)
        self.assertEqual(page.table.horizontalScrollBar().maximum(), 0)
        cell = page.table.cellWidget(0, 0)
        assert cell is not None
        meta = cell.findChild(ElidedLabel, "DownloadMeta")
        assert meta is not None
        self.assertIn("100%", meta.text())
        page.close()

    def test_periodic_table_reload_preserves_scroll_position(self) -> None:
        controller = DemoController()
        template = controller._downloads[0]
        controller._downloads = [
            {
                **template,
                "id": f"task-{index}",
                "title": f"Task {index:02d}",
                "progress": index % 100,
            }
            for index in range(40)
        ]
        page = DownloadsPage(controller)
        page.resize(900, 340)
        page.show()
        page.reload()
        self.qt_app.processEvents()
        bar = page.table.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        expected = bar.value()

        page.reload()
        self.qt_app.processEvents()
        self.assertEqual(bar.value(), expected)
        page.close()

    def test_subscription_folder_filter_and_move(self) -> None:
        controller = DemoController()
        page = SubscriptionsPage(controller)
        page.resize(1000, 640)
        page.show()
        page.reload()
        self.qt_app.processEvents()

        self.assertGreaterEqual(page.folder_filter.count(), 3)
        page.table.selectRow(0)
        self.assertTrue(page.move_button.isEnabled())
        with patch(
            "anirss.ui.subscriptions.QInputDialog.getItem",
            return_value=(
                "\u672a\u5206\u7c7b\uff08\u5168\u5c40\u4e0b\u8f7d\u76ee\u5f55\uff09",
                True,
            ),
        ):
            page.move_selected_subscription()
        self.qt_app.processEvents()

        moved_id = page._all_items[0]["id"]
        moved = next(item for item in controller.list_subscriptions() if item["id"] == moved_id)
        self.assertIsNone(moved["folder_id"])
        self.assertIn("AniRSS", moved["resolved_save_path"])
        page.close()

    def test_subscription_reload_preserves_scroll_and_compact_toolbar_fits(self) -> None:
        controller = DemoController()
        template = controller._subscriptions[0]
        controller._subscriptions = [
            {
                **template,
                "id": f"subscription-{index}",
                "name": f"Subscription {index:02d}",
            }
            for index in range(35)
        ]
        page = SubscriptionsPage(controller)
        page.resize(500, 440)
        page.show()
        page.reload()
        self.qt_app.processEvents()

        self.assertTrue(page.table.isColumnHidden(1))
        self.assertTrue(page.table.isColumnHidden(2))
        self.assertTrue(page.table.isColumnHidden(3))
        self.assertEqual(page.table.horizontalScrollBar().maximum(), 0)
        for button in (page.new_folder_button, page.move_button):
            self.assertGreaterEqual(
                button.contentsRect().width(),
                button.fontMetrics().horizontalAdvance(button.text()),
            )
            parent = button.parentWidget()
            assert parent is not None
            self.assertLessEqual(button.geometry().right(), parent.contentsRect().right())

        bar = page.table.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        expected = bar.value()
        page.reload()
        self.qt_app.processEvents()
        self.assertEqual(bar.value(), expected)
        page.close()

    def test_settings_refresh_preserves_scroll_position(self) -> None:
        controller = DemoController()
        page = SettingsPage(controller)
        page.resize(760, 380)
        page.show()
        page.reload()
        self.qt_app.processEvents()
        bar = page.settings_scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        expected = bar.value()

        page.set_settings(controller.load_settings())
        self.qt_app.processEvents()
        self.assertEqual(bar.value(), expected)
        page.close()


if __name__ == "__main__":
    unittest.main()
