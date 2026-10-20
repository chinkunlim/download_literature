"""Command-line entrypoint: APA reference list → verified JSON → PDFs → report, in one command.

Usage:
    uv run fetch-literature                     # uses DATA_DIR/input/references.txt (or .md / .json)
    uv run fetch-literature --input my_list.txt # any APA list (.txt / .md) or converted .json
    uv run fetch-literature --convert-only      # only APA → references.json, no download
    uv run fetch-literature --no-browser        # open access only (no Chrome, no sign-in)
    uv run fetch-literature --only Gross_1998_EmergingField
    uv run fetch-literature --refresh Schleider_2022_NHB  # replace an author / preprint copy if possible

Steps: an APA list is split, parsed and confirmed on Crossref, then written to `<list>.json` (keys,
extra URLs and kinds from an earlier run are kept). Every reference is then downloaded, version of
record first: published open-access copies, EBSCO, the publisher through Chrome / OpenAthens, and only
then preprints / author copies (flagged in the report). PDFs and `report.md` go to
`DATA_DIR/output/literature/`.
"""

from __future__ import annotations

import argparse
import logging
from contextlib import ExitStack
from pathlib import Path

import httpx

from download_literature.adapters.literature.browser import BrowserPublisherFetcher
from download_literature.adapters.literature.crossref import CrossrefResolver
from download_literature.adapters.literature.ebsco import EbscoFetcher
from download_literature.adapters.literature.files import (
    FilePdfStore,
    find_reference_list,
    load_references,
    save_references,
)
from download_literature.adapters.literature.http_pdf import HttpPdfFetcher
from download_literature.adapters.literature.openalex import OpenAlexFinder
from download_literature.adapters.literature.pdf_text import PypdfTextReader
from download_literature.config.logging_setup import setup_logging
from download_literature.config.settings import AppConfig, load_config
from download_literature.domain.apa import split_entries
from download_literature.domain.literature import ConversionNote, DownloadStatus, Reference
from download_literature.services.literature import PublisherFetcher, Sources, download_all, render_report
from download_literature.services.reference_builder import build_references, merge_with_existing

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) download-literature/0.1 (academic use)"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line options.

    Args:
        argv: Arguments; defaults to `sys.argv[1:]`.

    Returns:
        Parsed options.
    """
    parser = argparse.ArgumentParser(description="Convert an APA reference list and download the PDFs")
    parser.add_argument(
        "--input",
        "--refs",
        type=Path,
        default=None,
        help="APA list (.txt/.md) or converted .json (default: DATA_DIR/input/references.txt|.md|.json)",
    )
    parser.add_argument("--convert-only", action="store_true", help="only convert the APA list to JSON")
    parser.add_argument(
        "--no-browser", action="store_true", help="open access only; skip the publisher route"
    )
    parser.add_argument("--only", default="", help="comma-separated reference keys to process")
    parser.add_argument(
        "--refresh",
        default="",
        help="comma-separated keys (or 'all') whose PDFs are replaced if a better copy is found",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="you are at the computer: wait for bot checks / sign-ins and retry items that need review",
    )
    parser.add_argument(
        "--wait", type=int, default=300, help="seconds to wait per check in --interactive mode"
    )
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


def _load_list(path: Path, client: httpx.Client) -> tuple[list[Reference], list[ConversionNote]]:
    """Load a reference list, converting an APA text list to JSON first.

    Args:
        path: `.txt` / `.md` APA list or `.json` reference file.
        client: HTTP client for Crossref.

    Returns:
        (references, conversion notes); notes are empty for a JSON input.
    """
    if path.suffix.lower() == ".json":
        return load_references(path), []
    entries = split_entries(path.read_text(encoding="utf-8"))
    refs, notes = build_references(entries, CrossrefResolver(client))
    json_path = path.with_suffix(".json")
    if json_path.is_file():
        refs = merge_with_existing(refs, load_references(json_path))
    save_references(json_path, refs)
    logger.info("apa list converted entries=%d refs=%d json=%s", len(entries), len(refs), json_path)
    return refs, notes


def _build_sources(
    stack: ExitStack, client: httpx.Client, config: AppConfig, args: argparse.Namespace
) -> Sources:
    """Create the OA finder, HTTP fetcher, institutional routes (EBSCO, publisher), site fetcher and store.

    Args:
        stack: Exit stack that closes the browser when the batch ends.
        client: Shared HTTP client.
        config: Settings (paths, OpenAthens domain, EBSCO profile, credentials).
        args: Parsed options (`no_browser`, `wait`).

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
    return Sources(OpenAlexFinder(client), HttpPdfFetcher(client), routes, store, PypdfTextReader(), browser)


def _refresh_keys(refs: list[Reference], value: str) -> frozenset[str]:
    """Resolve the --refresh option.

    Args:
        refs: References being processed.
        value: Comma-separated keys, or `all`.

    Returns:
        Keys to refresh.
    """
    if value.strip().lower() == "all":
        return frozenset(r.key for r in refs)
    return frozenset(k.strip() for k in value.split(",") if k.strip())


def _print_conversion(path: Path, refs: list[Reference], notes: list[ConversionNote]) -> None:
    """Print the result of a convert-only run.

    Args:
        path: Input list.
        refs: Converted references.
        notes: Conversion notes.
    """
    print(f"Converted {len(refs)} references -> {path.with_suffix('.json')}")
    for note in notes:
        print(f"- {note.message}: {note.citation}")


def main(argv: list[str] | None = None) -> int:
    """Convert the reference list, download every reference and print the report.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 when nothing failed, 1 when at least one reference failed, 2 when no list was found.
    """
    config = load_config()
    args = _parse_args(argv)
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    path = args.input or find_reference_list(config.input_dir)
    if path is None or not path.is_file():
        print(f"No reference list found. Put references.txt (APA) in {config.input_dir} or use --input.")
        return 2
    logger.info("fetch start input=%s browser=%s", path, not args.no_browser)
    with ExitStack() as stack:
        client = stack.enter_context(
            httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
        )
        refs, notes = _load_list(path, client)
        if args.convert_only:
            _print_conversion(path, refs, notes)
            return 0
        selected = _select(refs, args.only)
        sources = _build_sources(stack, client, config, args)
        outcomes = download_all(selected, sources, _refresh_keys(selected, args.refresh))
    report = render_report(outcomes, notes)
    config.literature_dir.mkdir(parents=True, exist_ok=True)
    (config.literature_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)  # the CLI's real output; logs go to stderr / files
    print(f"PDF folder: {config.literature_dir}")
    return 1 if any(o.status is DownloadStatus.FAILED for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
