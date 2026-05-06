"""
Pytest configuration: isolate DB and disable background work before importing the app.

python-dotenv's load_dotenv() does not override existing env vars, so these values win.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_fd, _db_path = tempfile.mkstemp(suffix="-aqs-test.db")
os.close(_fd)
Path(_db_path).unlink(missing_ok=True)

os.environ["DISABLE_BACKGROUND_TASKS"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_db_path).resolve().as_posix()}"
