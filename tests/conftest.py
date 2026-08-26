"""Root pytest fixture: keeps tests from ever touching the real ./data directory.

Runs at import time, before pytest collects any test module. This matters because
backend.config.DATA_DIR (and everything derived from it at import time, e.g.
FAVORITES_PATH, DATABASE_PATH, GENERATION_COUNTER_PATH) is a module-level constant
computed from PLAYLISTMUSE_DATA_DIR the first time backend.config is imported -- by
which point a per-test monkeypatch is already too late for anything that forgets to
override its own path constant. Individual tests still monkeypatch specific path
constants for fine-grained control; this is only the fallback for the rest.
"""

import os
import shutil
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="playlistmuse-test-data-")
os.environ.setdefault("PLAYLISTMUSE_DATA_DIR", _TEST_DATA_DIR)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
