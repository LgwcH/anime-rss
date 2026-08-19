from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anirss.core.autostart import AutostartManager


class AutostartTests(unittest.TestCase):
    def test_linux_entry_is_user_scoped_and_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            config = home / "config"
            executable = home / "AniRSS app"
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config)}):
                manager = AutostartManager(platform_name="linux", home=home)
                manager.enable([str(executable), "--minimized"])
                self.assertTrue(manager.is_enabled())
                self.assertTrue(manager.is_configured([str(executable), "--minimized"]))
                self.assertFalse(manager.is_configured([str(executable)]))
                config_path = manager.config_path
                assert config_path is not None
                content = config_path.read_text(encoding="utf-8")
                escaped_executable = str(executable).replace("\\", "\\\\")
                self.assertIn(f'Exec="{escaped_executable}" "--minimized"', content)
                manager.disable()
                self.assertFalse(manager.is_enabled())

    def test_app_id_cannot_traverse(self) -> None:
        with self.assertRaises(ValueError):
            AutostartManager(app_id="../../outside")


if __name__ == "__main__":
    unittest.main()
