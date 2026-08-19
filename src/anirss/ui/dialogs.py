"""Dialogs used by the subscriptions and downloads pages."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .resources import icon
from .widgets import JellyButton as QPushButton
from .widgets import ToggleSwitch


def _value(source: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _keywords_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return ""


def _keywords_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，\n]", value) if item.strip()]


class SubscriptionDialog(QDialog):
    """Create or edit one RSS subscription."""

    def __init__(
        self,
        subscription: Mapping[str, Any] | None = None,
        default_directory: str = "",
        parent: QWidget | None = None,
        *,
        folders: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = dict(subscription or {})
        self._default_directory = default_directory
        self._folders = [dict(folder) for folder in (folders or [])]
        self.setWindowTitle("编辑订阅" if subscription else "新增订阅")
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 900
        available_height = available.height() if available is not None else 700
        minimum_width = min(520, max(380, int(available_width * 0.82)))
        minimum_height = min(420, max(340, int(available_height * 0.72)))
        self.setMinimumSize(minimum_width, minimum_height)
        self.resize(
            max(minimum_width, min(620, int(available_width * 0.88))),
            max(minimum_height, min(650, int(available_height * 0.88))),
        )
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(16)
        title = QLabel(self.windowTitle())
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size:20px;")
        outer.addWidget(title)
        detail = QLabel("为这部番剧设置 RSS 来源、匹配规则与保存位置。")
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True)
        detail.setObjectName("PageSubtitle")
        outer.addWidget(detail)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.name_edit = QLineEdit(str(_value(self._source, "name", "anime_name", "title")))
        self.name_edit.setMaxLength(200)
        self.name_edit.setPlaceholderText("例如：葬送的芙莉莲")
        form.addRow("番剧名称 *", self.name_edit)

        self.url_edit = QLineEdit(str(_value(self._source, "rss_url", "url", "feed_url")))
        self.url_edit.setMaxLength(2048)
        self.url_edit.setPlaceholderText("https://example.com/feed.xml")
        form.addRow("RSS 地址 *", self.url_edit)

        self.folder_combo = QComboBox()
        self.folder_combo.addItem("未分类（使用全局下载目录）", None)
        for folder in self._folders:
            name = str(folder.get("name") or "未命名文件夹")[:200]
            folder_id = folder.get("id")
            self.folder_combo.addItem(name, folder_id)
            index = self.folder_combo.count() - 1
            self.folder_combo.setItemData(
                index,
                str(folder.get("download_directory") or ""),
                Qt.ItemDataRole.ToolTipRole,
            )
        selected_folder_id = _value(self._source, "folder_id", default=None)
        selected_index = self.folder_combo.findData(selected_folder_id)
        self.folder_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.folder_combo.currentIndexChanged.connect(self._folder_changed)
        form.addRow("订阅文件夹", self.folder_combo)

        directory_row = QHBoxLayout()
        directory_row.setSpacing(7)
        self.directory_edit = QLineEdit(
            str(
                _value(
                    self._source,
                    "save_path",
                    "save_directory",
                    "directory_name",
                    "download_dir",
                    default="",
                )
            )
        )
        self.directory_edit.setMaxLength(4096)
        self.directory_edit.setPlaceholderText("留空则在当前订阅文件夹中按番剧名称创建目录")
        directory_row.addWidget(self.directory_edit)
        browse = QPushButton("浏览")
        browse.setIcon(icon("folder", "#717789", 17))
        browse.clicked.connect(self._browse_directory)
        directory_row.addWidget(browse)
        form.addRow("自定义保存目录", directory_row)
        self._folder_changed()

        self._initial_include_text = _keywords_text(
            _value(self._source, "include_keywords", "include_pattern", "include", default=[])
        )
        self.include_edit = QLineEdit(self._initial_include_text)
        self.include_edit.setMaxLength(2000)
        self.include_edit.setPlaceholderText("1080P, 简体（逗号分隔；全部满足）")
        form.addRow("必须包含", self.include_edit)

        self._initial_exclude_text = _keywords_text(
            _value(self._source, "exclude_keywords", "exclude_pattern", "exclude", default=[])
        )
        self.exclude_edit = QLineEdit(self._initial_exclude_text)
        self.exclude_edit.setMaxLength(2000)
        self.exclude_edit.setPlaceholderText("720P, 繁体, HEVC（命中即忽略）")
        form.addRow("排除关键词", self.exclude_edit)

        self.regex_edit = QLineEdit(
            str(
                _value(
                    self._source,
                    "episode_regex",
                    "episode_pattern",
                    default=r"(?:\[|\s)(\d{1,3})(?:\]|\s)",
                )
            )
        )
        self.regex_edit.setMaxLength(1000)
        self.regex_edit.setPlaceholderText(r"用于提取集数，例如 \[(\d+)\]")
        form.addRow("集数正则", self.regex_edit)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(10)
        self.auto_toggle = ToggleSwitch()
        self.auto_toggle.setChecked(
            bool(_value(self._source, "auto_download", "download_enabled", default=True))
        )
        toggle_row.addWidget(self.auto_toggle)
        auto_text = QLabel("匹配到新剧集后自动开始下载")
        auto_text.setTextFormat(Qt.TextFormat.PlainText)
        auto_text.setWordWrap(True)
        toggle_row.addWidget(auto_text)
        toggle_row.addStretch()
        form.addRow("自动下载", toggle_row)

        existing_row = QHBoxLayout()
        existing_row.setSpacing(10)
        self.existing_toggle = ToggleSwitch()
        self.existing_toggle.setChecked(
            bool(_value(self._source, "download_existing", default=False))
        )
        existing_row.addWidget(self.existing_toggle)
        existing_text = QLabel("首次刷新时也下载订阅中已有的条目")
        existing_text.setTextFormat(Qt.TextFormat.PlainText)
        existing_text.setWordWrap(True)
        existing_text.setToolTip("关闭时先建立基线，只自动下载之后出现的新条目。")
        existing_row.addWidget(existing_text)
        existing_row.addStretch()
        form.addRow("首次同步", existing_row)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_scroll.setWidget(form_host)
        outer.addWidget(form_scroll, 1)

        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#D84A5B;")
        self.error_label.hide()
        outer.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("保存订阅")
        save.setProperty("primary", True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)
        outer.addWidget(buttons)

    def _browse_directory(self) -> None:
        start = (
            self.directory_edit.text().strip()
            or self._selected_default_directory()
            or str(Path.home())
        )
        selected = QFileDialog.getExistingDirectory(self, "选择番剧保存目录", start)
        if selected:
            self.directory_edit.setText(selected)

    def _selected_default_directory(self) -> str:
        folder_id = self.folder_combo.currentData()
        if folder_id is not None:
            for folder in self._folders:
                if folder.get("id") == folder_id:
                    return str(folder.get("download_directory") or "")
        return self._default_directory

    def _folder_changed(self, _index: int | None = None) -> None:
        root = self._selected_default_directory()
        if root:
            self.directory_edit.setToolTip(f"留空时，默认保存到：{root}\\番剧名称")
        else:
            self.directory_edit.setToolTip("留空时使用全局下载目录并按番剧名称创建子目录")

    def _set_invalid(self, widget: QLineEdit, invalid: bool) -> None:
        widget.setProperty("invalid", invalid)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _validate_and_accept(self) -> None:
        self.error_label.hide()
        self._set_invalid(self.name_edit, False)
        self._set_invalid(self.url_edit, False)
        self._set_invalid(self.regex_edit, False)

        if not self.name_edit.text().strip():
            self._set_invalid(self.name_edit, True)
            self.error_label.setText("请填写番剧名称。")
            self.error_label.show()
            self.name_edit.setFocus()
            return
        parsed = urlparse(self.url_edit.text().strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self._set_invalid(self.url_edit, True)
            self.error_label.setText("请输入有效的 HTTP 或 HTTPS RSS 地址。")
            self.error_label.show()
            self.url_edit.setFocus()
            return
        regex = self.regex_edit.text().strip()
        if regex:
            try:
                re.compile(regex)
            except re.error as exc:
                self._set_invalid(self.regex_edit, True)
                self.error_label.setText(f"集数正则无效：{exc}")
                self.error_label.show()
                self.regex_edit.setFocus()
                return
        self.accept()

    def data(self) -> dict[str, Any]:
        """Return a backend-friendly representation of the form."""

        include_keywords = _keywords_list(self.include_edit.text())
        exclude_keywords = _keywords_list(self.exclude_edit.text())
        save_path = self.directory_edit.text().strip()
        episode_regex = self.regex_edit.text().strip()
        auto_download = self.auto_toggle.isChecked()
        preserve_include_pattern = (
            "include_pattern" in self._source
            and "include_keywords" not in self._source
            and self.include_edit.text() == self._initial_include_text
        )
        preserve_exclude_pattern = (
            "exclude_pattern" in self._source
            and "exclude_keywords" not in self._source
            and self.exclude_edit.text() == self._initial_exclude_text
        )
        include_pattern = (
            self._source.get("include_pattern")
            if preserve_include_pattern
            else "".join(f"(?=.*{re.escape(word)})" for word in include_keywords)
            if include_keywords
            else None
        )
        exclude_pattern = (
            self._source.get("exclude_pattern")
            if preserve_exclude_pattern
            else "(?:" + "|".join(re.escape(word) for word in exclude_keywords) + ")"
            if exclude_keywords
            else None
        )
        default_directory = self._selected_default_directory()
        same_as_default = bool(
            save_path
            and default_directory
            and Path(save_path).resolve() == Path(default_directory).resolve()
        )
        # Both UI-friendly keys and core-service keys are included.  Unknown
        # keys are deliberately ignored by the core's mapping constructor.
        result: dict[str, Any] = {
            "name": self.name_edit.text().strip(),
            "rss_url": self.url_edit.text().strip(),
            "feed_url": self.url_edit.text().strip(),
            "save_path": "" if same_as_default else save_path,
            "directory_name": None
            if same_as_default
            else Path(save_path).name
            if save_path
            else None,
            "include_keywords": include_keywords,
            "include_pattern": include_pattern,
            "exclude_keywords": exclude_keywords,
            "exclude_pattern": exclude_pattern,
            "episode_regex": episode_regex,
            "episode_pattern": episode_regex or None,
            "auto_download": auto_download,
            "download_enabled": auto_download,
            "download_existing": self.existing_toggle.isChecked(),
            "folder_id": self.folder_combo.currentData(),
            "enabled": bool(_value(self._source, "enabled", default=True)),
        }
        if "id" in self._source:
            result["id"] = self._source["id"]
        return result


class SubscriptionFolderDialog(QDialog):
    """Create or edit a logical subscription folder and its download root."""

    def __init__(
        self,
        folder: Mapping[str, Any] | None = None,
        default_directory: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = dict(folder or {})
        self._default_directory = default_directory
        self.setWindowTitle("编辑订阅文件夹" if folder else "新建订阅文件夹")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel(self.windowTitle())
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size:20px;")
        layout.addWidget(title)
        detail = QLabel("文件夹用于整理订阅，并为其中的番剧提供默认下载根目录。")
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True)
        detail.setObjectName("PageSubtitle")
        layout.addWidget(detail)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        self.name_edit = QLineEdit(str(self._source.get("name") or ""))
        self.name_edit.setMaxLength(200)
        self.name_edit.setPlaceholderText("例如：2026 夏季番")
        form.addRow("文件夹名称 *", self.name_edit)

        directory_row = QHBoxLayout()
        directory_row.setSpacing(7)
        self.directory_edit = QLineEdit(str(self._source.get("download_directory") or ""))
        self.directory_edit.setMaxLength(4096)
        self.directory_edit.setPlaceholderText("选择该文件夹的下载根目录")
        directory_row.addWidget(self.directory_edit)
        browse = QPushButton("浏览")
        browse.setIcon(icon("folder", "#717789", 17))
        browse.clicked.connect(self._browse)
        directory_row.addWidget(browse)
        form.addRow("下载根目录 *", directory_row)
        layout.addLayout(form)

        note = QLabel("移动订阅只会改变未来任务的默认保存位置，不会移动或删除已有文件。")
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setObjectName("Muted")
        layout.addWidget(note)
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#D84A5B;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存文件夹")
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("primary", True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        start = self.directory_edit.text().strip() or self._default_directory or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择文件夹下载根目录", start)
        if selected:
            self.directory_edit.setText(selected)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        directory = self.directory_edit.text().strip()
        if not name:
            self.error_label.setText("请填写文件夹名称。")
            self.error_label.show()
            self.name_edit.setFocus()
            return
        if not directory:
            self.error_label.setText("请选择文件夹的下载根目录。")
            self.error_label.show()
            self.directory_edit.setFocus()
            return
        if not Path(directory).expanduser().is_absolute():
            self.error_label.setText("下载根目录必须是绝对路径。")
            self.error_label.show()
            self.directory_edit.setFocus()
            return
        self.accept()

    def data(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name_edit.text().strip(),
            "download_directory": self.directory_edit.text().strip(),
        }
        if "id" in self._source:
            result["id"] = self._source["id"]
        return result


class RemoveDownloadDialog(QMessageBox):
    """Confirmation box that optionally removes downloaded files as well."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setIcon(QMessageBox.Icon.Warning)
        self.setWindowTitle("移除下载任务")
        self.setTextFormat(Qt.TextFormat.PlainText)
        display_title = title if len(title) <= 120 else f"{title[:117]}…"
        self.setText(f"确定要移除“{display_title}”吗？")
        self.setInformativeText("任务将从列表中移除；你可以选择同时删除已下载文件。")
        self.delete_files = QCheckBox("同时删除已下载文件")
        self.setCheckBox(self.delete_files)
        self.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        self.button(QMessageBox.StandardButton.Cancel).setText("取消")
        self.button(QMessageBox.StandardButton.Ok).setText("移除")
