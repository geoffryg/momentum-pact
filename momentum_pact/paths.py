"""Shared filesystem paths for Momentum Pact interfaces."""

import os
import sys
from pathlib import Path


def default_data_path() -> Path:
    """Return a writable, platform-appropriate path for personal data."""
    override = os.environ.get("MOMENTUM_PACT_DATA")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        root = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "momentum-pact" / "accountability.json"


DEFAULT_DATA_PATH = default_data_path()
