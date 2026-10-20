"""Offline tests for the book route: Open Library parsing and the book download flow."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.files import FilePdfStore  # noqa: E402
from download_literature.adapters.literature.openlibrary import (  # noqa: E402
    ia_public_pdf,
    latest_edition,
    matching_works,
)
from download_literature.domain.literature import (  # noqa: E402
    BookInfo,
    DownloadStatus,
    Reference,
    ReferenceKind,
)
from download_literature.services.literature import Sources, download_all  # noqa: E402

PDF = b"%PDF-1.4\n" + b"y" * 500


class OpenLibraryParseTest(unittest.TestCase):
    """Parsing Open Library and Internet Archive records."""

    def test_matching_works_need_title_and_author(self) -> None:
        """Works with the same title and author match; other authors do not."""
        docs = [
            {
                "key": "/works/W1",
                "title": "Cognitive therapy and the emotional disorders",
                "author_name": ["Aaron T. Beck"],
            },
            {
                "key": "/works/W2",
                "title": "Cognitive Therapy and the Emotional Disorders",
                "author_name": ["Aaron T. Beck"],
            },
            {
                "key": "/works/W3",
                "title": "Cognitive therapy and the emotional disorders",
                "author_name": ["Someone Else"],
            },
            {"key": "/works/W4", "title": "Feeling good", "author_name": ["Aaron T. Beck"]},
        ]
        found = matching_works(docs, "Cognitive therapy and the emotional disorders", "Beck")
        self.assertEqual([d["key"] for d in found], ["/works/W1", "/works/W2"])

    def test_statement_of_responsibility_is_ignored(self) -> None:
        """Catalogue titles like 'Title / Author' still match."""
        docs = [
            {
                "key": "/works/W9",
                "title": "Feeling good : the new mood therapy / David D. Burns",
                "author_name": ["David D. Burns"],
            }
        ]
        self.assertEqual(len(matching_works(docs, "Feeling good: The new mood therapy", "Burns")), 1)

    def test_record_without_subtitle_matches_main_title(self) -> None:
        """A catalogue record that omits the subtitle matches on the main title."""
        docs = [
            {"key": "/works/W8", "title": "Feeling Good", "author_name": ["David D. Burns"]},
            {"key": "/works/W7", "title": "Feeling Good Together", "author_name": ["David D. Burns"]},
        ]
        found = matching_works(docs, "Feeling good: The new mood therapy", "Burns")
        self.assertEqual([d["key"] for d in found], ["/works/W8"])

    def test_latest_edition_is_the_newest_year(self) -> None:
        """The newest edition wins and is described with publisher, edition, ISBN and pages."""
        entries = [
            {"publish_date": "1980", "publishers": ["Morrow"]},
            {
                "publish_date": "Jan 01, 2008",
                "publishers": ["Harper"],
                "edition_name": "Rev. and updated ed.",
                "isbn_13": ["9780380810338"],
                "number_of_pages": 736,
            },
            {"publish_date": "1999", "publishers": ["Avon"]},
            {"publishers": ["No date"]},
        ]
        edition = latest_edition(entries)
        assert edition is not None
        self.assertEqual(edition[0], 2008)
        self.assertEqual(edition[1], "2008, Harper, Rev. and updated ed., ISBN 9780380810338, 736 pages")

    def test_audio_editions_are_not_the_latest_edition(self) -> None:
        """Audiobooks are skipped when choosing the latest edition."""
        entries = [
            {"publish_date": "2017", "publishers": ["HarperAudio"], "physical_format": "Audio CD"},
            {"publish_date": "2016", "publishers": ["Blackstone"], "physical_format": "MP3 CD"},
            {"publish_date": "2008", "publishers": ["Harper"], "physical_format": "Paperback"},
        ]
        edition = latest_edition(entries)
        assert edition is not None
        self.assertEqual(edition[0], 2008)

    def test_only_unrestricted_text_pdfs(self) -> None:
        """Public scans give their Text PDF; lending-only items give nothing."""
        public = {
            "metadata": {"identifier": "principlesofpsyc01jame"},
            "files": [
                {"name": "principlesofpsyc01jame_bw.pdf", "format": "Grayscale PDF"},
                {"name": "principlesofpsyc01jame.pdf", "format": "Text PDF"},
            ],
        }
        self.assertEqual(
            ia_public_pdf(public),
            "https://archive.org/download/principlesofpsyc01jame/principlesofpsyc01jame.pdf",
        )
        lending = {
            "metadata": {"identifier": "x", "access-restricted-item": "true"},
            "files": [{"name": "x.pdf", "format": "Text PDF"}],
        }
        self.assertIsNone(ia_public_pdf(lending))


class FakeBooks:
    """Book finder with a fixed answer."""

    def __init__(self, info: BookInfo | None) -> None:
        self.info = info
        self.calls: list[tuple[str, str]] = []

    def find(self, title: str, author: str) -> BookInfo | None:
        self.calls.append((title, author))
        return self.info


class FakeHttp:
    """HTTP fetcher answering from a URL → bytes map."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> bytes | None:
        return self.pages.get(url)


class NoOa:
    """Open-access finder that finds nothing."""

    def find_pdf_locations(self, doi: str) -> list:  # type: ignore[type-arg]
        return []


class BookFlowTest(unittest.TestCase):
    """Books in the download flow."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FilePdfStore(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_public_domain_book_is_downloaded_with_edition_note(self) -> None:
        """A public scan is saved; the outcome names the latest edition."""
        info = BookInfo(
            1950, "1950, Dover, ISBN 1", ("https://archive.org/x.pdf",), "https://openlibrary.org/works/W"
        )
        books = FakeBooks(info)
        sources = Sources(NoOa(), FakeHttp({"https://archive.org/x.pdf": PDF}), (), self.store, books=books)
        ref = Reference(
            "James_1890",
            "James",
            kind=ReferenceKind.BOOK,
            title="The principles of psychology",
            author="James",
        )
        [outcome] = download_all([ref], sources)
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)
        self.assertIn("latest edition: 1950, Dover", outcome.detail)
        self.assertEqual(books.calls, [("The principles of psychology", "James")])

    def test_copyrighted_book_is_listed_for_borrowing(self) -> None:
        """Without a free copy the book is manual, with the latest edition to look for."""
        info = BookInfo(2008, "2008, Harper, Rev. ed.", (), "https://openlibrary.org/works/W")
        sources = Sources(NoOa(), FakeHttp({}), (), self.store, books=FakeBooks(info))
        ref = Reference("Burns_1980", "Burns", kind=ReferenceKind.BOOK, title="Feeling good", author="Burns")
        [outcome] = download_all([ref], sources)
        self.assertEqual(outcome.status, DownloadStatus.MANUAL)
        self.assertIn("borrow", outcome.detail)
        self.assertIn("latest edition: 2008, Harper, Rev. ed.", outcome.detail)


if __name__ == "__main__":
    unittest.main()
