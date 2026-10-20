"""Plain HTTP PDF fetcher for open-access sources (arXiv, ACL Anthology, Frontiers, repositories).

Follows one `citation_pdf_url` hop when a URL returns an HTML landing page. Never handles logins.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

import httpx

from download_literature.domain.literature import SourceError, is_pdf

logger = logging.getLogger(__name__)

_META_PDF = re.compile(r"<meta\b[^>]*\bname=[\"']citation_pdf_url[\"'][^>]*>", re.IGNORECASE)
_CONTENT = re.compile(r"\bcontent=[\"']([^\"']+)[\"']", re.IGNORECASE)


def parse_citation_pdf_url(html: str, page_url: str) -> str | None:
    """Find the `citation_pdf_url` meta tag that most scholarly landing pages provide.

    Args:
        html: Landing-page HTML.
        page_url: URL of that page, used to resolve relative links.

    Returns:
        Absolute PDF URL, or None when the tag is missing.
    """
    tag = _META_PDF.search(html)
    content = _CONTENT.search(tag.group(0)) if tag else None
    return urljoin(page_url, content.group(1)) if content else None


class HttpPdfFetcher:
    """Downloads PDFs over plain HTTP with a polite delay between requests."""

    def __init__(self, client: httpx.Client, min_interval_seconds: float = 1.0) -> None:
        """Create the fetcher.

        Args:
            client: Shared HTTP client (redirects followed, timeouts set).
            min_interval_seconds: Minimum pause between two requests, to be polite to servers.
        """
        self._client = client
        self._interval = min_interval_seconds
        self._last = 0.0

    def _get(self, url: str) -> httpx.Response:
        """GET a URL after the polite delay.

        Args:
            url: URL to request.

        Returns:
            The HTTP response.

        Raises:
            SourceError: On network errors.
        """
        wait = self._interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        start = time.monotonic()
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise SourceError(f"request failed: {exc}") from exc
        finally:
            self._last = time.monotonic()
        logger.info(
            "http get url=%s status=%s bytes=%d (%.0f ms)",
            url,
            resp.status_code,
            len(resp.content),
            (time.monotonic() - start) * 1000,
        )
        return resp

    def fetch(self, url: str) -> bytes | None:
        """Download a PDF, following one landing-page hop.

        Args:
            url: PDF or landing-page URL.

        Returns:
            PDF bytes, or None when no PDF was obtained.

        Raises:
            SourceError: On network errors.
        """
        resp = self._get(url)
        if resp.status_code != 200:
            return None
        if is_pdf(resp.content):
            return resp.content
        pdf_url = parse_citation_pdf_url(resp.text, str(resp.url))
        if pdf_url is None or pdf_url == url:
            return None
        hop = self._get(pdf_url)
        return hop.content if hop.status_code == 200 and is_pdf(hop.content) else None
