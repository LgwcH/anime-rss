from __future__ import annotations

import subprocess
import unittest
import winreg
from unittest.mock import patch

from anirss.core.autostart import AutostartManager


class AutostartTests(unittest.TestCase):
    def test_windows_entry_is_user_scoped_and_uses_the_expected_command(self) -> None:
        manager = AutostartManager()
        command = [r"C:\Program Files\AniRSS\AniRSS.exe", "--minimized"]

        with (
            patch("winreg.CreateKeyEx") as create_key,
            patch("winreg.SetValueEx") as set_value,
        ):
            key = create_key.return_value.__enter__.return_value
            manager.enable(command)

        create_key.assert_called_once_with(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        set_value.assert_called_once_with(
            key,
            "AniRSS",
            0,
            winreg.REG_SZ,
            subprocess.list2cmdline(command),
        )

    def test_app_name_rejects_control_characters(self) -> None:
        with self.assertRaises(ValueError):
            AutostartManager(app_name="AniRSS\nOther")


if __name__ == "__main__":
    unittest.main()
