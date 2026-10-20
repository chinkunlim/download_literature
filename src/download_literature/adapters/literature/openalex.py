"""OpenAlex adapter: finds open-access PDF URLs for a DOI (free API, no key or e-mail needed)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from download_literature.domain.literature import OaLocation, SourceError

logger = logging.getLogger(__name__)

OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:{doi}"


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
