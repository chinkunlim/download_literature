"""Literature download flow, version of record first (ADR-003).

Order: books → manual; existing file → skip (unless refreshed); published open-access copies;
institutional routes in order (EBSCO, publisher site); then preprints / accepted manuscripts / listed
URLs (plain HTTP, then the browser). Copies from the last step are flagged in the outcome.
Sources are passed in (dependency injection), so the same flow runs offline in tests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from download_literature.domain.literature import (
    BookInfo,
    DownloadOutcome,
    DownloadStatus,
    NeedsUserError,
    OaLocation,
    Reference,
    ReferenceKind,
    SourceError,
    cjk_bigrams,
    has_cjk,
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
        progress: Called with (key, step) while a reference is processed (e.g. for the web page).
    """

    open_access: OpenAccessFinder
    http: PdfFetcher
    publishers: tuple[PublisherFetcher, ...]
    store: PdfStore
    pdf_text: PdfTextReader | None = None
    site: PdfFetcher | None = None
    books: BookFinder | None = None
    progress: Callable[[str, str], None] | None = None


@dataclass
class _Attempt:
    """State of obtaining one reference.

    Attributes:
        reference: Reference being processed.
        sources: Download sources.
        blocked: Sites that needed a person (bot check, sign-in) and were skipped.
    """

    reference: Reference
    sources: Sources
    blocked: list[str] = field(default_factory=list)

    def note_error(self, where: str, exc: SourceError) -> None:
        """Log a failed source and remember sites that need a person.

        Args:
            where: Route or URL that failed.
            exc: The error.
        """
        if isinstance(exc, NeedsUserError):
            self.blocked.append(exc.site)
            logger.warning("needs a person key=%s site=%s (skipped)", self.reference.key, exc.site)
        else:
            logger.warning("source failed key=%s at=%s: %s", self.reference.key, where, exc)

    def step(self, name: str) -> None:
        """Report the step being tried.

        Args:
            name: Step name shown to the user (e.g. EBSCO).
        """
        if self.sources.progress is not None:
            self.sources.progress(self.reference.key, name)

    def blocked_note(self) -> str:
        """Describe the skipped sites.

        Returns:
            Note text, or empty when nothing was skipped.
        """
        if not self.blocked:
            return ""
        sites = ", ".join(dict.fromkeys(self.blocked))
        return f"needs you at {sites}: run with --interactive"


def _acceptable(attempt: _Attempt, data: bytes) -> bool:
    """Check that downloaded bytes are a PDF of this reference.

    Args:
        attempt: Current attempt (reference and text reader).
        data: Downloaded content.

    Returns:
        True for a PDF whose first pages show the title, or whose text cannot be read.
    """
    reference, reader = attempt.reference, attempt.sources.pdf_text
    if not is_pdf(data):
        return False
    if reader is None or not reference.title:
        return True
    text = reader.first_pages_text(data)
    unreadable = not text.strip() or (has_cjk(reference.title) and len(cjk_bigrams(text)) < 10)
    if unreadable:  # no text layer, or Chinese fonts pypdf cannot decode (garbled characters)
        logger.warning("text layer unreadable, title not checked key=%s", reference.key)
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


def _try_urls(attempt: _Attempt, urls: list[str], fetcher: PdfFetcher) -> tuple[bytes, str] | None:
    """Try URLs in order until one returns a PDF of this reference.

    Args:
        attempt: Current attempt.
        urls: Candidate URLs.
        fetcher: Plain HTTP or browser fetcher.

    Returns:
        (PDF bytes, URL) or None.
    """
    for url in urls:
        try:
            data = fetcher.fetch(url)
        except SourceError as exc:
            attempt.note_error(url, exc)
            continue
        if data and _acceptable(attempt, data):
            return data, url
        logger.info("no usable pdf key=%s url=%s", attempt.reference.key, url)
    return None


def _try_institutional(attempt: _Attempt) -> tuple[bytes, str] | None:
    """Try each institutional route in order; a wrong paper from one route moves on to the next.

    Args:
        attempt: Current attempt.

    Returns:
        (PDF bytes, URL) or None.
    """
    for route in attempt.sources.publishers:  # each route decides what it needs (DOI, title, landing page)
        attempt.step(getattr(route, "label", type(route).__name__))
        try:
            got = route.fetch_pdf(attempt.reference)
        except SourceError as exc:
            attempt.note_error(type(route).__name__, exc)
            continue
        if got and _acceptable(attempt, got[0]):
            return got
    return None


