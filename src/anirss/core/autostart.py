"""Safe, user-scoped Windows autostart configuration."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path


class AutostartError(RuntimeError):
    pass


def default_launch_command(*, minimized: bool = False) -> list[str]:
    command = [str(Path(sys.executable).resolve())]
    if not getattr(sys, "frozen", False):
        command.extend(["-m", "anirss"])
    if minimized:
        command.append("--minimized")
    return command


def _validate_command(command: Sequence[str]) -> list[str]:
    values = [str(part) for part in command]
    if not values or not values[0].strip():
        raise AutostartError("autostart command cannot be empty")
    if any("\x00" in part or "\n" in part or "\r" in part for part in values):
        raise AutostartError("autostart command contains unsafe control characters")
    executable = Path(values[0]).expanduser()
    if not executable.is_absolute():
        raise AutostartError("autostart executable must be an absolute path")
    return values


class AutostartManager:
    """Configure the current user's Windows HKCU ``Run`` entry."""

    _RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(
        self,
        app_name: str = "AniRSS",
    ) -> None:
        if not app_name or any(character in app_name for character in "\x00\r\n"):
            raise ValueError("app_name contains unsafe characters")
        self.app_name = app_name

    def enable(self, command: Sequence[str] | None = None) -> None:
        command = _validate_command(default_launch_command() if command is None else command)
        self._windows_enable(command)

    def disable(self) -> None:
        self._windows_disable()

    def is_enabled(self) -> bool:
        return self._windows_is_enabled()

    def is_configured(self, command: Sequence[str]) -> bool:
        """Return whether the user startup entry exactly launches *command*.

        Merely checking for an entry is insufficient for portable apps: moving
        or upgrading the application can leave Windows pointing at an old EXE.
        """

        values = _validate_command(command)
        return self._windows_value() == subprocess.list2cmdline(values)

    def set_enabled(self, enabled: bool, command: Sequence[str] | None = None) -> bool:
        if enabled:
            self.enable(command)
        else:
            self.disable()
        return self.is_enabled()

    def _windows_enable(self, command: Sequence[str]) -> None:
        try:
            import winreg
        except ImportError as exc:  # pragma: no cover - only possible off Windows
            raise AutostartError("Windows registry support is unavailable") from exc
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                self._RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key, self.app_name, 0, winreg.REG_SZ, subprocess.list2cmdline(command)
                )
        except OSError as exc:
            raise AutostartError(f"could not update Windows autostart: {exc}") from exc

    def _windows_disable(self) -> None:
        try:
            import winreg
        except ImportError as exc:  # pragma: no cover
            raise AutostartError("Windows registry support is unavailable") from exc
        try:
            with (
                winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    self._RUN_KEY,
                    0,
                    winreg.KEY_SET_VALUE,
                ) as key,
                suppress(FileNotFoundError),
            ):
                winreg.DeleteValue(key, self.app_name)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise AutostartError(f"could not disable Windows autostart: {exc}") from exc

    def _windows_is_enabled(self) -> bool:
        return self._windows_value() is not None

    def _windows_value(self) -> str | None:
        try:
            import winreg
        except ImportError:  # pragma: no cover
            return None
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self._RUN_KEY,
            ) as key:
                value, value_type = winreg.QueryValueEx(key, self.app_name)
            return str(value) if value_type == winreg.REG_SZ else None
        except OSError:
            return None


__all__ = ["AutostartError", "AutostartManager", "default_launch_command"]
