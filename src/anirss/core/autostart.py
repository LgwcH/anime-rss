"""Safe, user-scoped autostart configuration for desktop platforms."""

from __future__ import annotations

import os
import plistlib
import re
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
    """Configure startup for only the current user; never invokes a shell.

    Windows uses HKCU's Run key, macOS uses ``~/Library/LaunchAgents``, and
    Linux/other freedesktop desktops use ``~/.config/autostart``.  No admin
    rights, system directories, or login-shell scripts are involved.
    """

    def __init__(
        self,
        app_name: str = "AniRSS",
        app_id: str = "org.anirss.desktop",
        *,
        platform_name: str | None = None,
        home: str | Path | None = None,
    ) -> None:
        if not app_name or any(character in app_name for character in "\x00\r\n"):
            raise ValueError("app_name contains unsafe characters")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", app_id):
            raise ValueError(
                "app_id may contain only letters, digits, dots, dashes, and underscores"
            )
        self.app_name = app_name
        self.app_id = app_id
        self.platform_name = platform_name or sys.platform
        self.home = Path(home).expanduser().resolve() if home else Path.home().resolve()

    @property
    def config_path(self) -> Path | None:
        if self.platform_name == "darwin":
            return self.home / "Library" / "LaunchAgents" / f"{self.app_id}.plist"
        if self.platform_name.startswith("win"):
            return None
        xdg = os.environ.get("XDG_CONFIG_HOME")
        config_root = Path(xdg).expanduser() if xdg else self.home / ".config"
        return config_root.resolve() / "autostart" / f"{self.app_id}.desktop"

    def enable(self, command: Sequence[str] | None = None) -> None:
        command = _validate_command(default_launch_command() if command is None else command)
        if self.platform_name.startswith("win"):
            self._windows_enable(command)
        elif self.platform_name == "darwin":
            self._macos_enable(command)
        else:
            self._linux_enable(command)

    def disable(self) -> None:
        if self.platform_name.startswith("win"):
            self._windows_disable()
            return
        path = self.config_path
        if path and path.exists():
            try:
                path.unlink()
            except OSError as exc:
                raise AutostartError(f"could not remove autostart entry: {exc}") from exc

    def is_enabled(self) -> bool:
        if self.platform_name.startswith("win"):
            return self._windows_is_enabled()
        path = self.config_path
        return bool(path and path.is_file())

    def is_configured(self, command: Sequence[str]) -> bool:
        """Return whether the user startup entry exactly launches *command*.

        Merely checking for an entry is insufficient for portable apps: moving
        or upgrading the application can leave Windows pointing at an old EXE.
        """

        values = _validate_command(command)
        if self.platform_name.startswith("win"):
            return self._windows_value() == subprocess.list2cmdline(values)
        path = self.config_path
        if path is None or not path.is_file():
            return False
        try:
            if self.platform_name == "darwin":
                payload = plistlib.loads(path.read_bytes())
                return bool(payload.get("RunAtLoad")) and payload.get("ProgramArguments") == values
            expected_exec = "Exec=" + " ".join(self._desktop_quote(part) for part in values)
            return expected_exec in path.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, plistlib.InvalidFileException):
            return False

    def set_enabled(self, enabled: bool, command: Sequence[str] | None = None) -> bool:
        if enabled:
            self.enable(command)
        else:
            self.disable()
        return self.is_enabled()

    def _linux_enable(self, command: Sequence[str]) -> None:
        path = self.config_path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        exec_value = " ".join(self._desktop_quote(part) for part in command)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={self.app_name}\n"
            f"Exec={exec_value}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        self._atomic_write(path, content.encode("utf-8"))

    def _macos_enable(self, command: Sequence[str]) -> None:
        path = self.config_path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": self.app_id,
            "ProgramArguments": list(command),
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }
        self._atomic_write(path, plistlib.dumps(payload, fmt=plistlib.FMT_XML))

    def _windows_enable(self, command: Sequence[str]) -> None:
        try:
            import winreg
        except ImportError as exc:  # pragma: no cover - only possible off Windows
            raise AutostartError("Windows registry support is unavailable") from exc
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
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
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
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
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                value, value_type = winreg.QueryValueEx(key, self.app_name)
            return str(value) if value_type == winreg.REG_SZ else None
        except OSError:
            return None

    @staticmethod
    def _desktop_quote(value: str) -> str:
        escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise AutostartError(f"could not write autostart entry: {exc}") from exc


__all__ = ["AutostartError", "AutostartManager", "default_launch_command"]
