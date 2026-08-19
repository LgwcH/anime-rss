"""Cross-process ownership for one AniRSS data directory."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class AlreadyRunningError(RuntimeError):
    """Raised when another AniRSS process owns the same data directory."""


class SingleInstanceLock:
    """Hold a reliable Qt lock file for the lifetime of one desktop instance."""

    def __init__(self, path: str | Path) -> None:
        lock_path = Path(path).expanduser().resolve()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = lock_path
        self._lock = QLockFile(str(lock_path))
        # Do not steal a healthy long-running instance merely because its lock
        # file is old. QLockFile can still recognize and remove a lock whose
        # recorded process no longer exists.
        self._lock.setStaleLockTime(0)
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True
        self._acquired = self._lock.tryLock(0)
        return self._acquired

    def release(self) -> None:
        if not self._acquired:
            return
        self._lock.unlock()
        self._acquired = False

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise AlreadyRunningError(
                "another AniRSS instance is already using this data directory"
            )
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


__all__ = ["AlreadyRunningError", "SingleInstanceLock"]
