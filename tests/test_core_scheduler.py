from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from anirss.core.database import SQLiteRepository
from anirss.core.models import AppSettings, Subscription
from anirss.core.scheduler import SubscriptionScheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteRepository(Path(self.temporary.name) / "scheduler.db")
        self.settings = AppSettings(download_root=str(Path(self.temporary.name) / "downloads"))

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def _subscription(self, name: str) -> Subscription:
        return self.repository.save_subscription(
            Subscription(name=name, feed_url=f"https://example.test/{name}.xml")
        )

    def test_run_due_refreshes_concurrently_and_records_attempts(self) -> None:
        first = self._subscription("Parallel one")
        second = self._subscription("Parallel two")
        barrier = threading.Barrier(2, timeout=5)
        refreshed: list[str] = []

        def refresh(subscription: Subscription) -> None:
            refreshed.append(subscription.name)
            # Serial refreshes would deadlock here and time the barrier out.
            barrier.wait()

        scheduler = SubscriptionScheduler(self.repository, lambda: self.settings, refresh)

        self.assertEqual(scheduler.run_due(), 2)
        self.assertEqual(set(refreshed), {first.name, second.name})
        assert first.id is not None and second.id is not None
        self.assertIn(first.id, scheduler._last_attempts)
        self.assertIn(second.id, scheduler._last_attempts)
        # Attempts were just recorded, so nothing is due again immediately.
        self.assertEqual(scheduler.run_due(), 0)

    def test_run_due_isolates_failures(self) -> None:
        failing = self._subscription("Failing")
        healthy = self._subscription("Healthy")
        errors: list[tuple[Subscription, Exception]] = []
        refreshed: list[str] = []

        def refresh(subscription: Subscription) -> None:
            if subscription.id == failing.id:
                raise OSError("dead feed")
            refreshed.append(subscription.name)

        scheduler = SubscriptionScheduler(
            self.repository,
            lambda: self.settings,
            refresh,
            lambda subscription, exc: errors.append((subscription, exc)),
        )

        self.assertEqual(scheduler.run_due(), 1)
        self.assertEqual(refreshed, [healthy.name])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0].id, failing.id)
        self.assertIsInstance(errors[0][1], OSError)

    def test_run_due_starts_nothing_after_stop(self) -> None:
        self._subscription("Stopped one")
        self._subscription("Stopped two")
        calls: list[Subscription] = []
        scheduler = SubscriptionScheduler(self.repository, lambda: self.settings, calls.append)
        scheduler._stop_event.set()

        self.assertEqual(scheduler.run_due(), 0)
        self.assertEqual(calls, [])
        self.assertEqual(scheduler._last_attempts, {})


if __name__ == "__main__":
    unittest.main()
