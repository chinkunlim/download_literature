"""Composition root shared by the command line, the web app and the HTTP API (ADR-006).

`Runner` wires config, database, metadata services and download routes, and offers the operations
every front end needs: add entries, retry / delete items, process the list (one job at a time) and
rewrite the two Markdown files (`input/references.md`, `output/report.md`).
"""

from __future__ import annotations

import logging
import os
import shutil
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import httpx

from download_literature.adapters.db.engine import create_db_engine, upgrade_database
from download_literature.adapters.db.repository import SqlItemStore
from download_literature.adapters.literature.airiti import AiritiLibrary
from download_literature.adapters.literature.browser import BrowserPublisherFetcher
from download_literature.adapters.literature.crossref import CrossrefResolver
from download_literature.adapters.literature.ebsco import EbscoFetcher
from download_literature.adapters.literature.files import FilePdfStore, load_items
from download_literature.adapters.literature.http_pdf import HttpPdfFetcher
from download_literature.adapters.literature.metadata import CombinedResolver
from download_literature.adapters.literature.openalex import OpenAlexFinder, OpenAlexResolver
from download_literature.adapters.literature.openlibrary import OpenLibraryBooks
from download_literature.adapters.literature.pdf_text import PypdfTextReader
from download_literature.adapters.literature.report_md import render_report_md
from download_literature.adapters.literature.tracker_md import pending_text, render_input_md
from download_literature.adapters.locks import RunLock
from download_literature.config.settings import AppConfig
from download_literature.domain.literature import has_cjk
from download_literature.domain.tracker import ItemStatus, TrackedItem
from download_literature.services.literature import PublisherFetcher, Sources
from download_literature.services.reference_builder import WorkResolver, resolve_entry
from download_literature.services.tracker import (
    IdentifyResult,
    download_items,
    identify_pending,
    queue_entries,
    split_pending,
)

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) download-literature/0.1 (academic use)"
RETRYABLE = (
    ItemStatus.NEEDS_REVIEW,
    ItemStatus.UNAVAILABLE,
    ItemStatus.NOT_FOUND,
    ItemStatus.BORROW,
    ItemStatus.DOWNLOADED_COPY,
)


@dataclass(frozen=True)
class ProcessOptions:
    """How to process the list.

    Attributes:
        interactive: The user is at the computer: wait for bot checks and also retry ⚠️ items.
        wait_seconds: Seconds to wait per check when interactive.
        use_browser: Use Chrome (EBSCO, publisher sites); False = open access only.
        only: Limit the run to these keys (empty = no limit).
        refresh: Keys whose PDF should be replaced by a better copy if one is found.
        identify_only: Identify new entries and write APA, but do not download.
    """

    interactive: bool = False
    wait_seconds: int = 300
    use_browser: bool = True
    only: frozenset[str] = field(default_factory=frozenset)
    refresh: frozenset[str] = field(default_factory=frozenset)
    identify_only: bool = False


@dataclass(frozen=True)
class RunSummary:
    """What one processing run did.

    Attributes:
        queued: Entries taken from references.md.
        identify: Identification result (changes, duplicates dropped).
        processed: Keys downloaded / checked.
        job_id: Download job id, or None when nothing was downloaded.
    """

    queued: list[str]
    identify: IdentifyResult
    processed: list[str]
    job_id: int | None


