"""Literature download flow: books → manual, existing → skip, open access first, publisher last.

Sources are passed in (dependency injection), so the same flow runs offline in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from download_literature.domain.literature import (
    DownloadOutcome,
    DownloadStatus,
    Reference,
    ReferenceKind,
    SourceError,
    is_pdf,
    title_matches,
)

logger = logging.getLogger(__name__)


class OpenAccessFinder(Protocol):
    """Finds open-access PDF URLs for a DOI."""

    def find_pdf_urls(self, doi: str) -> list[str]:
        """Look up OA PDF URLs.

        Args:
            doi: DOI without prefix.

        Returns:
            Candidate PDF URLs, best first.
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
    """Obtains a PDF through the publisher site with institutional access."""

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


@dataclass(frozen=True)
class Sources:
    """Everything the download flow needs.

    Attributes:
        open_access: OA lookup (e.g. OpenAlex).
        http: Plain HTTP fetcher.
        publisher: Browser-based publisher fetcher; None disables the institutional route.
        store: Where PDFs are saved.
        pdf_text: Text reader for the title check; None skips the check.
    """

    open_access: OpenAccessFinder
    http: PdfFetcher
    publisher: PublisherFetcher | None
    store: PdfStore
    pdf_text: PdfTextReader | None = None


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


def _candidate_urls(reference: Reference, finder: OpenAccessFinder) -> list[str]:
    """Collect direct and open-access URLs without duplicates.

    Args:
        reference: Reference being processed.
        finder: OA lookup.

    Returns:
        Unique URLs in try order.
    """
    urls = list(reference.direct_urls())
    if reference.doi:
        try:
            urls += finder.find_pdf_urls(reference.doi)
        except SourceError as exc:
            logger.warning("open-access lookup failed key=%s: %s", reference.key, exc)
    return list(dict.fromkeys(urls))


def _try_open_access(reference: Reference, sources: Sources) -> tuple[bytes, str] | None:
    """Try each open-access URL until one returns a PDF.

    Args:
        reference: Reference being processed.
        sources: Download sources.

    Returns:
        (PDF bytes, URL) or None.
    """
    for url in _candidate_urls(reference, sources.open_access):
        try:
            data = sources.http.fetch(url)
        except SourceError as exc:
            logger.warning("skip url key=%s url=%s: %s", reference.key, url, exc)
            continue
        if data and _acceptable(reference, data, sources):
            return data, url
        logger.info("not a pdf key=%s url=%s", reference.key, url)
    return None


def _try_publisher(reference: Reference, sources: Sources) -> tuple[bytes, str] | None:
    """Try the institutional publisher route.

    Args:
        reference: Reference being processed.
        sources: Download sources.

    Returns:
        (PDF bytes, URL) or None.
    """
    if sources.publisher is None or not reference.doi:
        return None
    try:
        got = sources.publisher.fetch_pdf(reference)
    except SourceError as exc:
        logger.warning("publisher failed key=%s: %s", reference.key, exc)
        return None
    return got if got and _acceptable(reference, got[0], sources) else None


def download_reference(reference: Reference, sources: Sources) -> DownloadOutcome:
    """Obtain one reference.

    Args:
        reference: Reference to obtain.
        sources: Download sources.

    Returns:
        The outcome for this reference.
    """
    if reference.kind is ReferenceKind.BOOK:
        return DownloadOutcome(reference, DownloadStatus.MANUAL, detail="book: obtain from the library")
    existing = sources.store.existing(reference.key)
    if existing is not None:
        return DownloadOutcome(reference, DownloadStatus.ALREADY_PRESENT, path=existing)
    got = _try_open_access(reference, sources) or _try_publisher(reference, sources)
    if got is None:
        return DownloadOutcome(
            reference, DownloadStatus.FAILED, detail="no PDF from open access or publisher"
        )
    path = sources.store.save(reference.key, got[0])
    logger.info("downloaded key=%s url=%s bytes=%d", reference.key, got[1], len(got[0]))
    return DownloadOutcome(reference, DownloadStatus.DOWNLOADED, source=got[1], path=path)


def download_all(references: list[Reference], sources: Sources) -> list[DownloadOutcome]:
    """Obtain every reference; one failure never stops the batch.

    Args:
        references: References to obtain.
        sources: Download sources.

    Returns:
        One outcome per reference, in input order.
    """
    logger.info("download batch start count=%d", len(references))
    outcomes = [download_reference(ref, sources) for ref in references]
    failed = sum(o.status is DownloadStatus.FAILED for o in outcomes)
    logger.info("download batch done count=%d failed=%d", len(outcomes), failed)
    return outcomes


def render_report(outcomes: list[DownloadOutcome]) -> str:
    """Build a Markdown report of the batch.

    Args:
        outcomes: Outcomes from `download_all`.

    Returns:
        Markdown text with a summary line and one table row per reference.
    """
    counts = {s: sum(o.status is s for o in outcomes) for s in DownloadStatus}
    summary = ", ".join(f"{s.value}: {n}" for s, n in counts.items())
    rows = [
        f"| {o.reference.citation} | {o.status.value} | {o.path.name if o.path else ''} "
        f"| {o.source or o.detail} |"
        for o in outcomes
    ]
    header = [
        "# Literature download report",
        "",
        summary,
        "",
        "| Reference | Status | File | Source / note |",
    ]
    return "\n".join(header + ["| --- | --- | --- | --- |"] + rows) + "\n"
