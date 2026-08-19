import os
import unittest
from pathlib import Path
from unittest.mock import patch

from momentum_pact.paths import default_data_path


class DefaultDataPathTests(unittest.TestCase):
    def test_exact_environment_override_takes_precedence(self):
        with patch.dict(
            os.environ,
            {
                "MOMENTUM_PACT_DATA": "~/pact-data.json",
                "XDG_DATA_HOME": "/ignored",
            },
            clear=True,
        ):
            self.assertEqual(
                default_data_path(), Path("~/pact-data.json").expanduser()
            )

    def test_linux_uses_xdg_data_home(self):
        with (
            patch.dict(
                os.environ,
                {"XDG_DATA_HOME": "/tmp/portable-data-home"},
                clear=True,
            ),
            patch("momentum_pact.paths.sys.platform", "linux"),
        ):
            self.assertEqual(
                default_data_path(),
                Path("/tmp/portable-data-home/momentum-pact/accountability.json"),
            )

    def test_macos_uses_application_support(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("momentum_pact.paths.sys.platform", "darwin"),
            patch("momentum_pact.paths.Path.home", return_value=Path("/Users/example")),
        ):
            self.assertEqual(
                default_data_path(),
                Path(
                    "/Users/example/Library/Application Support/"
                    "momentum-pact/accountability.json"
                ),
            )

    def test_windows_uses_local_app_data(self):
        with (
            patch.dict(
                os.environ,
                {"LOCALAPPDATA": "C:/Users/example/AppData/Local"},
                clear=True,
            ),
            patch("momentum_pact.paths.sys.platform", "win32"),
        ):
            self.assertEqual(
                default_data_path(),
                Path(
                    "C:/Users/example/AppData/Local/"
                    "momentum-pact/accountability.json"
                ),
            )


if __name__ == "__main__":
    unittest.main()
