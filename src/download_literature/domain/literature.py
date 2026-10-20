"""Domain models for literature downloading: references, outcomes and pure helpers (no I/O)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ReferenceKind(str, Enum):
    """What kind of work a reference is; books are never downloaded automatically."""

    ARTICLE = "article"
    CHAPTER = "chapter"
    BOOK = "book"


class DownloadStatus(str, Enum):
    """Result of trying to obtain one reference."""

    DOWNLOADED = "downloaded"
    ALREADY_PRESENT = "already_present"
    MANUAL = "manual"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class SourceError(Exception):
    """A download source failed (network error, HTTP error, blocked page)."""


class NeedsUserError(SourceError):
    """A site needs a person (bot check, CAPTCHA, unfilled sign-in) and was skipped in unattended mode."""

    def __init__(self, site: str) -> None:
        """Create the error.

        Args:
            site: Host name of the site that needs a person.
        """
        super().__init__(f"needs a person at {site}")
        self.site = site


@dataclass(frozen=True)
class Reference:
    """One cited work to obtain.

    Attributes:
        key: Unique id, also used as the PDF file name stem.
        citation: Human-readable citation shown in the report.
        doi: DOI without the `https://doi.org/` prefix; empty when unknown.
        kind: Article, chapter or book.
        arxiv_id: arXiv identifier such as `2310.15461`; empty when none.
        pdf_urls: Extra known PDF or landing-page URLs, tried before open-access lookup.
        title: Work title, used to check that a downloaded PDF is the right paper; empty = no check.
        author: First author's family name (used to look up books); empty when unknown.
    """

    key: str
    citation: str
    doi: str = ""
    kind: ReferenceKind = ReferenceKind.ARTICLE
    arxiv_id: str = ""
    pdf_urls: tuple[str, ...] = ()
    title: str = ""
    author: str = ""

    def direct_urls(self) -> tuple[str, ...]:
        """List URLs that can be tried without any lookup.

        Returns:
            The arXiv PDF URL (if any) followed by `pdf_urls`.
        """
        arxiv = (f"https://arxiv.org/pdf/{self.arxiv_id}",) if self.arxiv_id else ()
        return arxiv + self.pdf_urls


@dataclass(frozen=True)
class BookInfo:
    """What a library catalogue (Open Library) knows about a book.

    Attributes:
        latest_year: Year of the newest edition; None when unknown.
        latest_edition: Newest edition described for people (year, publisher, edition, ISBN, pages).
        public_pdf_urls: Freely downloadable scans (public domain / open access only).
        catalog_url: Catalogue page of the book.
    """

    latest_year: int | None
    latest_edition: str
    public_pdf_urls: tuple[str, ...]
    catalog_url: str


@dataclass(frozen=True)
class OaLocation:
    """One open-access copy of a work.

    Attributes:
        url: PDF URL.
        published: True for the publisher's version of record; False for preprints and accepted manuscripts.
    """

    url: str
    published: bool


@dataclass(frozen=True)
class DownloadOutcome:
    """What happened to one reference.

    Attributes:
        reference: The reference that was processed.
        status: Final status.
        source: URL the PDF came from; empty when nothing was downloaded.
        path: Saved PDF path; None when nothing is on disk.
        detail: Short explanation for manual / failed items.
    """

    reference: Reference
    status: DownloadStatus
    source: str = ""
    path: Path | None = None
    detail: str = ""


def is_pdf(data: bytes) -> bool:
    """Check whether downloaded bytes are a PDF (not an HTML login or challenge page).

    Args:
        data: Response body.

    Returns:
        True when the PDF signature appears at the start of the content.
    """
    return data.lstrip()[:5] == b"%PDF-"


def safe_filename(name: str) -> str:
    """Turn a reference key into a portable file name stem.

    Args:
        name: Raw key or title.

    Returns:
        Letters, digits, `-` and `.` kept; every other run of characters becomes one `_`.
    """
    return re.sub(r"[^A-Za-z0-9.-]+", "_", name).strip("_")


def _words(text: str) -> list[str]:
    """Split text into lower-case words of letters and digits.

    Args:
        text: Any text.

    Returns:
        The words in order.
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def title_matches(title: str, text: str, min_share: float = 0.7) -> bool:
    """Check that a PDF's first-page text shows the expected title.

    Open-access indexes sometimes point at the wrong paper (ISSUE-002); this keeps such PDFs out.
    Hyphenation and line breaks are ignored by also comparing the text with all spaces removed.

    Args:
        title: Expected title; empty means no check.
        text: Text extracted from the first pages of the PDF.
        min_share: Share of title words (4+ letters) that must appear, 0-1.

    Returns:
        True when enough title words appear (or there is no title to check).
    """
    keywords = [w for w in _words(title) if len(w) >= 4]
    if not keywords:
        return True
    present = set(_words(text))
    joined = "".join(_words(text))
    found = sum(1 for w in keywords if w in present or w in joined)
    return found / len(keywords) >= min_share


@dataclass(frozen=True)
class WorkMeta:
    """Bibliographic facts about a work from a metadata service such as Crossref.

    Attributes:
        doi: DOI without prefix.
        title: Full title (subtitle included).
        year: Publication year; None when unknown.
        kind: Article, chapter or book.
        first_author: Family name of the first author; empty when unknown.
        authors: (family, given) pairs in order; a group author has an empty given name.
        container: Journal, proceedings, book (for a chapter) or repository (for a preprint) name.
        volume: Volume number.
        issue: Issue number.
        pages: Page range such as `775-808`.
        article_number: Article number for journals without pages.
        publisher: Publisher name (books, chapters, proceedings).
        edition: Edition statement such as `2nd ed.`.
        genre: Detailed type: journal-article, proceedings-article, book, book-chapter, preprint, ...
    """

    doi: str
    title: str
    year: int | None
    kind: ReferenceKind
    first_author: str
    authors: tuple[tuple[str, str], ...] = ()
    container: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    article_number: str = ""
    publisher: str = ""
    edition: str = ""
    genre: str = ""
