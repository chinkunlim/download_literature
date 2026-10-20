"""OpenAlex adapter: finds open-access PDF URLs for a DOI (free API, no key or e-mail needed)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from download_literature.domain.literature import SourceError

logger = logging.getLogger(__name__)

OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:{doi}"


def parse_openalex_pdf_urls(work: dict[str, Any]) -> list[str]:
    """Extract open-access PDF URLs from an OpenAlex work record.

    Args:
        work: Decoded JSON of `GET /works/doi:<doi>`.

    Returns:
        Unique PDF URLs, best OA location first; closed locations and missing PDFs are dropped.
    """
    locations = [work.get("best_oa_location") or {}] + list(work.get("locations") or [])
    urls = [loc.get("pdf_url") for loc in locations if loc.get("is_oa") and loc.get("pdf_url")]
    return list(dict.fromkeys(str(url) for url in urls))


class OpenAlexFinder:
    """Looks up open-access PDF locations on OpenAlex."""

    def __init__(self, client: httpx.Client) -> None:
        """Create the finder.

        Args:
            client: Shared HTTP client (timeouts and headers already set).
        """
        self._client = client

    def find_pdf_urls(self, doi: str) -> list[str]:
        """Look up OA PDF URLs for a DOI.

        Args:
            doi: DOI without the `https://doi.org/` prefix.

        Returns:
            Candidate PDF URLs, best first; empty when OpenAlex does not know the DOI.

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
        return parse_openalex_pdf_urls(resp.json())
