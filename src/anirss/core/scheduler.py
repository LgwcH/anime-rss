"""Cooperative polling scheduler used by :mod:`anirss.core.service`."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from .database import SQLiteRepository
from .models import AppSettings, Subscription, utc_now


class SubscriptionScheduler:
    """Poll due subscriptions on one stoppable background thread."""

    def __init__(
        self,
        repository: SQLiteRepository,
        settings_provider: Callable[[], AppSettings],
        refresh_callback: Callable[[Subscription], object],
        error_callback: Callable[[Subscription, Exception], None] | None = None,
    ) -> None:
        self._repository = repository
        self._settings_provider = settings_provider
        self._refresh_callback = refresh_callback
        self._error_callback = error_callback
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_attempts: dict[int, datetime] = {}

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="AniRSS subscription scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float | None = 10.0) -> bool:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=None if timeout is None else max(0.0, timeout))
        return not bool(thread and thread.is_alive())

    def wake(self) -> None:
        self._wake_event.set()

    def run_due(self) -> int:
        now = utc_now()
        settings = self._settings_provider()
        refreshed = 0
        for subscription in self._repository.list_subscriptions(enabled_only=True):
            if self._stop_event.is_set():
                break
            subscription_id = subscription.id
            assert subscription_id is not None
            interval = subscription.poll_interval_minutes or settings.default_poll_interval_minutes
            last_attempt = self._last_attempts.get(subscription_id)
            effective_last = subscription.last_checked_at
            if last_attempt is not None and (
                effective_last is None or last_attempt > effective_last
            ):
                effective_last = last_attempt
            due = effective_last is None or now - effective_last >= timedelta(minutes=interval)
            if not due:
                continue
            self._last_attempts[subscription_id] = now
            try:
                self._refresh_callback(subscription)
                refreshed += 1
            except Exception as exc:
                if self._error_callback:
                    self._error_callback(subscription, exc)
        return refreshed

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_due()
            try:
                delay = self._settings_provider().scheduler_tick_seconds
            except Exception:
                delay = 15
            self._wake_event.wait(max(1, delay))
            self._wake_event.clear()


__all__ = ["SubscriptionScheduler"]
