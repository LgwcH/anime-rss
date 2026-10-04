"""Cooperative polling scheduler used by :mod:`anirss.core.service`."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta

from .database import SQLiteRepository
from .models import AppSettings, Subscription, utc_now

# Upper bound on simultaneous feed fetches.  Every fetch is bounded by its own
# ``request_timeout_seconds`` network timeout, so a stalled source only ever
# occupies one worker instead of delaying the whole polling round.
MAX_CONCURRENT_REFRESHES = 4


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
        due: list[Subscription] = []
        for subscription in self._repository.list_subscriptions(enabled_only=True):
            subscription_id = subscription.id
            assert subscription_id is not None
            interval = subscription.poll_interval_minutes or settings.default_poll_interval_minutes
            last_attempt = self._last_attempts.get(subscription_id)
            effective_last = subscription.last_checked_at
            if last_attempt is not None and (
                effective_last is None or last_attempt > effective_last
            ):
                effective_last = last_attempt
            is_due = effective_last is None or now - effective_last >= timedelta(minutes=interval)
            if is_due:
                due.append(subscription)
        if self._stop_event.is_set():
            return 0
        refreshed = 0
        if len(due) <= 1:
            for subscription in due:
                if self._stop_event.is_set():
                    break
                refreshed += self._refresh_one(subscription, now)
            return refreshed
        # One dead feed must not stall every other source: fetches run in
        # parallel so a round costs the slowest feed, not the sum.  In-flight
        # fetches finish on their own timeout; no new work starts after stop.
        workers = min(MAX_CONCURRENT_REFRESHES, len(due))
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="AniRSS refresh",
        ) as pool:
            pending: list[tuple[Subscription, Future[object]]] = []
            for subscription in due:
                if self._stop_event.is_set():
                    break
                subscription_id = subscription.id
                assert subscription_id is not None
                self._last_attempts[subscription_id] = now
                pending.append((subscription, pool.submit(self._refresh_callback, subscription)))
            for subscription, future in pending:
                try:
                    future.result()
                except Exception as exc:
                    if self._error_callback:
                        self._error_callback(subscription, exc)
                else:
                    refreshed += 1
        return refreshed

    def _refresh_one(self, subscription: Subscription, attempted_at: datetime) -> int:
        subscription_id = subscription.id
        assert subscription_id is not None
        self._last_attempts[subscription_id] = attempted_at
        try:
            self._refresh_callback(subscription)
        except Exception as exc:
            if self._error_callback:
                self._error_callback(subscription, exc)
            return 0
        return 1

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_due()
            try:
                delay = self._settings_provider().scheduler_tick_seconds
            except Exception:
                delay = 15
            self._wake_event.wait(max(1, delay))
            self._wake_event.clear()


__all__ = ["MAX_CONCURRENT_REFRESHES", "SubscriptionScheduler"]
