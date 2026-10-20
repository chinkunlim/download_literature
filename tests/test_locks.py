"""Tests for the run lock."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.locks import RunLock  # noqa: E402
from download_literature.domain.tracker import AlreadyRunningError  # noqa: E402


class RunLockTest(unittest.TestCase):
    """Only one job at a time."""

    def test_second_lock_fails_until_released(self) -> None:
        """A second holder is refused while the first holds the lock, and succeeds afterwards."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.lock"
            with RunLock(path):
                with self.assertRaises(AlreadyRunningError):
                    RunLock(path).__enter__()
            with RunLock(path):
                pass


if __name__ == "__main__":
    unittest.main()
