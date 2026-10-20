"""OpenAlex adapter: finds open-access PDF URLs for a DOI (free API, no key or e-mail needed)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from download_literature.domain.literature import OaLocation, ReferenceKind, SourceError, WorkMeta

logger = logging.getLogger(__name__)

OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:{doi}"
OPENALEX_SEARCH_URL = "https://api.openalex.org/works"
_GENRES = {
    "article": "journal-article",
    "book": "book",
    "book-chapter": "book-chapter",
    "preprint": "preprint",
}


def _is_published(location: dict[str, Any]) -> bool:
    """Tell whether an OpenAlex location holds the version of record.

    Args:
        location: One entry of `locations` / `best_oa_location`.

    Returns:
        True for `publishedVersion`, or for an unversioned copy hosted by a journal.
    """
    version = location.get("version")
    source_type = (location.get("source") or {}).get("type")
    return version == "publishedVersion" or (version is None and source_type == "journal")


def parse_openalex_locations(work: dict[str, Any]) -> list[OaLocation]:
    """Extract open-access PDF copies from an OpenAlex work record.

    Args:
        work: Decoded JSON of `GET /works/doi:<doi>`.

    Returns:
        Unique PDF copies, best OA location first; closed locations and missing PDFs are dropped.
    """
    locations = [work.get("best_oa_location") or {}] + list(work.get("locations") or [])
    found: dict[str, OaLocation] = {}
    for loc in locations:
        url = loc.get("pdf_url")
        if loc.get("is_oa") and url and url not in found:
            found[url] = OaLocation(str(url), _is_published(loc))
    return list(found.values())


def _split_name(display_name: str) -> tuple[str, str]:
    """Split "Given Family" into (family, given).

    Args:
        display_name: OpenAlex author display name.

    Returns:
        (family, given); single-word names are family names.
    """
    parts = display_name.split()
    return (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (display_name, "")


def _repository(source_name: str, doi: str) -> str:
    """Shorten preprint server names for APA (e.g. "arXiv (Cornell University)" → "arXiv").

    Args:
        source_name: OpenAlex source display name.
        doi: DOI of the work.

    Returns:
        Repository name.
    """
    if doi.lower().startswith("10.48550/") or "arxiv" in source_name.lower():
        return "arXiv"
    return re.sub(r"\s*\(.*\)$", "", source_name)


def parse_openalex_work(work: dict[str, Any]) -> WorkMeta | None:
    """Convert an OpenAlex work record into a WorkMeta (used for preprints and title searches).

    Args:
        work: One OpenAlex work record.

    Returns:
        The work, or None without a title.
    """
    title = work.get("display_name") or work.get("title")
    if not title:
        return None
    doi = str(work.get("doi") or "").replace("https://doi.org/", "")
    genre = _GENRES.get(str(work.get("type")), "journal-article")
    kind = {"book": ReferenceKind.BOOK, "book-chapter": ReferenceKind.CHAPTER}.get(
        genre, ReferenceKind.ARTICLE
    )
    authors = tuple(
        _split_name(a["author"]["display_name"]) for a in work.get("authorships") or [] if a.get("author")
    )
    source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    biblio = work.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    pages = f"{first}-{last}" if first and last and first != last else str(first or "")
    return WorkMeta(
        doi,
        str(title),
        work.get("publication_year"),
        kind,
        authors[0][0] if authors else "",
        authors=authors,
        container=_repository(source, doi) if genre == "preprint" else source,
        volume=str(biblio.get("volume") or ""),
        issue=str(biblio.get("issue") or ""),
        pages=pages,
        genre=genre,
    )


class OpenAlexResolver:
    """Metadata lookups on OpenAlex: covers DataCite DOIs (arXiv) and title-only searches."""

    def __init__(self, client: httpx.Client) -> None:
        """Create the resolver.

        Args:
            client: Shared HTTP client.
        """
        self._client = client

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        """GET an OpenAlex URL.

        Args:
            url: Request URL.
            params: Query parameters.

        Returns:
            Decoded JSON, or None on 404.

        Raises:
            SourceError: On network errors or other non-200 status.
        """
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex request failed: {exc}") from exc
        logger.info("openalex url=%s status=%s", url, resp.status_code)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SourceError(f"openalex status {resp.status_code}")
        data: dict[str, Any] = resp.json()
        return data

    def by_doi(self, doi: str) -> WorkMeta | None:
        """Look up a DOI.

        Args:
            doi: DOI without prefix.

        Returns:
            The work, or None when unknown.

        Raises:
            SourceError: On network or server errors.
        """
        data = self._get_json(OPENALEX_WORK_URL.format(doi=doi))
        return parse_openalex_work(data) if data else None

    def search(self, citation: str) -> list[WorkMeta]:
        """Search works by free text (title, authors, year).

        Args:
            citation: Text to search.

        Returns:
            Up to five matches (unverified).

        Raises:
            SourceError: On network or server errors.
        """
        data = self._get_json(OPENALEX_SEARCH_URL, {"search": citation[:300], "per-page": "5"})
        works = [parse_openalex_work(w) for w in (data or {}).get("results", [])]
        return [w for w in works if w is not None]


class OpenAlexFinder:
    """Looks up open-access PDF locations on OpenAlex."""

    def __init__(self, client: httpx.Client) -> None:
        """Create the finder.

        Args:
            client: Shared HTTP client (timeouts and headers already set).
        """
        self._client = client

    def find_pdf_locations(self, doi: str) -> list[OaLocation]:
        """Look up open-access PDF copies for a DOI.

        Args:
            doi: DOI without the `https://doi.org/` prefix.

        Returns:
            Copies with their version, best first; empty when OpenAlex does not know the DOI.

        Raises:
            SourceError: On network errors or unexpected HTTP status.
        """
        start = time.monotonic()
        try:
            resp = self._client.get(OPENALEX_WORK_URL.format(doi=doi))
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex request failed: {exc}") from exc
        logger.info(
            "openalex doi=%s status=%s (%.0f ms)", doi, resp.status_code, (time.monotonic() - start) * 1000
        )
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise SourceError(f"openalex status {resp.status_code}")
        return parse_openalex_locations(resp.json())
