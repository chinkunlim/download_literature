"""EBSCO adapter: finds a reference on the library's EBSCO Discovery profile and saves its PDF (ADR-003).

EBSCO aggregates full text from many publishers (e.g. PsycARTICLES, Academic Search Premier), so it
often has the version of record when the publisher site is closed to the library or shows bot checks.
Flow: search the DOI (or title) → keep only results whose title matches the reference → open the PDF
viewer → keep the `application/pdf` response the viewer loads. Uses the shared Chrome profile.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from download_literature.adapters.literature.browser import BrowserPublisherFetcher
from download_literature.domain.literature import Reference, SourceError, title_matches

logger = logging.getLogger(__name__)

EBSCO_BASE = "https://research.ebsco.com/c"
_DETAIL_ID = re.compile(r"/search/details/([^/?#]+)")
_RESULT_LINKS_JS = (
    "() => [...document.querySelectorAll(\"a[href*='/search/details/']\")]"
    ".map(a => [(a.innerText || '').trim(), a.getAttribute('href') || ''])"
)


def ebsco_results_url(profile: str, query: str) -> str:
    """Build the EBSCO search-results URL.

    Args:
        profile: The library's EBSCO profile id (NDHU: `3pnjf3`).
        query: DOI or title.

    Returns:
        Results page URL.
    """
    return f"{EBSCO_BASE}/{profile}/search/results?q={quote(query, safe='')}"


def ebsco_viewer_url(profile: str, detail_id: str) -> str:
    """Build the EBSCO PDF viewer URL for a record.

    Args:
        profile: The library's EBSCO profile id.
        detail_id: Record id from a `/search/details/<id>` link.

    Returns:
        Viewer page URL.
    """
    return f"{EBSCO_BASE}/{profile}/viewer/pdf/{detail_id}"


def pick_matching_results(results: list[tuple[str, str]], title: str) -> list[str]:
    """Keep the results that are the cited work (a DOI search also lists papers citing it).

    Args:
        results: (link text, href) pairs from the results page.
        title: Reference title; empty means nothing can be confirmed.

    Returns:
        Record ids of matching results, in page order, without duplicates.
    """
    if not title:
        return []
    ids: list[str] = []
    for text, href in results:
        match = _DETAIL_ID.search(href)
        same = title_matches(title, text, 0.8) and title_matches(text, title, 0.6)
        if match and same and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


class EbscoFetcher:
    """Downloads version-of-record PDFs through the library's EBSCO Discovery profile."""

    label = "EBSCO"  # step name shown while this route runs

    def __init__(self, browser: BrowserPublisherFetcher, profile: str, max_records: int = 2) -> None:
        """Create the fetcher.

        Args:
            browser: Started Chrome session (shared profile, sign-in and bot-check waiting).
            profile: The library's EBSCO profile id.
            max_records: How many matching records to try (duplicates from several databases are common).
        """
        self._browser = browser
        self._profile = profile
        self._max = max_records

    def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
        """Search EBSCO for the reference and download its PDF.

        Args:
            reference: Reference with a title (needed to confirm the search result).

        Returns:
            (PDF bytes, viewer URL), or None when EBSCO has no PDF for it.

        Raises:
            SourceError: When the browser fails.
        """
        if not reference.title:
            return None
        page = self._browser.new_page()
        try:
            for detail_id in self._find_records(page, reference):
                got = self._viewer_pdf(page, detail_id)
                if got is not None:
                    return got
            return None
        except PlaywrightError as exc:
            raise SourceError(f"ebsco browser error: {exc.message}") from exc
        finally:
            page.close()

    def _find_records(self, page: Page, reference: Reference) -> list[str]:
        """Search by DOI (or title) and return matching record ids.

        Args:
            page: Browser tab.
            reference: Reference being processed.

        Returns:
            Up to `max_records` record ids.
        """
        page.goto(
            ebsco_results_url(self._profile, reference.doi or reference.title), wait_until="domcontentloaded"
        )
        self._browser.settle(page)
        try:
            page.wait_for_selector("a[href*='/search/details/']", timeout=25_000)
        except PlaywrightError:
            logger.info("ebsco no results key=%s", reference.key)
            return []
        ids = pick_matching_results([(t, h) for t, h in page.evaluate(_RESULT_LINKS_JS)], reference.title)
        logger.info("ebsco results key=%s matching=%d", reference.key, len(ids))
        return ids[: self._max]

    def _viewer_pdf(self, page: Page, detail_id: str) -> tuple[bytes, str] | None:
        """Open the PDF viewer for a record and capture the PDF it loads.

        Args:
            page: Browser tab.
            detail_id: Record id.

        Returns:
            (PDF bytes, viewer URL), or None when the record has no PDF (e.g. HTML full text only).
        """
        url = ebsco_viewer_url(self._profile, detail_id)
        try:
            with page.expect_response(
                lambda r: "application/pdf" in r.headers.get("content-type", ""), timeout=45_000
            ) as info:
                page.goto(url, wait_until="domcontentloaded")
            body = info.value.body()
        except PlaywrightError:
            logger.info("ebsco no pdf record=%s", detail_id)
            return None
        logger.info("ebsco pdf record=%s bytes=%d", detail_id, len(body))
        return body, url
