"""Command-line entrypoint for downloading literature PDFs.

Usage:
    uv run fetch-literature                      # open access first, then publisher via Chrome
    uv run fetch-literature --no-browser         # open access only (no Chrome, no sign-in)
    uv run fetch-literature --only Gross_1998_RGP,Webb_2012_PsychBull

Reads `DATA_DIR/input/references.json` (or `--refs`), saves PDFs and `report.md` in
`DATA_DIR/output/literature/`, and prints the report.
"""

from __future__ import annotations

import argparse
import logging
from contextlib import ExitStack
from pathlib import Path

import httpx

from download_literature.adapters.literature.browser import BrowserPublisherFetcher
from download_literature.adapters.literature.files import FilePdfStore, load_references
from download_literature.adapters.literature.http_pdf import HttpPdfFetcher
from download_literature.adapters.literature.openalex import OpenAlexFinder
from download_literature.adapters.literature.pdf_text import PypdfTextReader
from download_literature.config.logging_setup import setup_logging
from download_literature.config.settings import AppConfig, load_config
from download_literature.domain.literature import DownloadStatus, Reference
from download_literature.services.literature import PublisherFetcher, Sources, download_all, render_report

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) download-literature/0.1 (academic use)"


def _parse_args(argv: list[str] | None, config: AppConfig) -> argparse.Namespace:
    """Parse command-line options.

    Args:
        argv: Arguments; defaults to `sys.argv[1:]`.
        config: Settings providing default paths.

    Returns:
        Parsed options.
    """
    parser = argparse.ArgumentParser(description="Download the PDFs of a reference list")
    parser.add_argument(
        "--refs",
        type=Path,
        default=config.input_dir / "references.json",
        help="JSON reference list (default: DATA_DIR/input/references.json)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="open access only; skip the publisher route"
    )
    parser.add_argument("--only", default="", help="comma-separated reference keys to process")
    parser.add_argument("--wait", type=int, default=300, help="seconds to wait for a manual sign-in / check")
    return parser.parse_args(argv)


def _select(refs: list[Reference], only: str) -> list[Reference]:
    """Keep only the requested keys.

    Args:
        refs: All references.
        only: Comma-separated keys; empty keeps everything.

    Returns:
        The selected references.
    """
    keys = {k.strip() for k in only.split(",") if k.strip()}
    return [r for r in refs if not keys or r.key in keys]


def _build_sources(stack: ExitStack, config: AppConfig, args: argparse.Namespace) -> Sources:
    """Create the HTTP client, OA finder, optional Chrome fetcher and PDF store.

    Args:
        stack: Exit stack that closes the client and browser when the batch ends.
        config: Settings (paths, OpenAthens domain, credentials).
        args: Parsed options (`no_browser`, `wait`).

    Returns:
        The wired download sources.
    """
    headers = {"User-Agent": USER_AGENT}
    client = stack.enter_context(httpx.Client(headers=headers, follow_redirects=True, timeout=60))
    publisher: PublisherFetcher | None = None
    if not args.no_browser:
        login = (config.library_email, config.library_password)
        browser = BrowserPublisherFetcher(
            config.browser_profile_dir, config.openathens_domain, login, args.wait
        )
        publisher = stack.enter_context(browser)
    store = FilePdfStore(config.literature_dir)
    return Sources(OpenAlexFinder(client), HttpPdfFetcher(client), publisher, store, PypdfTextReader())


def main(argv: list[str] | None = None) -> int:
    """Download every reference and print the report.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 when nothing failed, 1 when at least one reference failed.
    """
    config = load_config()
    args = _parse_args(argv, config)
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    refs = _select(load_references(args.refs), args.only)
    logger.info("fetch start refs=%s count=%d browser=%s", args.refs, len(refs), not args.no_browser)
    with ExitStack() as stack:
        outcomes = download_all(refs, _build_sources(stack, config, args))
    report = render_report(outcomes)
    config.literature_dir.mkdir(parents=True, exist_ok=True)
    (config.literature_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)  # the CLI's real output; logs go to stderr / files
    print(f"PDF folder: {config.literature_dir}")
    return 1 if any(o.status is DownloadStatus.FAILED for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
