"""Offline tests for the literature downloader: models, parsers, reference file, report and service flow."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.browser import (  # noqa: E402
    entry_url,
    guess_pdf_url,
    is_openathens_host,
    pdf_url_variants,
)
from download_literature.adapters.literature.ebsco import (  # noqa: E402
    ebsco_results_url,
    ebsco_viewer_url,
    pick_matching_results,
)
from download_literature.adapters.literature.files import FilePdfStore, load_references  # noqa: E402
from download_literature.adapters.literature.http_pdf import parse_citation_pdf_url  # noqa: E402
from download_literature.adapters.literature.openalex import parse_openalex_locations  # noqa: E402
from download_literature.config.settings import AppConfig  # noqa: E402
from download_literature.domain.literature import (  # noqa: E402
    DownloadStatus,
    OaLocation,
    Reference,
    ReferenceKind,
    SourceError,
    is_pdf,
    safe_filename,
    title_matches,
)
from download_literature.services.literature import Sources, download_all, render_report  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PDF = b"%PDF-1.7\n" + b"x" * 2000


class FakeFinder:
    """Open-access finder: `urls` are published versions, `copies` are preprints / accepted manuscripts."""

    def __init__(self, urls: dict[str, list[str]], copies: dict[str, list[str]] | None = None) -> None:
        self.urls = urls
        self.copies = copies or {}

    def find_pdf_locations(self, doi: str) -> list[OaLocation]:
        published = [OaLocation(u, True) for u in self.urls.get(doi, [])]
        return published + [OaLocation(u, False) for u in self.copies.get(doi, [])]


class FakeHttp:
    """HTTP fetcher answering from a URL -> bytes map (missing URLs return None, 'boom' raises)."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> bytes | None:
        self.calls.append(url)
        if url == "boom":
            raise SourceError("network down")
        return self.pages.get(url)


class FakePublisher:
    """Publisher fetcher returning a PDF for the listed DOIs."""

    def __init__(self, dois: set[str]) -> None:
        self.dois = dois
        self.calls: list[str] = []

    def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
        self.calls.append(reference.doi)
        return (PDF, f"https://publisher.example/{reference.doi}") if reference.doi in self.dois else None


class DomainTest(unittest.TestCase):
    """Pure helpers in the domain layer."""

    def test_is_pdf_accepts_pdf_and_rejects_html(self) -> None:
        """Only content starting with the PDF signature counts as a PDF."""
        self.assertTrue(is_pdf(PDF))
        self.assertTrue(is_pdf(b"\n\n%PDF-1.4 rest"))
        self.assertFalse(is_pdf(b"<!DOCTYPE html><title>Just a moment...</title>"))
        self.assertFalse(is_pdf(b""))

    def test_safe_filename_strips_unsafe_characters(self) -> None:
        """Keys become portable file names."""
        self.assertEqual(safe_filename("Torre & Lieberman/2018: Emotion?"), "Torre_Lieberman_2018_Emotion")

    def test_candidate_urls_put_arxiv_and_explicit_urls_first(self) -> None:
        """arXiv PDF comes first, then explicitly listed URLs."""
        ref = Reference(key="k", citation="c", arxiv_id="2310.15461", pdf_urls=("https://x/y.pdf",))
        self.assertEqual(ref.direct_urls(), ("https://arxiv.org/pdf/2310.15461", "https://x/y.pdf"))


class FakeText:
    """PDF text reader returning a fixed first-page text per PDF body."""

    def __init__(self, texts: dict[bytes, str]) -> None:
        self.texts = texts

    def first_pages_text(self, data: bytes) -> str:
        return self.texts.get(data, "")


