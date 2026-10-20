"""Process-wide run lock: only one processing job (command line, web page or API) runs at a time.

Uses an OS file lock in `DATA_DIR/state/`, released automatically when the process ends.
"""

from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from types import TracebackType

from download_literature.domain.tracker import AlreadyRunningError

logger = logging.getLogger(__name__)


class RunLock:
    """Exclusive, non-blocking lock on a file."""

    def __init__(self, path: Path) -> None:
        """Create the lock (not taken yet).

        Args:
            path: Lock file path.
        """
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> RunLock:
        """Take the lock.

        Returns:
            This lock.

        Raises:
            AlreadyRunningError: When another job holds it.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise AlreadyRunningError("another job is running") from exc
        self._fd = fd
        logger.info("run lock taken path=%s", self._path)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Release the lock.

        Args:
            exc_type: Exception class, if any.
            exc: Exception, if any.
            tb: Traceback, if any.
        """
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
        logger.info("run lock released path=%s", self._path)
