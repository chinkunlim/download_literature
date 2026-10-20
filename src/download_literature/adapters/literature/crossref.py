"""Crossref adapter: confirms DOIs and finds DOIs for citations (free API, no key or e-mail needed)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from download_literature.domain.literature import ReferenceKind, SourceError, WorkMeta

logger = logging.getLogger(__name__)

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
_BOOK_TYPES = {"book", "monograph", "edited-book", "reference-book", "book-set"}
_CHAPTER_TYPES = {"book-chapter", "book-section", "book-part", "reference-entry"}
# Records that describe something other than the cited work itself (e.g. Faculty Opinions recommendations)
_SKIPPED_TYPES = {"dataset", "peer-review", "component", "grant", "standard", "database", "other"}


def _year(item: dict[str, Any]) -> int | None:
    """Read the publication year from a Crossref record.

    Args:
        item: Crossref work record.

    Returns:
        First year found in issued / published-print / published-online, or None.
    """
    for field in ("issued", "published-print", "published-online"):
        parts = (item.get(field) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def parse_crossref_work(item: dict[str, Any]) -> WorkMeta | None:
    """Convert a Crossref work record into a WorkMeta.

    Args:
        item: One record from `/works/<doi>` (`message`) or `/works?query...` (`message.items[]`).

    Returns:
        The work, or None when the record has no title or is not a publication (dataset, review report, ...).
    """
    titles = item.get("title") or []
    if not titles or item.get("type", "") in _SKIPPED_TYPES:
        return None
    title = titles[0]
    subtitles = item.get("subtitle") or []
    if subtitles and subtitles[0].lower() not in title.lower():
        title = f"{title}: {subtitles[0]}"
    title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
    kind_name = item.get("type", "")
    kind = (
        ReferenceKind.BOOK
        if kind_name in _BOOK_TYPES
        else ReferenceKind.CHAPTER
        if kind_name in _CHAPTER_TYPES
        else ReferenceKind.ARTICLE
    )
    authors = item.get("author") or [{}]
    return WorkMeta(str(item["DOI"]), title, _year(item), kind, str(authors[0].get("family", "")))


class CrossrefResolver:
    """Looks up works on Crossref."""

    def __init__(self, client: httpx.Client) -> None:
        """Create the resolver.

        Args:
            client: Shared HTTP client (timeouts and headers already set).
        """
        self._client = client

    def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET a Crossref URL.

        Args:
            url: Request URL.
            params: Query parameters.

        Returns:
            The response (any status).

        Raises:
            SourceError: On network errors, rate limiting or server errors.
        """
        start = time.monotonic()
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"crossref request failed: {exc}") from exc
        logger.info(
            "crossref url=%s status=%s (%.0f ms)", url, resp.status_code, (time.monotonic() - start) * 1000
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise SourceError(f"crossref status {resp.status_code}")
        return resp

    def by_doi(self, doi: str) -> WorkMeta | None:
        """Look up a DOI.

        Args:
            doi: DOI without prefix.

        Returns:
            The work, or None when Crossref does not know the DOI.

        Raises:
            SourceError: On network or server errors.
        """
        resp = self._get(f"{CROSSREF_WORKS_URL}/{quote(doi, safe='/')}")
        if resp.status_code != 200:
            return None
        return parse_crossref_work(resp.json()["message"])

    def search(self, citation: str) -> list[WorkMeta]:
        """Search Crossref with a whole citation.

        Args:
            citation: Reference text.

        Returns:
            Up to three best matches (unverified; the caller checks title and year).

        Raises:
            SourceError: On network or server errors.
        """
        resp = self._get(CROSSREF_WORKS_URL, {"query.bibliographic": citation[:500], "rows": "3"})
        if resp.status_code != 200:
            return []
        items = resp.json()["message"].get("items", [])
        return [w for w in (parse_crossref_work(i) for i in items) if w is not None]
