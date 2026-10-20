"""Offline tests for the Airiti (華藝) adapter's parsers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.airiti import (  # noqa: E402
    detail_url,
    is_airiti_doi,
    parse_airiti_meta,
    parse_result_links,
    search_query,
    volume_issue_from_text,
)
from download_literature.domain.literature import ReferenceKind  # noqa: E402

ONCLICK = (
    "_文章書目_點擊篇名('10237283-N202301030031-00001', '927A7A2FC925FEF7FFEA86EC87F49222', "
    "'%e5%8f%b0', 'false', '', 'P001');"
)


class AiritiParseTest(unittest.TestCase):
    """Search results and article metadata."""

    def test_result_links(self) -> None:
        """Titles and DocIDs come from the title links' onclick handlers; other links are ignored."""
        found = parse_result_links(
            [("台灣低憂鬱孕產婦正向心理因素初探", ONCLICK), ("Download", ""), ("x", "other()")]
        )
        self.assertEqual(found, [("台灣低憂鬱孕產婦正向心理因素初探", "10237283-N202301030031-00001")])

    def test_article_metadata(self) -> None:
        """citation_* tags become a WorkMeta with the article page as its URL."""
        meta = {
            "citation_title": ["台灣低憂鬱孕產婦正向心理因素初探"],
            "citation_author": ["張歆祐", "陳怡婷"],
            "citation_journal_title": ["中華心理衛生學刊"],
            "citation_date": ["2022/12/01"],
            "citation_volume": ["35"],
            "citation_issue": ["4"],
            "citation_firstpage": ["319"],
            "citation_lastpage": ["346"],
            "citation_doi": ["10.30074/FJMH.202212_35(4).0001"],
            "citation_publisher": ["社團法人中華心理衛生協會"],
            "citation_abstract_html_url": [
                "https://www.airitilibrary.com/Article/Detail/10237283-N2023-00001"
            ],
        }
        work = parse_airiti_meta(meta)
        assert work is not None
        self.assertEqual(
            (work.title, work.year, work.kind, work.first_author),
            ("台灣低憂鬱孕產婦正向心理因素初探", 2022, ReferenceKind.ARTICLE, "張歆祐"),
        )
        self.assertEqual(work.authors, (("張歆祐", ""), ("陳怡婷", "")))
        self.assertEqual(
            (work.container, work.volume, work.issue, work.pages), ("中華心理衛生學刊", "35", "4", "319-346")
        )
        self.assertEqual(work.doi, "10.30074/FJMH.202212_35(4).0001")
        self.assertEqual(work.url, "https://www.airitilibrary.com/Article/Detail/10237283-N2023-00001")
        self.assertIsNone(parse_airiti_meta({}))

    def test_helpers(self) -> None:
        """Article URLs and Airiti-registered DOIs are recognised."""
        self.assertEqual(detail_url("ABC-1"), "https://www.airitilibrary.com/Article/Detail/ABC-1")
        self.assertTrue(is_airiti_doi("10.30074/FJMH.202212_35(4).0001"))
        self.assertTrue(is_airiti_doi("10.6129/CJP.20190101"))
        self.assertFalse(is_airiti_doi("10.1037/a0027600"))


class AiritiTextTest(unittest.TestCase):
    """Volume / issue from page text and the search query."""

    def test_volume_issue_from_page_text(self) -> None:
        """Chinese and English page labels give volume and issue; issue-only journals give the issue."""
        self.assertEqual(volume_issue_from_text("《中華心理衛生學刊》 35卷4期 (2022 / 12)"), ("35", "4"))
        self.assertEqual(volume_issue_from_text("《應用心理研究》 70期 (2019 / 06) Pp. 77-121"), ("", "70"))
        self.assertEqual(volume_issue_from_text("Journal Volume 35 Issue 4 (2022/12)"), ("35", "4"))
        self.assertEqual(volume_issue_from_text("no numbers"), ("", ""))

    def test_issue_zero_is_empty(self) -> None:
        """Airiti writes issue 0 when it has no issue number."""
        work = parse_airiti_meta({"citation_title": ["T"], "citation_issue": ["0"], "citation_volume": [""]})
        assert work is not None
        self.assertEqual((work.volume, work.issue), ("", ""))

    def test_search_query_uses_the_title(self) -> None:
        """A full APA citation is searched by its title; other text as written."""
        line = "張歆祐、陳怡婷（2022）。台灣低憂鬱孕產婦正向心理因素初探。中華心理衛生學刊，35(4)，319–346。"
        self.assertEqual(search_query(line), "台灣低憂鬱孕產婦正向心理因素初探")
        self.assertEqual(search_query("回顧台灣正念效果研究"), "回顧台灣正念效果研究")


if __name__ == "__main__":
    unittest.main()
