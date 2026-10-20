"""Airiti Library (華藝線上圖書館) adapter for Chinese references (ADR-007).

NDHU subscribes to Airiti (IP access on campus, OpenAthens off campus). The site needs a real browser:
- search: type the query into the search box; result titles carry the article DocID in their onclick;
- metadata: article pages (`/Article/Detail/<DocID>`) have full `citation_*` meta tags (incl. DOI);
- download: "Download" opens a confirmation dialog; "Yes" makes the browser download the PDF.
Uses the shared Chrome session (`BrowserPublisherFetcher`): sign-in and bot checks follow its rules.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from download_literature.adapters.literature.browser import BrowserPublisherFetcher
from download_literature.domain.apa import parse_apa
from download_literature.domain.literature import (
    Reference,
    ReferenceKind,
    SourceError,
    WorkMeta,
    has_cjk,
    title_matches,
)

logger = logging.getLogger(__name__)

AIRITI = "https://www.airitilibrary.com"
_DOCID = re.compile(r"點擊篇名\('([^']+)'")
_AIRITI_DOI = re.compile(r"^10\.(?:30\d{3}|29\d{3}|6\d{3})/", re.IGNORECASE)
_META_JS = (
    "() => [...document.querySelectorAll('meta[name^=\"citation_\"]')]"
    ".map(m => [m.getAttribute('name'), m.getAttribute('content') || ''])"
)
_RESULTS_JS = (
    "() => [...document.querySelectorAll('a[onclick*=\"點擊篇名\"]')]"
    ".map(a => [(a.innerText || '').trim(), a.getAttribute('onclick') || ''])"
)


def detail_url(doc_id: str) -> str:
    """Build an Airiti article page URL.

    Args:
        doc_id: Airiti DocID.

    Returns:
        Article page URL.
    """
    return f"{AIRITI}/Article/Detail/{doc_id}"


def is_airiti_doi(doi: str) -> bool:
    """Tell whether a DOI is one Airiti registers (Taiwanese journals; prefixes 10.30xxx, 10.29xxx, 10.6xxx).

    Args:
        doi: DOI without prefix.

    Returns:
        True for Airiti-style DOIs.
    """
    return _AIRITI_DOI.match(doi) is not None


def parse_result_links(links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Extract (title, DocID) pairs from search-result title links.

    Args:
        links: (link text, onclick) pairs.

    Returns:
        Results in page order.
    """
    found = []
    for text, onclick in links:
        match = _DOCID.search(onclick)
        if match and text:
            found.append((text, match.group(1)))
    return found


def _first(meta: dict[str, list[str]], name: str) -> str:
    """Return the first value of a meta tag.

    Args:
        meta: Tag name → values.
        name: Tag name.

    Returns:
        Stripped value, or empty.
    """
    return (meta.get(name) or [""])[0].strip()


def _group(match: re.Match[str] | None) -> str:
    """Return the first non-empty group of a match.

    Args:
        match: Regex match with alternative groups, or None.

    Returns:
        The group text, or empty.
    """
    return next((g for g in match.groups() if g), "") if match else ""


def volume_issue_from_text(text: str) -> tuple[str, str]:
    """Read volume and issue from an article page's text (Airiti's meta tags may lack them).

    Args:
        text: Page text, e.g. "《期刊》 35卷4期 (2022 / 12)" or "Volume 35 Issue 4".

    Returns:
        (volume, issue); empty strings when not found.
    """
    volume = re.search(r"(\d+)\s*卷|Volume\s+(\d+)", text)
    issue = re.search(r"(\d+)\s*期|Issue\s+(\d+)", text)
    return _group(volume), _group(issue)


def search_query(citation: str) -> str:
    """Choose what to type into Airiti's search box.

    Args:
        citation: Citation or title text.

    Returns:
        The title of a full APA citation, otherwise the text itself.
    """
    try:
        return parse_apa(citation).title or citation
    except ValueError:
        return citation


def parse_airiti_meta(meta: dict[str, list[str]]) -> WorkMeta | None:
    """Convert an article page's `citation_*` tags into a WorkMeta.

    Args:
        meta: Tag name → values (authors repeat).

    Returns:
        The work, or None without a title.
    """

    title = _first(meta, "citation_title")
    if not title:
        return None
    year = re.match(r"(\d{4})", _first(meta, "citation_date"))
    authors = tuple((a.strip(), "") for a in meta.get("citation_author", []) if a.strip())
    start, end = _first(meta, "citation_firstpage"), _first(meta, "citation_lastpage")
    return WorkMeta(
        _first(meta, "citation_doi"),
        title,
        int(year.group(1)) if year else None,
        ReferenceKind.ARTICLE,
        authors[0][0] if authors else "",
        authors=authors,
        container=_first(meta, "citation_journal_title"),
        volume=_first(meta, "citation_volume"),
        issue=_first(meta, "citation_issue").lstrip("0"),  # Airiti writes 0 when there is no issue number
        pages=f"{start}-{end}" if start and end else start,
        publisher=_first(meta, "citation_publisher"),
        genre="journal-article",
        url=_first(meta, "citation_abstract_html_url"),
    )


