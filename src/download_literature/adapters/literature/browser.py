"""Publisher PDF fetcher that drives the installed Google Chrome through Playwright (ADR-001).

Route: `https://go.openathens.net/redirector/<domain>?url=https://doi.org/<doi>`. On campus the
redirector forwards straight to the publisher (IP access); off campus it shows the OpenAthens
sign-in page, where the library e-mail / password from `.env` are filled in. Credentials are only
ever typed on `*.openathens.net` pages. Cloudflare checks, CAPTCHAs and Google / Microsoft sign-in
are never automated: the script waits for the user to finish them in the visible window.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from pathlib import Path
from types import TracebackType
from urllib.parse import quote, urlparse

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from download_literature.domain.literature import Reference, SourceError, is_pdf

logger = logging.getLogger(__name__)

_CHALLENGE_TITLES = ("just a moment", "請稍候", "attention required", "verify you are human")
_FETCH_JS = """async (url) => {
  try {
    const r = await fetch(url, {credentials: 'include'});
    const b = new Uint8Array(await r.arrayBuffer());
    let s = '';
    for (let i = 0; i < b.length; i += 32768) {
      s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
    }
    return {status: r.status, data: btoa(s)};
  } catch (e) { return {status: String(e), data: ''}; }
}"""
_PDF_META_JS = "() => document.querySelector('meta[name=\"citation_pdf_url\"]')?.content || null"


def _origin(url: str) -> str:
    """Return the scheme and host of a URL.

    Args:
        url: Any URL.

    Returns:
        `scheme://host[:port]`.
    """
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


def entry_url(doi: str, openathens_domain: str) -> str:
    """Build the URL that opens a DOI with institutional access.

    Args:
        doi: DOI without prefix.
        openathens_domain: OpenAthens organisation domain (e.g. `ndhu.edu.tw`); empty = plain DOI link.

    Returns:
        The OpenAthens redirector URL, or the doi.org URL.
    """
    doi_url = f"https://doi.org/{doi}"
    if not openathens_domain:
        return doi_url
    return f"https://go.openathens.net/redirector/{openathens_domain}?url={quote(doi_url, safe='')}"


def is_openathens_host(url: str) -> bool:
    """Tell whether a page belongs to OpenAthens (the only place credentials may be typed).

    Args:
        url: Current page URL.

    Returns:
        True for `openathens.net` and its sub-domains.
    """
    host = (urlparse(url).hostname or "").lower()
    return host == "openathens.net" or host.endswith(".openathens.net")


def guess_pdf_url(page_url: str) -> str | None:
    """Guess the PDF link on Atypon-style publisher sites (Sage, Wiley, T&F, NEJM, ACM).

    Args:
        page_url: Article page URL such as `https://host/doi/full/10.x/y`.

    Returns:
        `https://host/doi/pdf/10.x/y`, or None when the URL has no `/doi/` path.
    """
    match = re.match(r"(https?://[^/]+)/doi/(?:(?:abs|full|epdf|epub|reader)/)?(10\..+)", page_url)
    return f"{match.group(1)}/doi/pdf/{match.group(2)}" if match else None


def pdf_url_variants(pdf_url: str) -> list[str]:
    """List the URLs to try for one PDF link, most likely first.

    Args:
        pdf_url: PDF link found on the article page.

    Returns:
        For Wiley (`/doi/pdf/` opens a viewer) the `/doi/pdfdirect/...?download=true` file URL first,
        then the original; for other sites just the original.
    """
    if "wiley.com/doi/pdf/" in pdf_url:
        return [pdf_url.replace("/doi/pdf/", "/doi/pdfdirect/", 1) + "?download=true", pdf_url]
    return [pdf_url]


class BrowserPublisherFetcher:
    """Opens each DOI in a visible Chrome window and saves the publisher PDF.

    Use as a context manager so the browser is closed afterwards.
    """

    def __init__(
        self, profile_dir: Path, openathens_domain: str, login: tuple[str, str], wait_seconds: int = 300
    ) -> None:
        """Create the fetcher (the browser starts in `__enter__`).

        Args:
            profile_dir: Persistent Chrome profile folder (keeps the sign-in between runs), in DATA_DIR.
            openathens_domain: OpenAthens organisation domain; empty = plain DOI links.
            login: (e-mail, password) for the OpenAthens sign-in page; empty strings = never auto-fill.
            wait_seconds: How long to wait for the user to finish a manual check or sign-in.
        """
        self._profile_dir = profile_dir
        self._domain = openathens_domain
        self._login = login
        self._wait = wait_seconds
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None

    def __enter__(self) -> BrowserPublisherFetcher:
        """Start Chrome with the persistent profile.

        Returns:
            This fetcher.
        """
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self._profile_dir), channel="chrome", headless=False, accept_downloads=True
        )
        logger.info("browser started profile=%s", self._profile_dir)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Close Chrome.

        Args:
            exc_type: Exception class, if any.
            exc: Exception, if any.
            tb: Traceback, if any.
        """
        if self._ctx is not None:
            self._ctx.close()
        if self._pw is not None:
            self._pw.stop()
        logger.info("browser closed")

    def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
        """Download the PDF via the publisher (DOI), then via the reference's own URLs in the browser.

        The second route covers author / university copies on sites that reject plain HTTP clients.

        Args:
            reference: Reference with a DOI.

        Returns:
            (PDF bytes, PDF URL), or None when no PDF could be obtained.

        Raises:
            SourceError: When the browser was not started.
        """
        if self._ctx is None:
            raise SourceError("browser not started")
        page = self._ctx.new_page()
        try:
            for url in [None, *reference.pdf_urls]:  # None = publisher route via the DOI
                try:
                    got = self._via_publisher(page, reference) if url is None else self._via_site(page, url)
                except PlaywrightError as exc:
                    logger.warning("browser route failed key=%s: %s", reference.key, exc.message)
                    continue
                if got is not None:
                    return got
            return None
        finally:
            page.close()

    def _via_publisher(self, page: Page, reference: Reference) -> tuple[bytes, str] | None:
        """Open the DOI (through OpenAthens) and download the publisher PDF.

        Args:
            page: Browser tab to use.
            reference: Reference with a DOI.

        Returns:
            (PDF bytes, PDF URL), or None.
        """
        page.goto(entry_url(reference.doi, self._domain), wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)
        pdf_url = self._find_pdf_url(page)
        logger.info("publisher page key=%s url=%s pdf=%s", reference.key, page.url, pdf_url)
        return self._download(page, pdf_url) if pdf_url else None

    def _via_site(self, page: Page, pdf_url: str) -> tuple[bytes, str] | None:
        """Download a known PDF URL from inside its own site (open the site's home page, then fetch).

        Opening the home page first avoids navigating to a file that the browser would save as a download.

        Args:
            page: Browser tab to use.
            pdf_url: Author or repository PDF URL.

        Returns:
            (PDF bytes, URL), or None.
        """
        page.goto(_origin(pdf_url) + "/", wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)
        body = self._fetch_in_page(page, pdf_url)
        return (body, pdf_url) if is_pdf(body) else None

    def _needs_user(self, page: Page) -> bool:
        """Tell whether the page is a sign-in or bot check the user has to finish.

        Args:
            page: Current page.

        Returns:
            True on OpenAthens / identity-provider pages or challenge pages.
        """
        try:
            title = (page.title() or "").lower()
        except PlaywrightError:
            return True  # page is navigating (e.g. a challenge redirect): keep waiting (ISSUE-003)
        host = (urlparse(page.url).hostname or "").lower()
        sign_in = is_openathens_host(page.url) or any(
            h in host for h in ("login.microsoftonline.com", "accounts.google.com", "sso.", "idp.")
        )
        return sign_in or any(t in title for t in _CHALLENGE_TITLES)

    def _settle(self, page: Page) -> None:
        """Fill the OpenAthens sign-in once, then wait until the user clears any remaining check.

        Args:
            page: Current page.
        """
        deadline = time.monotonic() + self._wait
        state = {"filled": False, "warned": False}
        clear_checks = 0  # a challenge page can vanish briefly before reloading; require two calm checks
        while clear_checks < 2 and time.monotonic() < deadline:
            if self._needs_user(page):
                clear_checks = 0
                self._handle_blocker(page, state)
            else:
                clear_checks += 1
            page.wait_for_timeout(1500)
        page.wait_for_load_state("domcontentloaded")

    def _handle_blocker(self, page: Page, state: dict[str, bool]) -> None:
        """Fill the OpenAthens form once, otherwise ask the user (once) to finish the check.

        Args:
            page: Page showing a sign-in or bot check.
            state: `filled` / `warned` flags shared across one `_settle` call.
        """
        if is_openathens_host(page.url) and not state["filled"]:
            state["filled"] = self._fill_openathens(page)
        elif not state["warned"]:
            logger.warning("請在 Chrome 視窗完成登入或驗證（最多等 %d 秒） url=%s", self._wait, page.url)
            state["warned"] = True

    def _fill_openathens(self, page: Page) -> bool:
        """Type the library e-mail and password on the OpenAthens page (one or two steps).

        Args:
            page: An `*.openathens.net` page.

        Returns:
            True when credentials were submitted, False when none are configured or no form was found.
        """
        email, password = self._login
        if not (email and password and is_openathens_host(page.url)):
            return False
        user_box = page.locator("input[type=email], input[name=username], input[name=email]").first
        if user_box.count() == 0:
            return False
        user_box.fill(email)
        pass_box = page.locator("input[type=password]").first
        if not pass_box.is_visible():
            user_box.press("Enter")
            pass_box.wait_for(state="visible", timeout=15_000)
        if not is_openathens_host(page.url):
            return False  # moved to another identity provider: leave it to the user
        pass_box.fill(password)
        pass_box.press("Enter")
        logger.info("openathens sign-in submitted")
        return True

    def _find_pdf_url(self, page: Page) -> str | None:
        """Find the PDF link on a publisher article page.

        Args:
            page: Article page.

        Returns:
            PDF URL from `citation_pdf_url`, or an Atypon-style guess, or None.
        """
        meta = page.evaluate(_PDF_META_JS)
        return str(meta) if meta else guess_pdf_url(page.url)

    def _fetch_in_page(self, page: Page, pdf_url: str) -> bytes:
        """Fetch a URL with the page's own `fetch()`, so the request is a normal browser request.

        Playwright's `context.request` runs outside the browser and is rejected by publisher bot
        protection (ISSUE-001); a fetch from inside the page uses the real browser session.

        Args:
            page: Page on the same site as `pdf_url`.
            pdf_url: PDF URL.

        Returns:
            Response body (may be HTML when access is denied); empty on a fetch error.
        """
        result = page.evaluate(_FETCH_JS, pdf_url)
        body = base64.b64decode(result.get("data") or "")
        logger.info("in-page fetch status=%s bytes=%d url=%s", result.get("status"), len(body), pdf_url)
        return body

    def _download(self, page: Page, pdf_url: str) -> tuple[bytes, str] | None:
        """Download the PDF from the article page; if that fails, open the PDF URL and fetch it there.

        Args:
            page: Article page whose context holds the publisher session.
            pdf_url: PDF URL.

        Returns:
            (PDF bytes, URL), or None.
        """
        got = self._fetch_variants(page, pdf_url)
        if got is not None:
            return got
        page.goto(pdf_url, wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)
        return self._fetch_variants(page, page.url)  # redirects may change the host (e.g. Wiley Compass)

    def _fetch_variants(self, page: Page, pdf_url: str) -> tuple[bytes, str] | None:
        """Try every URL variant of a PDF link that is on the page's own site.

        Args:
            page: Page used for the in-page fetch.
            pdf_url: PDF link.

        Returns:
            (PDF bytes, URL) for the first variant that yields a PDF, or None.
        """
        for url in pdf_url_variants(pdf_url):
            if _origin(page.url) == _origin(url):
                body = self._fetch_in_page(page, url)
                if is_pdf(body):
                    return body, url
        return None
