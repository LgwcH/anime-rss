from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from anirss import app as app_module


class ApplicationPlatformTests(unittest.TestCase):
    def test_main_rejects_non_windows_before_creating_application(self) -> None:
        application = Mock()
        application.exec.return_value = 0
        stderr = StringIO()

        with (
            patch.object(app_module.sys, "platform", "linux"),
            patch.object(
                app_module,
                "create_application",
                return_value=(application, Mock(), Mock()),
            ) as create_application,
            redirect_stderr(stderr),
        ):
            result = app_module.main([])

        self.assertEqual(result, 1)
        self.assertIn("Windows 10/11", stderr.getvalue())
        create_application.assert_not_called()

    def test_version_and_help_work_on_non_windows(self) -> None:
        stdout = StringIO()
        with (
            patch.object(app_module.sys, "platform", "linux"),
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as version_exit,
        ):
            app_module.main(["--version"])
        self.assertEqual(version_exit.exception.code, 0)
        self.assertIn("AniRSS", stdout.getvalue())

        with (
            patch.object(app_module.sys, "platform", "linux"),
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit) as help_exit,
        ):
            app_module.main(["--help"])
        self.assertEqual(help_exit.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