class TitleTest(unittest.TestCase):
    """Title check that keeps wrong papers out."""

    def test_title_matches_despite_case_punctuation_and_line_breaks(self) -> None:
        """Most title words present, in any case or layout, counts as a match."""
        text = "Qualitative Research in Psychology\nUsing the-\nmatic analysis in PSYCHOLOGY\nVirginia Braun"
        self.assertTrue(title_matches("Using thematic analysis in psychology", text))

    def test_other_paper_does_not_match(self) -> None:
        """A different paper's first page is rejected."""
        text = "Representations and lived experiences of sexual health among young adults"
        self.assertFalse(title_matches("Using thematic analysis in psychology", text))

    def test_empty_title_always_matches(self) -> None:
        """Without a title there is nothing to check."""
        self.assertTrue(title_matches("", "anything"))


class ParserTest(unittest.TestCase):
    """Parsers for external formats."""

    def test_openalex_locations_with_version(self) -> None:
        """Unique OA PDFs, best first; published = publishedVersion or an unversioned journal copy."""
        data = json.loads((FIXTURES / "openalex_work.json").read_text(encoding="utf-8"))
        self.assertEqual(
            parse_openalex_locations(data),
            [
                OaLocation("https://www.frontiersin.org/articles/10.3389/fpsyt.2016.00215/pdf", True),
                OaLocation("https://europepmc.org/articles/pmc5222787?pdf=render", False),
                OaLocation("https://journal.example/no-version.pdf", True),
            ],
        )

    def test_citation_pdf_url_is_resolved_against_page_url(self) -> None:
        """The citation_pdf_url meta tag is found and made absolute."""
        html = '<html><head><meta content="/bitstream/1/2/paper.pdf" name="citation_pdf_url"></head></html>'
        self.assertEqual(
            parse_citation_pdf_url(html, "https://deepblue.example.edu/items/abc"),
            "https://deepblue.example.edu/bitstream/1/2/paper.pdf",
        )
        self.assertIsNone(parse_citation_pdf_url("<html></html>", "https://x"))


class BrowserHelpersTest(unittest.TestCase):
    """Pure helpers of the publisher browser adapter."""

    def test_entry_url_uses_openathens_redirector(self) -> None:
        """With a domain the DOI link is wrapped in the OpenAthens redirector."""
        self.assertEqual(
            entry_url("10.1/a", "ndhu.edu.tw"),
            "https://go.openathens.net/redirector/ndhu.edu.tw?url=https%3A%2F%2Fdoi.org%2F10.1%2Fa",
        )
        self.assertEqual(entry_url("10.1/a", ""), "https://doi.org/10.1/a")

    def test_credentials_only_on_openathens_hosts(self) -> None:
        """Only openathens.net pages qualify for auto-filled credentials."""
        self.assertTrue(is_openathens_host("https://login.openathens.net/auth/x"))
        self.assertFalse(is_openathens_host("https://openathens.net.evil.example/login"))
        self.assertFalse(is_openathens_host("https://accounts.google.com/"))

    def test_guess_pdf_url_for_atypon_sites(self) -> None:
        """Atypon article URLs map to their /doi/pdf/ counterpart."""
        self.assertEqual(
            guess_pdf_url("https://journals.sagepub.com/doi/full/10.1177/1754073917742706"),
            "https://journals.sagepub.com/doi/pdf/10.1177/1754073917742706",
        )
        self.assertIsNone(guess_pdf_url("https://www.sciencedirect.com/science/article/pii/S0065"))

    def test_wiley_pdfdirect_variant_is_tried_first(self) -> None:
        """Wiley serves the file at /doi/pdfdirect/; other sites keep their URL."""
        self.assertEqual(
            pdf_url_variants("https://compass.onlinelibrary.wiley.com/doi/pdf/10.1111/x"),
            [
                "https://compass.onlinelibrary.wiley.com/doi/pdfdirect/10.1111/x?download=true",
                "https://compass.onlinelibrary.wiley.com/doi/pdf/10.1111/x",
            ],
        )
        self.assertEqual(
            pdf_url_variants("https://journals.sagepub.com/doi/pdf/10.1/y"),
            ["https://journals.sagepub.com/doi/pdf/10.1/y"],
        )


