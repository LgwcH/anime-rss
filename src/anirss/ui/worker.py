"""Tiny Qt thread-pool helpers for potentially slow controller calls."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    """Run one callable off the UI thread and marshal its result back."""

    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)