class AiritiLibrary:
    """Search, identify and download Chinese references on Airiti (resolver + download route)."""

    label = "華藝"  # step name shown while this route runs

    def __init__(self, browser: BrowserPublisherFetcher, max_details: int = 3) -> None:
        """Create the adapter.

        Args:
            browser: Started Chrome session.
            max_details: How many search results to open for their metadata.
        """
        self._browser = browser
        self._max = max_details

    def _article(self, page: Page, url: str) -> WorkMeta | None:
        """Open an article page and read its metadata.

        Args:
            page: Browser tab.
            url: Article page (or a DOI link that redirects to it).

        Returns:
            The work, or None when the page is not an Airiti article.
        """
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._browser.settle(page)
        if "/Article/Detail/" not in page.url:
            return None
        meta: dict[str, list[str]] = {}
        for name, content in page.evaluate(_META_JS):
            meta.setdefault(name, []).append(content)
        work = parse_airiti_meta(meta)
        if work is None:
            return None
        volume, issue = work.volume, work.issue
        if not volume and not issue:
            volume, issue = volume_issue_from_text(page.evaluate("() => document.body.innerText"))
        return WorkMeta(**{**work.__dict__, "url": work.url or page.url, "volume": volume, "issue": issue})

    def _search_ids(self, page: Page, query: str) -> list[str]:
        """Search Airiti and return result DocIDs.

        Args:
            page: Browser tab.
            query: Title or citation text.

        Returns:
            DocIDs of the first results.
        """
        page.goto(AIRITI + "/", wait_until="domcontentloaded", timeout=60_000)
        self._browser.settle(page)
        box = page.locator("input[type=text], input[type=search]").first
        box.fill(query[:120])
        box.press("Enter")
        try:
            page.wait_for_selector("a[onclick*='點擊篇名']", timeout=25_000)
        except PlaywrightError:
            return []
        return [doc for _, doc in parse_result_links(page.evaluate(_RESULTS_JS))][: self._max]

    def search(self, citation: str) -> list[WorkMeta]:
        """Search Airiti (Chinese inputs only) and read the metadata of the top results.

        Args:
            citation: Citation or title text.

        Returns:
            Works found (unverified; the caller checks title, year and author).

        Raises:
            SourceError: On browser errors.
        """
        if not has_cjk(citation):
            return []
        page = self._browser.new_page()
        try:
            works = [
                self._article(page, detail_url(d)) for d in self._search_ids(page, search_query(citation))
            ]
        except PlaywrightError as exc:
            raise SourceError(f"airiti search failed: {exc.message}") from exc
        finally:
            page.close()
        logger.info("airiti search results=%d", len(works))
        return [w for w in works if w is not None]

    def by_doi(self, doi: str) -> WorkMeta | None:
        """Look up an Airiti-registered DOI.

        Args:
            doi: DOI without prefix.

        Returns:
            The work, or None for other DOIs.

        Raises:
            SourceError: On browser errors.
        """
        if not is_airiti_doi(doi):
            return None
        page = self._browser.new_page()
        try:
            return self._article(page, f"https://doi.org/{doi}")
        except PlaywrightError as exc:
            raise SourceError(f"airiti doi lookup failed: {exc.message}") from exc
        finally:
            page.close()

    def _article_url(self, reference: Reference) -> str:
        """Find the reference's Airiti article page.

        Args:
            reference: Reference to download.

        Returns:
            Article URL, a DOI link for Airiti DOIs, or empty.
        """
        listed = [u for u in reference.pdf_urls if "airitilibrary.com/Article/Detail/" in u]
        if listed:
            return listed[0]
        return f"https://doi.org/{reference.doi}" if reference.doi and is_airiti_doi(reference.doi) else ""

    def _find_by_title(self, page: Page, reference: Reference) -> WorkMeta | None:
        """Search a Chinese title on Airiti and open the matching article.

        Args:
            page: Browser tab.
            reference: Reference with a Chinese title.

        Returns:
            The matching article (page left open on it), or None.
        """
        for doc_id in self._search_ids(page, reference.title):
            work = self._article(page, detail_url(doc_id))
            if (
                work
                and title_matches(reference.title, work.title, 0.8)
                and title_matches(work.title, reference.title, 0.8)
            ):
                return work
        return None

    def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
        """Download a Chinese reference's PDF from Airiti (Download → Yes).

        Args:
            reference: Reference with an Airiti page, an Airiti DOI or a Chinese title.

        Returns:
            (PDF bytes, article URL), or None when Airiti does not have it.

        Raises:
            SourceError: On browser errors.
        """
        url = self._article_url(reference)
        if not url and not has_cjk(reference.title):
            return None
        page = self._browser.new_page()
        try:
            found = self._article(page, url) if url else self._find_by_title(page, reference)
            if found is None:
                return None
            page.locator("a,button", has_text="Download").first.click()
            with page.context.expect_event("download", timeout=60_000) as info:
                page.get_by_role("button", name="Yes").first.click()
            data = Path(info.value.path()).read_bytes()
            logger.info("airiti pdf key=%s bytes=%d", reference.key, len(data))
            return data, page.url
        except PlaywrightError as exc:
            raise SourceError(f"airiti download failed: {exc.message}") from exc
        finally:
            page.close()
