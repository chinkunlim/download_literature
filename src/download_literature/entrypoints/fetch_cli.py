"""Command-line entrypoint: the Markdown reference list in, PDFs and an updated list out (ADR-005).

Usage:
    uv run fetch-literature                 # process new / retry entries of DATA_DIR/input/references.md
    uv run fetch-literature --interactive   # at the computer: also handle ⚠️ items (bot checks, sign-ins)
    uv run fetch-literature --identify-only # only identify new entries and write APA 7, no download
    uv run fetch-literature --no-browser    # open access only (no Chrome)
    uv run fetch-literature --refresh Gross_1998_RGP   # try to replace an author / preprint copy
    uv run fetch-literature --only Webb_2012_PsychBull # limit this run to some keys

Steps: read the list → apply the user's edits (deleted rows, '重試') → identify new lines (Crossref,
OpenAlex) and write APA 7 → download the selected items (version of record first; steps that need a
person are skipped unless --interactive) → write the status, file and notes back into the list.
State lives next to the list in `references.json`; PDFs go to `DATA_DIR/output/literature/`.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import httpx

from download_literature.adapters.literature.browser import BrowserPublisherFetcher
from download_literature.adapters.literature.crossref import CrossrefResolver
from download_literature.adapters.literature.ebsco import EbscoFetcher
from download_literature.adapters.literature.files import FilePdfStore, load_items, save_items
from download_literature.adapters.literature.http_pdf import HttpPdfFetcher
from download_literature.adapters.literature.metadata import CombinedResolver
from download_literature.adapters.literature.openalex import OpenAlexFinder, OpenAlexResolver
from download_literature.adapters.literature.openlibrary import OpenLibraryBooks
from download_literature.adapters.literature.pdf_text import PypdfTextReader
from download_literature.adapters.literature.tracker_md import (
    STATUS_LABELS,
    parse_tracker_md,
    render_tracker_md,
)
from download_literature.config.logging_setup import setup_logging
from download_literature.config.settings import AppConfig, load_config
from download_literature.domain.tracker import ItemStatus, TrackedItem
from download_literature.services.literature import PublisherFetcher, Sources, download_all
from download_literature.services.reference_builder import resolve_entry
from download_literature.services.tracker import (
    add_new_entries,
    apply_md_edits,
    apply_outcomes,
    refresh_identification,
    select_items,
)

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) download-literature/0.1 (academic use)"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line options.

    Args:
        argv: Arguments; defaults to `sys.argv[1:]`.

    Returns:
        Parsed options.
    """
    parser = argparse.ArgumentParser(description="Process the Markdown reference list and download the PDFs")
    parser.add_argument(
        "--input", type=Path, default=None, help="list file (default: DATA_DIR/input/references.md)"
    )
    parser.add_argument("--identify-only", action="store_true", help="identify new entries, no download")
    parser.add_argument("--no-browser", action="store_true", help="open access only; no Chrome")
    parser.add_argument("--only", default="", help="comma-separated keys to process in this run")
    parser.add_argument(
        "--refresh", default="", help="comma-separated keys whose PDF should be replaced if better"
    )
    parser.add_argument(
        "--interactive", action="store_true", help="wait for bot checks / sign-ins; retry ⚠️ items"
    )
    parser.add_argument(
        "--wait", type=int, default=300, help="seconds to wait per check in --interactive mode"
    )
    return parser.parse_args(argv)


def _keys(value: str) -> set[str]:
    """Split a comma-separated key option.

    Args:
        value: Option text.

    Returns:
        Keys.
    """
    return {k.strip() for k in value.split(",") if k.strip()}


def _to_process(items: list[TrackedItem], args: argparse.Namespace) -> list[TrackedItem]:
    """Choose this run's items: pending (+ ⚠️ when interactive) and --refresh keys, limited by --only.

    Args:
        items: All items.
        args: Parsed options.

    Returns:
        Items to download.
    """
    chosen = {i.key for i in select_items(items, args.interactive)} | _keys(args.refresh)
    only = _keys(args.only)
    return [i for i in items if i.key in chosen and i.reference is not None and (not only or i.key in only)]