class EbscoHelpersTest(unittest.TestCase):
    """Pure helpers of the EBSCO adapter."""

    def test_urls(self) -> None:
        """Search and viewer URLs use the library's EBSCO profile id."""
        self.assertEqual(
            ebsco_results_url("3pnjf3", "10.1037/a0027600"),
            "https://research.ebsco.com/c/3pnjf3/search/results?q=10.1037%2Fa0027600",
        )
        self.assertEqual(
            ebsco_viewer_url("3pnjf3", "zghjhqze7r"),
            "https://research.ebsco.com/c/3pnjf3/viewer/pdf/zghjhqze7r",
        )

    def test_only_results_with_the_cited_title_are_kept(self) -> None:
        """Papers that merely cite the DOI are skipped; detail ids are taken from the links."""
        results = [
            ("Self-distancing in children", "/c/3pnjf3/search/details/aaa111?pos=1&q=x"),
            (
                "Dealing With Feeling: A Meta-Analysis of the Effectiveness of Strategies",
                "/c/3pnjf3/search/details/zghjhqze7r?pos=2",
            ),
            ("no link", ""),
        ]
        self.assertEqual(
            pick_matching_results(
                results, "Dealing with feeling: A meta-analysis of the effectiveness of strategies"
            ),
            ["zghjhqze7r"],
        )
        self.assertEqual(pick_matching_results(results, ""), [])


