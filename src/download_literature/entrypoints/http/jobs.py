"""Background job manager for the web app: runs `Runner.process` in one worker thread at a time.

The browser (Playwright, sync API) stays inside that thread. A second start while a job runs is
refused; a job started while the command line holds the run lock ends with a clear error message.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from download_literature.domain.tracker import AlreadyRunningError
from download_literature.entrypoints.runner import ProcessOptions, RunSummary

logger = logging.getLogger(__name__)


class JobManager:
    """Starts processing runs in the background and remembers how the last one ended."""

    def __init__(self, process: Callable[[ProcessOptions], RunSummary]) -> None:
        """Create the manager.

        Args:
            process: Function that processes the list once (normally `Runner.process`).
        """
        self._process = process
        self._thread: threading.Thread | None = None
        self._guard = threading.Lock()
        self.last_error = ""
        self.last_summary: RunSummary | None = None

    def running(self) -> bool:
        """Tell whether a job is running in this web app.

        Returns:
            True while the worker thread is alive.
        """
        return self._thread is not None and self._thread.is_alive()

    def start(self, options: ProcessOptions) -> bool:
        """Start a processing run unless one is already running.

        Args:
            options: Process options.

        Returns:
            False when a job is already running.
        """
        with self._guard:
            if self.running():
                return False
            self.last_error = ""
            self._thread = threading.Thread(
                target=self._run, args=(options,), name="literature-job", daemon=True
            )
            self._thread.start()
            return True

    def _run(self, options: ProcessOptions) -> None:
        """Worker: run the job and record the result or error.

        Args:
            options: Process options.
        """
        try:
            self.last_summary = self._process(options)
        except AlreadyRunningError:
            self.last_error = "另一個處理工作正在執行（例如指令列），請稍後再試。"
        except Exception as exc:  # report any failure on the page; details are in the log
            logger.exception("web job failed")
            self.last_error = f"處理時發生錯誤：{type(exc).__name__}（詳情見 log）"

    def summary_text(self) -> str:
        """Describe the last finished run for the page.

        Returns:
            e.g. "加入 0 筆、辨識 1 筆、處理 0 筆；略過重複：…"; empty before the first run.
        """
        summary = self.last_summary
        if summary is None:
            return ""
        queued, identified, processed = len(summary.queued), summary.identify.changed, len(summary.processed)
        text = f"加入 {queued} 筆、辨識 {identified} 筆、處理 {processed} 筆"
        if summary.identify.duplicates:
            text += "；略過重複：" + "、".join(summary.identify.duplicates)
        return text

    def wait(self, timeout: float) -> None:
        """Wait for the running job (tests, shutdown).

        Args:
            timeout: Seconds to wait at most.
        """
        if self._thread is not None:
            self._thread.join(timeout)
