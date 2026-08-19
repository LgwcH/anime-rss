from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from anirss.single_instance import AlreadyRunningError, SingleInstanceLock


class SingleInstanceTests(unittest.TestCase):
    def test_only_one_owner_can_lock_a_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "anirss.instance.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())

            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_context_manager_reports_an_existing_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "anirss.instance.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)
            self.assertTrue(first.acquire())
            try:
                with self.assertRaises(AlreadyRunningError), second:
                    pass
            finally:
                first.release()


if __name__ == "__main__":
    unittest.main()