def _build_sources(
    stack: ExitStack, client: httpx.Client, config: AppConfig, args: argparse.Namespace
) -> Sources:
    """Create the download sources: open access, EBSCO and publisher (Chrome), books and the PDF store.

    Args:
        stack: Exit stack that closes the browser when the batch ends.
        client: Shared HTTP client.
        config: Settings (paths, OpenAthens domain, EBSCO profile, credentials).
        args: Parsed options (`no_browser`, `interactive`, `wait`).

    Returns:
        The wired download sources.
    """
    routes: tuple[PublisherFetcher, ...] = ()
    browser: BrowserPublisherFetcher | None = None
    if not args.no_browser:
        login = (config.library_email, config.library_password)
        wait = args.wait if args.interactive else 0  # unattended: skip steps that need a person (ADR-004)
        browser = BrowserPublisherFetcher(config.browser_profile_dir, config.openathens_domain, login, wait)
        stack.enter_context(browser)
        ebsco = (EbscoFetcher(browser, config.ebsco_profile),) if config.ebsco_profile else ()
        routes = (*ebsco, browser)  # EBSCO first: version of record with fewer bot checks (ADR-003)
    store = FilePdfStore(config.literature_dir)
    return Sources(
        OpenAlexFinder(client),
        HttpPdfFetcher(client),
        routes,
        store,
        PypdfTextReader(),
        browser,
        OpenLibraryBooks(client),
    )


def _write_list(md_path: Path, items: list[TrackedItem], config: AppConfig) -> None:
    """Save the state JSON and rewrite the Markdown list.

    Args:
        md_path: Markdown list path.
        items: All items.
        config: Settings (PDF folder for file links).
    """
    save_items(md_path.with_suffix(".json"), items)
    file_base = os.path.relpath(config.literature_dir, md_path.parent)
    md_path.write_text(render_tracker_md(items, file_base), encoding="utf-8")


def _print_summary(md_path: Path, items: list[TrackedItem], processed: int, skipped: list[str]) -> None:
    """Print what the run did.

    Args:
        md_path: Markdown list path.
        items: All items after the run.
        processed: Number of items downloaded this run.
        skipped: New lines skipped because they were already listed.
    """
    counts = Counter(i.status for i in items)
    print(f"清單：{md_path}（共 {len(items)} 筆，本次處理 {processed} 筆）")
    for status in ItemStatus:
        if counts[status]:
            print(f"  {STATUS_LABELS[status]}：{counts[status]}")
    for line in skipped:
        print(f"  已在清單中，略過：{line}")
    if counts[ItemStatus.NEEDS_REVIEW]:
        print("  在電腦前時執行：uv run fetch-literature --interactive")


def main(argv: list[str] | None = None) -> int:
    """Process the reference list once.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 (problems are recorded per item in the list).
    """
    config = load_config()
    args = _parse_args(argv)
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    md_path: Path = args.input or config.input_dir / "references.md"
    edits = parse_tracker_md(md_path.read_text(encoding="utf-8") if md_path.is_file() else "")
    items = apply_md_edits(load_items(md_path.with_suffix(".json")), edits.rows)
    logger.info("list start file=%s items=%d new=%d", md_path, len(items), len(edits.pending))
    with ExitStack() as stack:
        client = stack.enter_context(
            httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
        )
        resolver = CombinedResolver([CrossrefResolver(client), OpenAlexResolver(client)])
        items = refresh_identification(items, resolver, resolve_entry)
        items, skipped = add_new_entries(items, edits.pending, resolver, resolve_entry)
        _write_list(md_path, items, config)  # new entries are saved even if the download is interrupted
        todo = [] if args.identify_only else _to_process(items, args)
        if todo:
            refs = [i.reference for i in todo if i.reference is not None]
            outcomes = download_all(
                refs, _build_sources(stack, client, config, args), frozenset(_keys(args.refresh))
            )
            items = apply_outcomes(items, outcomes)
    _write_list(md_path, items, config)
    _print_summary(md_path, items, len(todo), skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
