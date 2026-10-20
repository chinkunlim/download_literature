"""Literature download flow, version of record first (ADR-003).

Order: books → manual; existing file → skip (unless refreshed); published open-access copies;
institutional routes in order (EBSCO, publisher site); then preprints / accepted manuscripts / listed
URLs (plain HTTP, then the browser). Copies from the last step are flagged in the outcome.
Sources are passed in (dependency injection), so the same flow runs offline in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from download_literature.domain.literature import (
    BookInfo,
    ConversionNote,
    DownloadOutcome,
    DownloadStatus,
    OaLocation,
    Reference,
    ReferenceKind,
    SourceError,
    is_pdf,
    title_matches,
)

logger = logging.getLogger(__name__)


AUTHOR_COPY_NOTE = "author/preprint copy: check page numbers against the published version"


class OpenAccessFinder(Protocol):
    """Finds open-access PDF copies for a DOI."""

    def find_pdf_locations(self, doi: str) -> list[OaLocation]:
        """Look up OA PDF copies.

        Args:
            doi: DOI without prefix.

        Returns:
            Copies with their version, best first.
        """
        ...


class PdfFetcher(Protocol):
    """Downloads one URL without a browser."""

    def fetch(self, url: str) -> bytes | None:
        """Download a URL.

        Args:
            url: PDF or landing-page URL.

        Returns:
            PDF bytes, or None when the URL did not yield a PDF.
        """
        ...


class PublisherFetcher(Protocol):
    """Obtains a version-of-record PDF with institutional access (EBSCO, publisher site)."""

    def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
        """Download the publisher PDF.

        Args:
            reference: Reference with a DOI.

        Returns:
            (PDF bytes, source URL), or None on failure.
        """
        ...


class PdfStore(Protocol):
    """Stores PDFs by reference key."""

    def existing(self, key: str) -> Path | None:
        """Find an already saved PDF.

        Args:
            key: Reference key.

        Returns:
            The saved path, or None.
        """
        ...

    def set_aside(self, key: str) -> Path | None:
        """Move an existing PDF out of the way before refreshing it.

        Args:
            key: Reference key.

        Returns:
            Where the old file now is, or None when there was none.
        """
        ...

    def restore(self, key: str, aside: Path) -> Path:
        """Put a set-aside file back.

        Args:
            key: Reference key.
            aside: Path returned by `set_aside`.

        Returns:
            The restored path.
        """
        ...

    def save(self, key: str, data: bytes) -> Path:
        """Save PDF bytes.

        Args:
            key: Reference key.
            data: PDF content.

        Returns:
            The saved path.
        """
        ...


class PdfTextReader(Protocol):
    """Extracts text from the first pages of a PDF."""

    def first_pages_text(self, data: bytes) -> str:
        """Extract text.

        Args:
            data: PDF content.

        Returns:
            Text of the first pages; empty when the PDF has no text layer or cannot be read.
        """
        ...


class BookFinder(Protocol):
    """Looks up books (latest edition and free scans)."""

    def find(self, title: str, author: str) -> BookInfo | None:
        """Look up a book.

        Args:
            title: Book title.
            author: First author's family name.

        Returns:
            Book information, or None when unknown.
        """
        ...


@dataclass(frozen=True)
class Sources:
    """Everything the download flow needs.

    Attributes:
        open_access: OA lookup (e.g. OpenAlex).
        http: Plain HTTP fetcher.
        publishers: Institutional routes tried in order (e.g. EBSCO, then the publisher site); empty = none.
        store: Where PDFs are saved.
        pdf_text: Text reader for the title check; None skips the check.
        site: Browser fetcher for listed URLs that plain HTTP cannot fetch; None skips that step.
        books: Book catalogue (latest edition, public-domain scans); None treats books as manual.
    """

    open_access: OpenAccessFinder
    http: PdfFetcher
    publishers: tuple[PublisherFetcher, ...]
    store: PdfStore
    pdf_text: PdfTextReader | None = None
    site: PdfFetcher | None = None
    books: BookFinder | None = None


def _acceptable(reference: Reference, data: bytes, sources: Sources) -> bool:
    """Check that downloaded bytes are a PDF of this reference.

    Args:
        reference: Reference being processed.
        data: Downloaded content.
        sources: Download sources (provides the text reader).

    Returns:
        True for a PDF whose first pages show the title, or whose text cannot be read.
    """
    if not is_pdf(data):
        return False
    if sources.pdf_text is None or not reference.title:
        return True
    text = sources.pdf_text.first_pages_text(data)
    if not text.strip():
        logger.warning("no text layer, title not checked key=%s", reference.key)
        return True
    if title_matches(reference.title, text):
        return True
    logger.warning("title mismatch, rejected key=%s first_text=%r", reference.key, text[:80])
    return False


def _oa_locations(reference: Reference, finder: OpenAccessFinder) -> list[OaLocation]:
    """Look up open-access copies, tolerating lookup failures.

    Args:
        reference: Reference being processed.
        finder: OA lookup.

    Returns:
        Copies found (empty without a DOI or on error).
    """
    if not reference.doi:
        return []
    try:
        return finder.find_pdf_locations(reference.doi)
    except SourceError as exc:
        logger.warning("open-access lookup failed key=%s: %s", reference.key, exc)
        return []


def _try_urls(
    reference: Reference, urls: list[str], fetcher: PdfFetcher, sources: Sources
) -> tuple[bytes, str] | None:
    """Try URLs in order until one returns a PDF of this reference.

    Args:
        reference: Reference being processed.
        urls: Candidate URLs.
        fetcher: Plain HTTP or browser fetcher.
        sources: Download sources (title check).

    Returns:
        (PDF bytes, URL) or None.
    """
    for url in urls:
        try:
            data = fetcher.fetch(url)
        except SourceError as exc:
            logger.warning("skip url key=%s url=%s: %s", reference.key, url, exc)
            continue
        if data and _acceptable(reference, data, sources):
            return data, url
        logger.info("no usable pdf key=%s url=%s", reference.key, url)
    return None


def _try_institutional(reference: Reference, sources: Sources) -> tuple[bytes, str] | None:
    """Try each institutional route in order; a wrong paper from one route moves on to the next.

    Args:
        reference: Reference being processed.
        sources: Download sources.

    Returns:
        (PDF bytes, URL) or None.
    """
    if not reference.doi:
        return None
    for route in sources.publishers:
        try:
            got = route.fetch_pdf(reference)
        except SourceError as exc:
            logger.warning(
                "institutional route failed key=%s route=%s: %s", reference.key, type(route).__name__, exc
            )
            continue
        if got and _acceptable(reference, got[0], sources):
            return got
    return None


def _obtain(reference: Reference, sources: Sources) -> tuple[bytes, str, bool] | None:
    """Run the download routes in preference order.

    Args:
        reference: Reference being processed.
        sources: Download sources.

    Returns:
        (PDF bytes, URL, is_version_of_record) or None.
    """
    locations = _oa_locations(reference, sources.open_access)
    published = [loc.url for loc in locations if loc.published]
    got = _try_urls(reference, published, sources.http, sources) or _try_institutional(reference, sources)
    if got:
        return got[0], got[1], True
    secondary = list(reference.direct_urls()) + [loc.url for loc in locations if not loc.published]
    secondary = [u for u in dict.fromkeys(secondary) if u not in published]
    got = _try_urls(reference, secondary, sources.http, sources)
    if got is None and sources.site is not None:
        got = _try_urls(reference, list(reference.pdf_urls), sources.site, sources)
    return (got[0], got[1], False) if got else None


def _book_info(reference: Reference, sources: Sources) -> BookInfo | None:
    """Look up a book in the catalogue, tolerating failures.

    Args:
        reference: Book reference.
        sources: Download sources.

    Returns:
        Book information, or None.
    """
    if sources.books is None or not reference.title:
        return None
    try:
        return sources.books.find(reference.title, reference.author)
    except SourceError as exc:
        logger.warning("book lookup failed key=%s: %s", reference.key, exc)
        return None


def _download_book(reference: Reference, sources: Sources) -> DownloadOutcome:
    """Obtain a book: a free scan, else an institutional e-book (when it has a DOI), else borrow.

    Args:
        reference: Book reference.
        sources: Download sources.

    Returns:
        The outcome; its detail names the latest edition when known.
    """
    info = _book_info(reference, sources)
    edition = f"latest edition: {info.latest_edition}" if info and info.latest_edition else ""
    got = _try_urls(reference, list(info.public_pdf_urls), sources.http, sources) if info else None
    if got is None and reference.doi:
        found = _obtain(reference, sources)
        got = (found[0], found[1]) if found else None
    if got is None:
        detail = "; ".join(x for x in ("book: borrow from the library", edition) if x)
        return DownloadOutcome(reference, DownloadStatus.MANUAL, detail=detail)
    path = sources.store.save(reference.key, got[0])
    logger.info("downloaded book key=%s url=%s bytes=%d", reference.key, got[1], len(got[0]))
    return DownloadOutcome(reference, DownloadStatus.DOWNLOADED, source=got[1], path=path, detail=edition)


def download_reference(reference: Reference, sources: Sources, refresh: bool = False) -> DownloadOutcome:
    """Obtain one reference.

    Args:
        reference: Reference to obtain.
        sources: Download sources.
        refresh: Look for a better copy even when a file exists (the old file is kept if none is found).

    Returns:
        The outcome for this reference.
    """
    aside = sources.store.set_aside(reference.key) if refresh else None
    existing = sources.store.existing(reference.key)
    if existing is not None:
        return DownloadOutcome(reference, DownloadStatus.ALREADY_PRESENT, path=existing)
    if reference.kind is ReferenceKind.BOOK:
        return _download_book(reference, sources)
    got = _obtain(reference, sources)
    if got is None and aside is not None:
        path = sources.store.restore(reference.key, aside)
        return DownloadOutcome(
            reference,
            DownloadStatus.ALREADY_PRESENT,
            path=path,
            detail="no better copy found; kept the previous copy",
        )
    if got is None:
        return DownloadOutcome(
            reference, DownloadStatus.FAILED, detail="no PDF from open access, EBSCO or publisher"
        )
    data, url, official = got
    path = sources.store.save(reference.key, data)
    logger.info("downloaded key=%s url=%s bytes=%d official=%s", reference.key, url, len(data), official)
    detail = "" if official else AUTHOR_COPY_NOTE
    return DownloadOutcome(reference, DownloadStatus.DOWNLOADED, source=url, path=path, detail=detail)


def download_all(
    references: list[Reference], sources: Sources, refresh: frozenset[str] = frozenset()
) -> list[DownloadOutcome]:
    """Obtain every reference; one failure never stops the batch.

    Args:
        references: References to obtain.
        sources: Download sources.
        refresh: Keys whose existing files should be replaced by a better copy when one is found.

    Returns:
        One outcome per reference, in input order.
    """
    logger.info("download batch start count=%d refresh=%d", len(references), len(refresh))
    outcomes = [download_reference(ref, sources, ref.key in refresh) for ref in references]
    failed = sum(o.status is DownloadStatus.FAILED for o in outcomes)
    logger.info("download batch done count=%d failed=%d", len(outcomes), failed)
    return outcomes


def render_report(outcomes: list[DownloadOutcome], notes: list[ConversionNote] | None = None) -> str:
    """Build a Markdown report of the batch.

    Args:
        outcomes: Outcomes from `download_all`.
        notes: Conversion notes from the APA step; shown in their own section when present.

    Returns:
        Markdown text with a summary line, one table row per reference and the notes.
    """
    counts = {s: sum(o.status is s for o in outcomes) for s in DownloadStatus}
    summary = ", ".join(f"{s.value}: {n}" for s, n in counts.items())
    rows = [
        f"| {o.reference.citation} | {o.status.value} | {o.path.name if o.path else ''} "
        f"| {'; '.join(x for x in (o.source, o.detail) if x)} |"
        for o in outcomes
    ]
    lines = ["# Literature download report", "", summary, "", "| Reference | Status | File | Source / note |"]
    lines += ["| --- | --- | --- | --- |"] + rows
    if notes:
        lines += ["", "## Check these citations", "", "| Citation | Note |", "| --- | --- |"]
        lines += [f"| {n.citation} | {n.message} |" for n in notes]
    return "\n".join(lines) + "\n"