class Runner:
    """Operations shared by every front end."""

    def __init__(self, config: AppConfig) -> None:
        """Open (and migrate) the database.

        Args:
            config: Application settings.
        """
        self.config = config
        upgrade_database(config.database_url)
        self.store = SqlItemStore(create_db_engine(config.database_url))
        self._migrate_legacy_json()

    @property
    def input_md(self) -> Path:
        """Path of the user's input list.

        Returns:
            `DATA_DIR/input/references.md`.
        """
        return self.config.input_dir / "references.md"

    @property
    def report_md(self) -> Path:
        """Path of the report.

        Returns:
            `DATA_DIR/output/report.md`.
        """
        return self.config.output_dir / "report.md"

    def _migrate_legacy_json(self) -> None:
        """Import the old `input/references.json` once (database empty), then archive the file."""
        legacy = self.config.input_dir / "references.json"
        if not legacy.is_file() or self.store.list_items():
            return
        for item in load_items(legacy):
            self.store.add(item)
        archive = self.config.data_dir / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), archive / f"references.json.migrated-{datetime.now():%Y%m%d-%H%M%S}")
        logger.info("legacy list migrated into the database from=%s", legacy)

    def add_entries(self, lines: list[str]) -> list[str]:
        """Queue new entries (identified when the list is processed).

        Args:
            lines: Entries as written by the user.

        Returns:
            Keys of the queued items.
        """
        keys = queue_entries(self.store, lines)
        self.write_files()
        return keys

    def retry(self, keys: set[str]) -> list[str]:
        """Set items back to pending so the next run processes them again.

        Args:
            keys: Item keys.

        Returns:
            Keys actually reset.
        """
        reset = []
        for key in sorted(keys):
            item = self.store.get(key)
            if item is not None and item.status is not ItemStatus.PENDING:
                self.store.update(replace(item, status=ItemStatus.PENDING))
                reset.append(key)
        self.write_files()
        return reset

    def reidentify(self, keys: set[str]) -> list[str]:
        """Look items up again (new APA text and metadata) at the next run, then download if needed.

        Args:
            keys: Item keys.

        Returns:
            Keys marked for re-identification.
        """
        marked = []
        for key in sorted(keys):
            item = self.store.get(key)
            if item is not None and item.reference is not None:
                status = ItemStatus.PENDING if item.status is not ItemStatus.DOWNLOADED else item.status
                self.store.update(replace(item, apa="", status=status))
                marked.append(key)
        self.write_files()
        return marked

    def delete(self, keys: set[str]) -> list[str]:
        """Remove items from the list (downloaded PDFs are kept on disk).

        Args:
            keys: Item keys.

        Returns:
            Keys removed.
        """
        removed = [k for k in sorted(keys) if self.store.delete(k)]
        self.write_files()
        return removed

    def take_md_entries(self) -> list[str]:
        """Read the pending section of references.md and queue its entries (the section is then emptied).

        Returns:
            Keys queued.
        """
        if not self.input_md.is_file():
            return []
        entries = split_pending(pending_text(self.input_md.read_text(encoding="utf-8")))
        if not entries:
            return []
        keys = queue_entries(self.store, entries)
        self.write_files(keep_pending=False)
        return keys

    def _to_process(self, options: ProcessOptions) -> list[str]:
        """Choose the keys a run downloads.

        Args:
            options: Process options.

        Returns:
            Pending keys (plus ⚠️ when interactive) and refresh keys, limited by `only`.
        """
        wanted = {ItemStatus.PENDING} | ({ItemStatus.NEEDS_REVIEW} if options.interactive else set())
        keys = [
            i.key
            for i in self.store.list_items()
            if i.reference is not None and (i.status in wanted or i.key in options.refresh)
        ]
        return [k for k in keys if not options.only or k in options.only]

    def _browser(self, stack: ExitStack, options: ProcessOptions) -> BrowserPublisherFetcher:
        """Start the shared Chrome session for this run.

        Args:
            stack: Exit stack that closes the browser at the end of the run.
            options: Process options (interactive waiting).

        Returns:
            The started browser.
        """
        cfg = self.config
        wait = options.wait_seconds if options.interactive else 0  # unattended: skip steps needing a person
        browser = BrowserPublisherFetcher(
            cfg.browser_profile_dir, cfg.openathens_domain, (cfg.library_email, cfg.library_password), wait
        )
        stack.enter_context(browser)
        return browser

    def _sources(self, client: httpx.Client, browser: BrowserPublisherFetcher | None) -> Sources:
        """Build the download sources for one run.

        Args:
            client: Shared HTTP client.
            browser: Started Chrome session, or None for open access only.

        Returns:
            The wired sources: Airiti (Chinese), EBSCO, then the publisher site (ADR-003, ADR-007).
        """
        cfg = self.config
        routes: tuple[PublisherFetcher, ...] = ()
        if browser is not None:
            ebsco = (EbscoFetcher(browser, cfg.ebsco_profile),) if cfg.ebsco_profile else ()
            routes = (AiritiLibrary(browser), *ebsco, browser)
        return Sources(
            OpenAlexFinder(client),
            HttpPdfFetcher(client),
            routes,
            FilePdfStore(cfg.literature_dir),
            PypdfTextReader(),
            browser,
            OpenLibraryBooks(client),
        )

    def _needs_browser_to_identify(self) -> bool:
        """Tell whether pending entries include Chinese text (identified through Airiti in Chrome).

        Returns:
            True when a Chinese entry is waiting to be identified (new, or marked for re-identification).
        """
        return any(
            has_cjk(i.input) and ((i.reference is None and i.status is ItemStatus.PENDING) or not i.apa)
            for i in self.store.list_items()
        )

    def process(self, options: ProcessOptions) -> RunSummary:
        """Run the list once: take md entries, identify, download, rewrite the Markdown files.

        Args:
            options: Process options.

        Returns:
            What the run did.

        Raises:
            AlreadyRunningError: When another job is running.
        """
        with RunLock(self.config.state_dir / "run.lock"), ExitStack() as stack:
            queued = self.take_md_entries()
            client = stack.enter_context(
                httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
            )
            browser = None
            if options.use_browser and self._needs_browser_to_identify():
                browser = self._browser(stack, options)
            services: list[WorkResolver] = [CrossrefResolver(client), OpenAlexResolver(client)]
            services += [AiritiLibrary(browser)] if browser else []
            identified = identify_pending(self.store, CombinedResolver(services), resolve_entry)
            self.write_files()
            keys = [] if options.identify_only else self._to_process(options)
            job_id = None
            if keys:
                if options.use_browser and browser is None:
                    browser = self._browser(stack, options)
                job_id = download_items(self.store, keys, self._sources(client, browser), options.refresh)
        self.write_files()
        return RunSummary(queued, identified, keys, job_id)

    def write_files(self, keep_pending: bool = True) -> None:
        """Rewrite references.md (compact processed list) and report.md.

        Args:
            keep_pending: Keep what the user has typed in the pending section (False only right after
                those entries were queued).
        """
        items: list[TrackedItem] = self.store.list_items()
        pending: list[str] = []
        if keep_pending and self.input_md.is_file():
            raw = pending_text(self.input_md.read_text(encoding="utf-8")).strip("\n").splitlines()
            pending = [line for line in raw if line.strip() not in ("-", "*", "+")]
        self.input_md.parent.mkdir(parents=True, exist_ok=True)
        self.input_md.write_text(render_input_md(items, pending), encoding="utf-8")
        self.report_md.parent.mkdir(parents=True, exist_ok=True)
        file_base = os.path.relpath(self.config.literature_dir, self.report_md.parent)
        stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
        self.report_md.write_text(render_report_md(items, file_base, stamp), encoding="utf-8")