def _obtain(attempt: _Attempt) -> tuple[bytes, str, bool] | None:
    """Run the download routes in preference order.

    Args:
        attempt: Current attempt.

    Returns:
        (PDF bytes, URL, is_version_of_record) or None.
    """
    reference, sources = attempt.reference, attempt.sources
    attempt.step("開放取用")
    locations = _oa_locations(reference, sources.open_access)
    published = [loc.url for loc in locations if loc.published]
    got = _try_urls(attempt, published, sources.http) or _try_institutional(attempt)
    if got:
        return got[0], got[1], True
    secondary = list(reference.direct_urls()) + [loc.url for loc in locations if not loc.published]
    secondary = [u for u in dict.fromkeys(secondary) if u not in published]
    attempt.step("作者稿／預印本")
    got = _try_urls(attempt, secondary, sources.http)
    if got is None and sources.site is not None:
        got = _try_urls(attempt, list(reference.pdf_urls), sources.site)
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


def _join(*parts: str) -> str:
    """Join non-empty notes.

    Args:
        parts: Note texts.

    Returns:
        Notes separated by "; ".
    """
    return "; ".join(p for p in parts if p)


def _download_book(attempt: _Attempt, aside: Path | None) -> DownloadOutcome:
    """Obtain a book: a free scan, else an institutional e-book (when it has a DOI), else borrow.

    Args:
        attempt: Current attempt for a book reference.
        aside: Previous file set aside by a refresh (restored when nothing is found), or None.

    Returns:
        The outcome; its detail names the latest edition when known.
    """
    reference, sources = attempt.reference, attempt.sources
    attempt.step("書籍目錄")
    info = _book_info(reference, sources)
    edition = f"latest edition: {info.latest_edition}" if info and info.latest_edition else ""
    got = _try_urls(attempt, list(info.public_pdf_urls), sources.http) if info else None
    if got is None and reference.doi:
        found = _obtain(attempt)
        got = (found[0], found[1]) if found else None
    if got is None and aside is not None:
        return _no_pdf(attempt, aside)
    if got is None:
        status = DownloadStatus.NEEDS_REVIEW if attempt.blocked else DownloadStatus.MANUAL
        detail = _join(attempt.blocked_note(), "book: borrow from the library", edition)
        return DownloadOutcome(reference, status, detail=detail)
    path = sources.store.save(reference.key, got[0])
    logger.info("downloaded book key=%s url=%s bytes=%d", reference.key, got[1], len(got[0]))
    return DownloadOutcome(reference, DownloadStatus.DOWNLOADED, source=got[1], path=path, detail=edition)


def _no_pdf(attempt: _Attempt, aside: Path | None) -> DownloadOutcome:
    """Build the outcome when no PDF was obtained.

    Args:
        attempt: Current attempt.
        aside: Previous file set aside by a refresh, or None.

    Returns:
        Previous copy restored, needs_review (a site needed a person) or failed.
    """
    reference, store = attempt.reference, attempt.sources.store
    if aside is not None:
        path = store.restore(reference.key, aside)
        detail = _join("no better copy found; kept the previous copy", attempt.blocked_note())
        return DownloadOutcome(reference, DownloadStatus.ALREADY_PRESENT, path=path, detail=detail)
    if attempt.blocked:
        return DownloadOutcome(reference, DownloadStatus.NEEDS_REVIEW, detail=attempt.blocked_note())
    return DownloadOutcome(
        reference, DownloadStatus.FAILED, detail="no PDF from open access, EBSCO or publisher"
    )


def download_reference(reference: Reference, sources: Sources, refresh: bool = False) -> DownloadOutcome:
    """Obtain one reference.

    Args:
        reference: Reference to obtain.
        sources: Download sources.
        refresh: Look for the version of record even when a file exists; the old file is kept when only
            an author copy (or nothing) is found.

    Returns:
        The outcome for this reference.
    """
    aside = sources.store.set_aside(reference.key) if refresh else None
    existing = sources.store.existing(reference.key)
    if existing is not None:
        return DownloadOutcome(reference, DownloadStatus.ALREADY_PRESENT, path=existing)
    attempt = _Attempt(reference, sources)
    if reference.kind is ReferenceKind.BOOK:
        return _download_book(attempt, aside)
    got = _obtain(attempt)
    if got is None or (aside is not None and not got[2]):  # refresh never swaps for a copy (ISSUE-004)
        return _no_pdf(attempt, aside)
    data, url, official = got
    path = sources.store.save(reference.key, data)
    logger.info("downloaded key=%s url=%s bytes=%d official=%s", reference.key, url, len(data), official)
    detail = "" if official else _join(AUTHOR_COPY_NOTE, attempt.blocked_note())
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
