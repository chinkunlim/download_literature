"""Offline tests for Chinese references: title matching, APA parsing / formatting, keys and file names."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.domain.apa import parse_apa  # noqa: E402
from download_literature.domain.apa_format import format_apa  # noqa: E402
from download_literature.domain.literature import ReferenceKind, WorkMeta, safe_filename, title_matches  # noqa: E402
from download_literature.services.reference_builder import make_key, match_free_text  # noqa: E402

LINE = (
    "張歆祐、陳怡婷、陳怡樺（2022）。台灣低憂鬱孕產婦正向心理因素初探。中華心理衛生學刊，35(4)，319–346。"
    "https://doi.org/10.30074/FJMH.202212_35(4).0001"
)
META = WorkMeta(
    "10.30074/FJMH.202212_35(4).0001",
    "台灣低憂鬱孕產婦正向心理因素初探",
    2022,
    ReferenceKind.ARTICLE,
    "張歆祐",
    authors=(("張歆祐", ""), ("陳怡婷", ""), ("陳怡樺", "")),
    container="中華心理衛生學刊",
    volume="35",
    issue="4",
    pages="319-346",
    genre="journal-article",
)


class TitleMatchTest(unittest.TestCase):
    """Chinese titles are compared by character pairs."""

    def test_same_and_different_titles(self) -> None:
        """The same Chinese title matches (spacing ignored); another title does not."""
        self.assertTrue(
            title_matches(
                "台灣低憂鬱孕產婦正向心理因素初探", "中華心理衛生學刊\n台灣低憂鬱 孕產婦正向\n心理因素初探"
            )
        )
        self.assertFalse(
            title_matches("台灣低憂鬱孕產婦正向心理因素初探", "運用正念認知治療減少慢性精神病人家庭衝突")
        )


class ParseTest(unittest.TestCase):
    """Chinese APA with full-width punctuation."""

    def test_parse_chinese_apa(self) -> None:
        """Authors split on '、', full-width year, title ends at '。', DOI found."""
        entry = parse_apa(LINE)
        self.assertEqual((entry.first_author, entry.year), ("張歆祐", 2022))
        self.assertEqual(entry.title, "台灣低憂鬱孕產婦正向心理因素初探")
        self.assertEqual(entry.doi, "10.30074/FJMH.202212_35(4).0001")
        self.assertEqual(entry.kind_hint, ReferenceKind.ARTICLE)


class FormatTest(unittest.TestCase):
    """Chinese APA 7 output."""

    def test_chinese_article(self) -> None:
        """Names joined with '、', full-width brackets and punctuation, italic journal and volume."""
        self.assertEqual(
            format_apa(META),
            "張歆祐、陳怡婷、陳怡樺（2022）。台灣低憂鬱孕產婦正向心理因素初探。*中華心理衛生學刊，35*(4)，319–346。"
            "https://doi.org/10.30074/FJMH.202212_35(4).0001",
        )


class KeyTest(unittest.TestCase):
    """Keys and file names keep Chinese characters."""

    def test_key_and_filename(self) -> None:
        """Key = author_year_first characters of the title; file names keep CJK."""
        self.assertEqual(
            make_key("張歆祐", 2022, "台灣低憂鬱孕產婦正向心理因素初探", set()), "張歆祐_2022_台灣低憂鬱孕產"
        )
        self.assertEqual(safe_filename("張歆祐_2022_台灣低憂鬱孕產"), "張歆祐_2022_台灣低憂鬱孕產")
        self.assertEqual(safe_filename("A/B: c?"), "A_B_c")


class FreeTextTest(unittest.TestCase):
    """Chinese title-only input."""

    def test_title_and_author_title(self) -> None:
        """A full Chinese title matches; author + partial title matches; partial title alone does not."""
        other = WorkMeta(
            "10.1/o",
            "運用正念認知治療減少慢性精神病人家庭衝突情境的成效",
            2026,
            ReferenceKind.ARTICLE,
            "李秀如",
            authors=(("李秀如", ""),),
        )
        self.assertEqual(match_free_text("台灣低憂鬱孕產婦正向心理因素初探", [other, META]), META)
        self.assertEqual(match_free_text("張歆祐 台灣低憂鬱孕產婦", [other, META]), META)
        self.assertIsNone(match_free_text("台灣低憂鬱孕產婦", [other, META]))


class GarbledTextTest(unittest.TestCase):
    """Chinese PDFs whose text layer cannot be decoded."""

    def test_unreadable_chinese_text_is_accepted(self) -> None:
        """A Chinese title with a PDF text layer that has no Chinese characters is not rejected."""
        import tempfile

        from download_literature.adapters.literature.files import FilePdfStore
        from download_literature.domain.literature import DownloadStatus, Reference
        from download_literature.services.literature import Sources, download_all

        pdf = b"%PDF-1.4 garbled"

        class Text:
            def first_pages_text(self, data: bytes) -> str:
                return "77\nΫᚥ̨ᝄ͍ ؈ׂࣖӺၾᑗґ ᏐͰjྼᗇ"

        class Route:
            def fetch_pdf(self, reference: Reference) -> tuple[bytes, str]:
                return pdf, "https://www.airitilibrary.com/Article/Detail/x"

        class NoOa:
            def find_pdf_locations(self, doi: str) -> list:  # type: ignore[type-arg]
                return []

        class NoHttp:
            def fetch(self, url: str) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            sources = Sources(NoOa(), NoHttp(), (Route(),), FilePdfStore(Path(tmp)), Text())
            ref = Reference("K", "k", doi="10.3966/x", title="回顧台灣正念效果研究與臨床應用")
            [outcome] = download_all([ref], sources)
        self.assertEqual(outcome.status, DownloadStatus.DOWNLOADED)


if __name__ == "__main__":
    unittest.main()
