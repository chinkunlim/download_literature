"""Open Library / Internet Archive adapter for books (ADR-004).

Finds a book's latest edition (year, publisher, edition, ISBN, pages) and, only for books that are
public domain or openly licensed (`ebook_access == "public"` and not access-restricted on the Internet
Archive), the URL of a downloadable PDF scan. Lending-only (in-copyright) scans are never downloaded.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from download_literature.domain.literature import BookInfo, SourceError, title_matches

logger = logging.getLogger(__name__)

OPENLIBRARY = "https://openlibrary.org"
SEARCH_FIELDS = "key,title,author_name,first_publish_year,ebook_access,ia"
_PDF_FORMATS = ("Text PDF", "Additional Text PDF")
_AUDIO = re.compile(r"audio|\bcd\b|mp3|cassette", re.IGNORECASE)


def matching_works(docs: list[dict[str, Any]], title: str, author: str) -> list[dict[str, Any]]:
    """Keep the search results that are the cited book (full title, or main title when a subtitle is missing).

    Args:
        docs: Open Library search `docs`.
        title: Cited title.
        author: First author's family name; empty skips the author check.

    Returns:
        Matching docs in ranking order.
    """
    found = []
    for doc in docs:
        doc_title = str(doc.get("title") or "").split(" / ")[0]  # drop "/ statement of responsibility"
        authors = " ".join(doc.get("author_name") or []).lower()
        main, doc_main = title.split(":")[0], doc_title.split(":")[0]
        same_title = (title_matches(title, doc_title, 0.8) and title_matches(doc_title, title, 0.8)) or (
            title_matches(main, doc_main, 1.0) and title_matches(doc_main, main, 1.0)
        )
        if same_title and (not author or author.lower() in authors):
            found.append(doc)
    return found


def _edition_year(entry: dict[str, Any]) -> int | None:
    """Read the publication year of an edition.

    Args:
        entry: Open Library edition record.

    Returns:
        Four-digit year, or None.
    """
    match = re.search(r"\b(1[5-9]|20)\d{2}\b", str(entry.get("publish_date") or ""))
    return int(match.group(0)) if match else None


def latest_edition(entries: list[dict[str, Any]]) -> tuple[int, str] | None:
    """Pick the newest printed edition (audiobooks are skipped) and describe it.

    Args:
        entries: Open Library edition records (from one or more works).

    Returns:
        (year, "year, publisher, edition, ISBN …, N pages"), or None when no edition has a year.
    """
    printed = [e for e in entries if not _AUDIO.search(str(e.get("physical_format") or ""))]
    dated = [(year, e) for e in printed if (year := _edition_year(e)) is not None]
    if not dated:
        return None
    year, entry = max(dated, key=lambda pair: pair[0])
    isbn = (entry.get("isbn_13") or entry.get("isbn_10") or [""])[0]
    parts = [
        str(year),
        ", ".join(entry.get("publishers") or []),
        str(entry.get("edition_name") or ""),
        f"ISBN {isbn}" if isbn else "",
        f"{entry['number_of_pages']} pages" if entry.get("number_of_pages") else "",
    ]
    return year, ", ".join(p for p in parts if p)


def ia_public_pdf(metadata: dict[str, Any]) -> str | None:
    """Find the downloadable PDF of an unrestricted Internet Archive item.

    Args:
        metadata: Response of `https://archive.org/metadata/<identifier>`.

    Returns:
        PDF URL, or None for lending-only (access-restricted) items or items without a text PDF.
    """
    meta = metadata.get("metadata") or {}
    if str(meta.get("access-restricted-item", "")).lower() == "true":
        return None
    identifier = meta.get("identifier")
    for fmt in _PDF_FORMATS:
        for file in metadata.get("files") or []:
            if file.get("format") == fmt and "_encrypted" not in file.get("name", ""):
                return f"https://archive.org/download/{identifier}/{file['name']}"
    return None


class OpenLibraryBooks:
    """Looks up books on Open Library and the Internet Archive."""

    def __init__(self, client: httpx.Client, max_works: int = 3) -> None:
        """Create the finder.

        Args:
            client: Shared HTTP client.
            max_works: How many matching works to merge (Open Library often splits one book).
        """
        self._client = client
        self._max = max_works

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """GET a JSON document.

        Args:
            url: Request URL.
            params: Query parameters.

        Returns:
            Decoded JSON (empty dict on 404).

        Raises:
            SourceError: On network errors or other non-200 status.
        """
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"open library request failed: {exc}") from exc
        logger.info("open library url=%s status=%s", url, resp.status_code)
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise SourceError(f"open library status {resp.status_code}")
        data: dict[str, Any] = resp.json()
        return data

    def _public_pdfs(self, docs: list[dict[str, Any]]) -> tuple[str, ...]:
        """Collect PDF URLs of public scans.

        Args:
            docs: Matching works.

        Returns:
            Downloadable PDF URLs (at most three scans are checked).
        """
        urls = []
        ids = [ia for d in docs if d.get("ebook_access") == "public" for ia in (d.get("ia") or [])]
        for identifier in ids[:3]:
            url = ia_public_pdf(self._get_json(f"https://archive.org/metadata/{identifier}"))
            if url:
                urls.append(url)
        return tuple(urls)

    def find(self, title: str, author: str) -> BookInfo | None:
        """Look up a book's latest edition and any free scan.

        Args:
            title: Book title.
            author: First author's family name.

        Returns:
            Book information, or None when Open Library has no matching work.

        Raises:
            SourceError: On network or server errors.
        """
        # search on the main title (catalogue records often lack the subtitle); matching_works filters
        params = {"title": title.split(":")[0], "author": author, "limit": "20", "fields": SEARCH_FIELDS}
        docs = matching_works(
            self._get_json(f"{OPENLIBRARY}/search.json", params).get("docs", []), title, author
        )
        if not docs:
            return None
        entries: list[dict[str, Any]] = []
        for doc in docs[: self._max]:
            entries += self._get_json(f"{OPENLIBRARY}{doc['key']}/editions.json", {"limit": "200"}).get(
                "entries", []
            )
        latest = latest_edition(entries)
        return BookInfo(
            latest[0] if latest else None,
            latest[1] if latest else "",
            self._public_pdfs(docs),
            f"{OPENLIBRARY}{docs[0]['key']}",
        )
