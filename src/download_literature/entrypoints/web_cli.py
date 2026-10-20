"""Start the web app: `uv run literature-web` → http://127.0.0.1:8765 (local only, ADR-008)."""

from __future__ import annotations

import logging

import uvicorn

from download_literature.config.logging_setup import setup_logging
from download_literature.config.settings import load_config
from download_literature.entrypoints.http.app import create_app
from download_literature.entrypoints.http.jobs import JobManager
from download_literature.entrypoints.runner import Runner

logger = logging.getLogger(__name__)


def main() -> int:
    """Run the web server until stopped (Ctrl-C).

    Returns:
        Process exit code.
    """
    config = load_config()
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    runner = Runner(config)
    app = create_app(runner, JobManager(runner.process), config.http_port)
    print(f"文獻下載網頁：http://127.0.0.1:{config.http_port}　（Ctrl-C 結束）")
    uvicorn.run(app, host="127.0.0.1", port=config.http_port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