class FilesTest(unittest.TestCase):
    """Reference file loading and PDF storage."""

    def test_load_references_reads_kinds_and_defaults(self) -> None:
        """Entries are parsed into Reference objects; missing fields get defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refs.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "key": "A_2020",
                            "citation": "A (2020)",
                            "doi": "10.1/a",
                            "arxiv_id": "1234.5678",
                            "title": "T",
                        },
                        {"key": "Beck_1976", "citation": "Beck (1976)", "kind": "book"},
                    ]
                ),
                encoding="utf-8",
            )
            refs = load_references(path)
        self.assertEqual(refs[0].doi, "10.1/a")
        self.assertEqual(refs[0].title, "T")
        self.assertEqual(refs[0].kind, ReferenceKind.ARTICLE)
        self.assertEqual(refs[1].kind, ReferenceKind.BOOK)
        self.assertEqual(refs[1].pdf_urls, ())

    def test_store_saves_and_finds_existing_pdf(self) -> None:
        """Saved PDFs are found again by key."""
        with tempfile.TemporaryDirectory() as tmp:
            store = FilePdfStore(Path(tmp))
            self.assertIsNone(store.existing("A_2020"))
            saved = store.save("A_2020", PDF)
            self.assertEqual(store.existing("A_2020"), saved)
            self.assertEqual(saved.read_bytes(), PDF)


class ServiceTest(unittest.TestCase):
    """The download flow in services.literature."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FilePdfStore(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _sources(self, http: FakeHttp, finder: FakeFinder, publisher: FakePublisher | None = None) -> Sources:
        return Sources(
            open_access=finder, http=http, publishers=(publisher,) if publisher else (), store=self.store
        )

    def test_books_are_marked_manual_without_network(self) -> None:
        """Books are never fetched; they are listed for manual handling."""
        http = FakeHttp({})
        [outcome] = download_all(
            [Reference("Beck_1976", "Beck", kind=ReferenceKind.BOOK)], self._sources(http, FakeFinder({}))
        )
        self.assertEqual(outcome.status, DownloadStatus.MANUAL)
        self.assertEqual(http.calls, [])

    def test_existing_file_is_not_downloaded_again(self) -> None:
        """A PDF already on disk is reported and skipped."""
        self.store.save("A", PDF)
        http = FakeHttp({})
        [outcome] = download_all([Reference("A", "A", doi="10.1/a")], self._sources(http, FakeFinder({})))
        self.assertEqual(outcome.status, DownloadStatus.ALREADY_PRESENT)
        self.assertEqual(http.calls, [])

    def test_open_access_pdf_is_saved(self) -> None:
        """An OA URL returning a real PDF is saved and the publisher is not used."""
        publisher = FakePublisher({"10.1/a"})
        sources = self._sources(
            FakeHttp({"https://oa/a.pdf": PDF}), FakeFinder({"10.1/a": ["https://oa/a.pdf"]}), publisher
        )
        [outcome] = download_all([Reference("A", "A", doi="10.1/a")], sources)
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)
        self.assertEqual(outcome.source, "https://oa/a.pdf")
        self.assertEqual(publisher.calls, [])
        self.assertTrue(outcome.path is not None and outcome.path.is_file())

    def test_html_and_errors_fall_back_to_publisher(self) -> None:
        """Non-PDF answers and source errors are skipped; the publisher route is tried last."""
        http = FakeHttp({"https://oa/a.pdf": b"<html>challenge</html>"})
        finder = FakeFinder({"10.1/a": ["boom", "https://oa/a.pdf"]})
        [outcome] = download_all(
            [Reference("A", "A", doi="10.1/a")], self._sources(http, finder, FakePublisher({"10.1/a"}))
        )
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)
        self.assertEqual(outcome.source, "https://publisher.example/10.1/a")

    def test_wrong_paper_is_rejected_and_next_source_used(self) -> None:
        """A PDF whose first pages do not show the title is skipped."""
        wrong, right = PDF + b"wrong", PDF + b"right"
        http = FakeHttp({"https://oa/wrong.pdf": wrong, "https://oa/right.pdf": right})
        finder = FakeFinder({"10.1/a": ["https://oa/wrong.pdf", "https://oa/right.pdf"]})
        texts = FakeText(
            {wrong: "Sexual health of young adults", right: "Using thematic analysis in psychology"}
        )
        sources = Sources(open_access=finder, http=http, publishers=(), store=self.store, pdf_text=texts)
        ref = Reference("A", "A", doi="10.1/a", title="Using thematic analysis in psychology")
        [outcome] = download_all([ref], sources)
        self.assertEqual(outcome.source, "https://oa/right.pdf")

    def test_unreadable_pdf_text_is_accepted(self) -> None:
        """Scanned PDFs without a text layer are kept (nothing to compare)."""
        sources = Sources(
            FakeFinder({"10.1/a": ["https://oa/a.pdf"]}),
            FakeHttp({"https://oa/a.pdf": PDF}),
            None,
            self.store,
            FakeText({}),
        )
        [outcome] = download_all([Reference("A", "A", doi="10.1/a", title="Some title here")], sources)
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)

    def test_next_institutional_route_is_tried_after_a_wrong_paper(self) -> None:
        """When the first route (e.g. EBSCO) returns another paper, the next route (publisher) is used."""

        class WrongPaper:
            def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
                return PDF + b"wrong", "https://ebsco.example/wrong"

        texts = FakeText(
            {PDF + b"wrong": "Another study entirely", PDF: "Dealing with feeling meta-analysis"}
        )
        right = FakePublisher({"10.1/a"})
        sources = Sources(FakeFinder({}), FakeHttp({}), (WrongPaper(), right), self.store, texts)
        ref = Reference("A", "A", doi="10.1/a", title="Dealing with feeling meta-analysis")
        [outcome] = download_all([ref], sources)
        self.assertEqual(outcome.source, "https://publisher.example/10.1/a")

    def test_preprints_and_author_copies_come_after_institutional_routes(self) -> None:
        """arXiv, accepted manuscripts and listed URLs are used only when EBSCO / publisher fail."""
        ref = Reference("A", "A", doi="10.1/a", arxiv_id="1234.5678", pdf_urls=("https://lab/a.pdf",))
        http = FakeHttp({"https://arxiv.org/pdf/1234.5678": PDF})
        publisher = FakePublisher({"10.1/a"})
        [outcome] = download_all([ref], Sources(FakeFinder({}), http, (publisher,), self.store))
        self.assertEqual(outcome.source, "https://publisher.example/10.1/a")
        self.assertEqual(http.calls, [])

    def test_author_copy_is_flagged_in_the_outcome(self) -> None:
        """A secondary copy is saved but marked so its page numbers get checked."""
        finder = FakeFinder({}, {"10.1/a": ["https://repo/accepted.pdf"]})
        http = FakeHttp({"https://repo/accepted.pdf": PDF})
        [outcome] = download_all([Reference("A", "A", doi="10.1/a")], Sources(finder, http, (), self.store))
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)
        self.assertIn("author/preprint copy", outcome.detail)

    def test_site_fetcher_retries_listed_urls_blocked_for_plain_http(self) -> None:
        """Listed URLs that plain HTTP cannot fetch are retried in the browser."""
        ref = Reference("A", "A", doi="10.1/a", pdf_urls=("https://lab/a.pdf",))
        site = FakeHttp({"https://lab/a.pdf": PDF})
        sources = Sources(FakeFinder({}), FakeHttp({}), (), self.store, None, site)
        [outcome] = download_all([ref], sources)
        self.assertEqual(outcome.source, "https://lab/a.pdf")
        self.assertEqual(site.calls, ["https://lab/a.pdf"])

    def test_refresh_replaces_copy_with_official_version(self) -> None:
        """--refresh sets the old file aside and keeps the newly found official PDF."""
        self.store.save("A", PDF + b"old")
        sources = self._sources(FakeHttp({}), FakeFinder({}), FakePublisher({"10.1/a"}))
        [outcome] = download_all([Reference("A", "A", doi="10.1/a")], sources, refresh=frozenset({"A"}))
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)
        assert outcome.path is not None
        self.assertEqual(outcome.path.read_bytes(), PDF)
        self.assertTrue((Path(self.tmp.name) / "superseded" / "A.pdf").is_file())

    def test_refresh_keeps_old_file_when_nothing_better_is_found(self) -> None:
        """Without an official version the previous file is restored."""
        self.store.save("A", PDF + b"old")
        sources = self._sources(FakeHttp({}), FakeFinder({}))
        [outcome] = download_all([Reference("A", "A", doi="10.1/a")], sources, refresh=frozenset({"A"}))
        self.assertEqual(outcome.status, DownloadStatus.ALREADY_PRESENT)
        assert outcome.path is not None
        self.assertEqual(outcome.path.read_bytes(), PDF + b"old")
        self.assertIn("kept the previous copy", outcome.detail)

    def test_failure_when_every_source_fails(self) -> None:
        """Without any PDF the reference is reported as failed."""
        [outcome] = download_all(
            [Reference("A", "A", doi="10.1/a")], self._sources(FakeHttp({}), FakeFinder({}))
        )
        self.assertEqual(outcome.status, DownloadStatus.FAILED)
        self.assertIsNone(outcome.path)

    def test_report_lists_every_reference(self) -> None:
        """The Markdown report has one row per reference and a summary line."""
        outcomes = download_all(
            [
                Reference("Beck_1976", "Beck (1976)", kind=ReferenceKind.BOOK),
                Reference("A", "A (2020)", doi="10.1/a"),
            ],
            self._sources(FakeHttp({}), FakeFinder({})),
        )
        report = render_report(outcomes)
        self.assertIn("Beck (1976)", report)
        self.assertIn("A (2020)", report)
        self.assertIn("manual: 1", report)
        self.assertIn("failed: 1", report)


class ConfigTest(unittest.TestCase):
    """Library credentials in the config layer."""

    def test_password_is_hidden_from_repr(self) -> None:
        """The password never appears when the config is logged or printed."""
        cfg = AppConfig(library_email="a@b.c", library_password="s3cret-value")
        self.assertNotIn("s3cret-value", repr(cfg))
        self.assertEqual(cfg.literature_dir, cfg.output_dir / "literature")


if __name__ == "__main__":
    unittest.main()
