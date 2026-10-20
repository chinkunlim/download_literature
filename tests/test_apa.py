"""Offline tests for APA conversion: parsing, Crossref parsing, building and merging references."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.crossref import parse_crossref_work  # noqa: E402
from download_literature.adapters.literature.files import (  # noqa: E402
    find_reference_list,
    load_references,
    save_references,
)
from download_literature.domain.apa import parse_apa, split_entries  # noqa: E402
from download_literature.domain.literature import (  # noqa: E402
    ConversionNote,
    DownloadOutcome,
    DownloadStatus,
    Reference,
    ReferenceKind,
    SourceError,
    WorkMeta,
)
from download_literature.services.literature import render_report  # noqa: E402
from download_literature.services.reference_builder import (  # noqa: E402
    build_references,
    make_key,
    merge_with_existing,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _entries() -> list[str]:
    return split_entries((FIXTURES / "apa_list.md").read_text(encoding="utf-8"))


class SplitTest(unittest.TestCase):
    """Splitting a pasted reference list into entries."""

    def test_headings_bullets_and_wrapped_lines(self) -> None:
        """Headings are dropped, bullets removed and wrapped lines joined."""
        entries = _entries()
        self.assertEqual(len(entries), 7)
        self.assertTrue(entries[0].startswith("Beck, A. T. (1976)."))
        self.assertTrue(entries[2].endswith("2(3), 271–299."))

    def test_markdown_emphasis_and_links_are_removed(self) -> None:
        """Italics markers vanish; markdown links keep their URL."""
        entries = _entries()
        self.assertNotIn("*", entries[1])
        self.assertIn("Qualitative Research in Psychology, 3(2)", entries[1])
        self.assertTrue(entries[6].endswith("https://example.org/paper.pdf"))


class ParseTest(unittest.TestCase):
    """Parsing one APA 7 entry."""

    def setUp(self) -> None:
        self.entries = [parse_apa(e) for e in _entries()]

    def test_book(self) -> None:
        """A book without volume or DOI is recognised as a book."""
        beck = self.entries[0]
        self.assertEqual((beck.first_author, beck.year), ("Beck", 1976))
        self.assertEqual(beck.title, "Cognitive therapy and the emotional disorders")
        self.assertEqual(beck.kind_hint, ReferenceKind.BOOK)

    def test_journal_article_with_doi_url(self) -> None:
        """Title stops before the journal; the DOI URL is reduced to the DOI."""
        braun = self.entries[1]
        self.assertEqual(braun.title, "Using thematic analysis in psychology")
        self.assertEqual(braun.doi, "10.1191/1478088706qp063oa")
        self.assertEqual(braun.kind_hint, ReferenceKind.ARTICLE)
        self.assertEqual(braun.urls, ())

    def test_article_without_doi(self) -> None:
        """Volume / page numbers mark an article even without a DOI."""
        gross = self.entries[2]
        self.assertEqual(gross.title, "The emerging field of emotion regulation: An integrative review")
        self.assertEqual(gross.doi, "")
        self.assertEqual(gross.kind_hint, ReferenceKind.ARTICLE)

    def test_chapter_title_stops_before_in(self) -> None:
        """Editor initials after 'In' do not leak into the title."""
        kross = self.entries[3]
        self.assertEqual(kross.title, "Self-distancing: Theory, research, and current directions")
        self.assertEqual(kross.kind_hint, ReferenceKind.CHAPTER)

    def test_preprint_bracket_and_arxiv_id(self) -> None:
        """Bracketed descriptions are dropped and the arXiv id is found without its version."""
        he = self.entries[4]
        self.assertTrue(he.title.endswith("self-expression of mental distress"))
        self.assertEqual(he.arxiv_id, "2512.04087")

    def test_year_suffix_doi_prefix_and_hyphenated_author(self) -> None:
        """'2008b', 'doi:' prefix with trailing period and hyphenated surnames are handled."""
        nh = self.entries[5]
        self.assertEqual((nh.first_author, nh.year), ("Nolen-Hoeksema", 2008))
        self.assertEqual(nh.doi, "10.1111/j.1745-6924.2008.00088.x")

    def test_no_date_question_title_and_url(self) -> None:
        """'n.d.' gives no year; a question mark ends the title and is kept."""
        doe = self.entries[6]
        self.assertIsNone(doe.year)
        self.assertEqual(doe.title, "Is this a question?")
        self.assertEqual(doe.urls, ("https://example.org/paper.pdf",))

    def test_entry_without_year_is_rejected(self) -> None:
        """Text that is not an APA reference raises ValueError."""
        with self.assertRaises(ValueError):
            parse_apa("Just some note without a date")


class CrossrefParseTest(unittest.TestCase):
    """Parsing Crossref work records."""

    def test_search_items(self) -> None:
        """Title + subtitle are joined, HTML removed, types mapped, untitled items skipped."""
        items = json.loads((FIXTURES / "crossref_search.json").read_text(encoding="utf-8"))["message"][
            "items"
        ]
        works = [parse_crossref_work(i) for i in items]
        self.assertEqual(
            works[0],
            WorkMeta(
                "10.1037/1089-2680.2.3.271",
                "The Emerging Field of Emotion Regulation: An Integrative Review",
                1998,
                ReferenceKind.ARTICLE,
                "Gross",
            ),
        )
        assert works[1] is not None
        self.assertEqual(works[1].title, "Self-Distancing: Theory, Research, and Current Directions")
        self.assertEqual(works[1].kind, ReferenceKind.CHAPTER)
        self.assertIsNone(works[2])

    def test_non_publication_records_are_skipped(self) -> None:
        """Datasets, peer reviews and similar Crossref records are not treated as the cited work."""
        item = {"DOI": "10.3410/f.1", "type": "dataset", "title": ["Faculty Opinions recommendation of X"]}
        self.assertIsNone(parse_crossref_work(item))


class FakeResolver:
    """Resolver answering from fixed tables."""

    def __init__(self, by_doi: dict[str, WorkMeta], search: dict[str, list[WorkMeta]]) -> None:
        self.dois = by_doi
        self.searches = search

    def by_doi(self, doi: str) -> WorkMeta | None:
        if doi == "10.9999/boom":
            raise SourceError("down")
        return self.dois.get(doi)

    def search(self, citation: str) -> list[WorkMeta]:
        for needle, works in self.searches.items():
            if needle in citation:
                return works
        return []


GROSS = WorkMeta(
    "10.1037/1089-2680.2.3.271",
    "The Emerging Field of Emotion Regulation: An Integrative Review",
    1998,
    ReferenceKind.ARTICLE,
    "Gross",
)


class BuildTest(unittest.TestCase):
    """Turning APA entries into References with Crossref confirmation."""

    def test_missing_doi_is_found_by_search(self) -> None:
        """A matching search hit (title and year) supplies the DOI and Crossref's title."""
        refs, notes = build_references([_entries()[2]], FakeResolver({}, {"Gross": [GROSS]}))
        self.assertEqual(refs[0].doi, GROSS.doi)
        self.assertEqual(refs[0].title, GROSS.title)
        self.assertEqual(refs[0].key, "Gross_1998_EmergingField")
        self.assertEqual(notes, [])

    def test_book_review_hit_is_not_taken_for_a_book(self) -> None:
        """A journal article with the book's title (e.g. a review) does not turn a book into an article."""
        review = WorkMeta(
            "10.1/review",
            "Cognitive therapy and the emotional disorders",
            1977,
            ReferenceKind.ARTICLE,
            "Smith",
        )
        refs, _ = build_references([_entries()[0]], FakeResolver({}, {"Beck": [review]}))
        self.assertEqual(refs[0].kind, ReferenceKind.BOOK)
        self.assertEqual(refs[0].doi, "")

    def test_wrong_search_hit_is_rejected_with_note(self) -> None:
        """A hit with a different title is ignored and the entry is flagged."""
        other = WorkMeta(
            "10.1/x", "Something else entirely about emotions", 1998, ReferenceKind.ARTICLE, "Gross"
        )
        refs, notes = build_references([_entries()[2]], FakeResolver({}, {"Gross": [other]}))
        self.assertEqual(refs[0].doi, "")
        self.assertIn("no DOI found", notes[0].message)

    def test_hit_by_another_first_author_is_rejected(self) -> None:
        """A commentary whose title quotes the paper (other first author) is not accepted."""
        entry = (
            "Lieberman, M. D. (2007). Putting feelings into words: Affect labeling disrupts "
            "amygdala activity in response to affective stimuli. Psychological Science, 18(5), 421–428."
        )
        opinion = WorkMeta(
            "10.3410/f.1",
            "Faculty Opinions recommendation of Putting feelings into words: Affect "
            "labeling disrupts amygdala activity in response to affective stimuli",
            2007,
            ReferenceKind.ARTICLE,
            "Berridge",
        )
        real = WorkMeta(
            "10.1111/j.1467-9280.2007.01916.x",
            "Putting Feelings Into Words",
            2007,
            ReferenceKind.ARTICLE,
            "Lieberman",
        )
        real_full = WorkMeta(
            real.doi,
            "Putting Feelings Into Words: Affect Labeling Disrupts Amygdala Activity in "
            "Response to Affective Stimuli",
            2007,
            ReferenceKind.ARTICLE,
            "Lieberman",
        )
        refs, _ = build_references([entry], FakeResolver({}, {"Lieberman": [opinion, real_full]}))
        self.assertEqual(refs[0].doi, real.doi)

    def test_short_crossref_title_is_accepted_when_author_and_year_match(self) -> None:
        """Crossref may store only the main title; it is accepted when author and year agree."""
        entry = (
            "Lieberman, M. D. (2007). Putting feelings into words: Affect labeling disrupts amygdala. "
            "P, 18(5), 1–2."
        )
        short = WorkMeta(
            "10.1111/j.1467-9280.2007.01916.x",
            "Putting Feelings Into Words",
            2007,
            ReferenceKind.ARTICLE,
            "Lieberman",
        )
        other_author = WorkMeta(
            "10.1/other", "Putting Feelings Into Words", 2007, ReferenceKind.ARTICLE, "Smith"
        )
        refs, notes = build_references([entry], FakeResolver({}, {"Lieberman": [other_author, short]}))
        self.assertEqual(refs[0].doi, short.doi)
        self.assertEqual(refs[0].title, "Putting feelings into words: Affect labeling disrupts amygdala")
        self.assertEqual(notes, [])

    def test_given_doi_is_confirmed_and_kind_taken_from_crossref(self) -> None:
        """A DOI in the citation is looked up; Crossref's type wins over the guess."""
        chapter = WorkMeta(
            "10.1016/bs.aesp.2016.10.002", "Self-Distancing", 2017, ReferenceKind.CHAPTER, "Kross"
        )
        refs, notes = build_references([_entries()[3]], FakeResolver({chapter.doi: chapter}, {}))
        self.assertEqual(refs[0].kind, ReferenceKind.CHAPTER)
        self.assertEqual(refs[0].title, "Self-distancing: Theory, research, and current directions")
        self.assertEqual(notes, [])

    def test_unknown_doi_and_lookup_errors_are_noted(self) -> None:
        """Unknown DOIs and failing lookups keep the parsed data and add a note."""
        entry = _entries()[1]
        refs, notes = build_references(
            [entry, entry.replace("10.1191/1478088706qp063oa", "10.9999/boom")], FakeResolver({}, {})
        )
        self.assertEqual(refs[0].doi, "10.1191/1478088706qp063oa")
        self.assertIn("not found on Crossref", notes[0].message)
        self.assertIn("lookup failed", notes[1].message)

    def test_unparsable_entries_are_skipped_with_note(self) -> None:
        """Lines without a year become notes, not references."""
        refs, notes = build_references(["Appendix A"], FakeResolver({}, {}))
        self.assertEqual(refs, [])
        self.assertIn("could not parse", notes[0].message)

    def test_keys_are_unique_and_ascii(self) -> None:
        """Same author/year/title start gets a suffix; accents are folded to ASCII."""
        taken: set[str] = set()
        first = make_key("Tóth-Király", 2021, "The development of a scale", taken)
        second = make_key("Tóth-Király", 2021, "The development of another scale", taken)
        self.assertEqual(first, "Toth-Kiraly_2021_DevelopmentScale")
        self.assertEqual(second, "Toth-Kiraly_2021_DevelopmentAnother")
        third = make_key("Tóth-Király", 2021, "The development of a scale", taken)
        self.assertEqual(third, "Toth-Kiraly_2021_DevelopmentScale_b")


class MergeTest(unittest.TestCase):
    """Keeping keys and manual additions when a list is converted again."""

    def test_existing_key_urls_and_kind_are_kept(self) -> None:
        """A matching old entry (same DOI) keeps key, URLs and kind; order follows the new list."""
        old = [
            Reference(
                "Braun_2006_QRP",
                "old",
                doi="10.1191/1478088706QP063OA",
                pdf_urls=("https://repo/braun.pdf",),
                title="Using thematic analysis in psychology",
            ),
            Reference("Dropped_2000", "gone", doi="10.1/gone"),
        ]
        new = [
            Reference("Gross_1998_EmergingField", "Gross", doi="10.1037/x", title="T"),
            Reference(
                "Braun_2006_UsingThematic",
                "Braun new",
                doi="10.1191/1478088706qp063oa",
                pdf_urls=("https://new/url",),
                title="Using thematic analysis in psychology",
            ),
        ]
        merged = merge_with_existing(new, old)
        self.assertEqual([r.key for r in merged], ["Gross_1998_EmergingField", "Braun_2006_QRP"])
        self.assertEqual(merged[1].pdf_urls, ("https://repo/braun.pdf", "https://new/url"))
        self.assertEqual(merged[1].citation, "Braun new")

    def test_match_by_title_when_no_doi(self) -> None:
        """Books without DOI match on title."""
        old = [
            Reference(
                "Beck_1976_book",
                "old",
                kind=ReferenceKind.BOOK,
                title="Cognitive therapy and the emotional disorders",
            )
        ]
        new = [
            Reference(
                "Beck_1976_CognitiveTherapy",
                "new",
                kind=ReferenceKind.BOOK,
                title="Cognitive Therapy and the Emotional Disorders",
            )
        ]
        self.assertEqual(merge_with_existing(new, old)[0].key, "Beck_1976_book")


class SaveTest(unittest.TestCase):
    """Writing the reference JSON."""

    def test_round_trip(self) -> None:
        """Saved references load back unchanged; empty fields are omitted from the file."""
        refs = [
            Reference("A_2020_X", "A (2020)", doi="10.1/a", title="X", pdf_urls=("https://u",)),
            Reference("B_1990_Y", "B (1990)", kind=ReferenceKind.BOOK, title="Y"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refs.json"
            save_references(path, refs)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("doi", raw[1])
            self.assertEqual(load_references(path), refs)


class InputAndReportTest(unittest.TestCase):
    """Picking the input file and reporting conversion notes."""

    def test_text_list_is_preferred_over_json(self) -> None:
        """references.txt / .md win over references.json; nothing found gives None."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertIsNone(find_reference_list(folder))
            (folder / "references.json").write_text("[]", encoding="utf-8")
            self.assertEqual(find_reference_list(folder), folder / "references.json")
            (folder / "references.md").write_text("x", encoding="utf-8")
            self.assertEqual(find_reference_list(folder), folder / "references.md")
            (folder / "references.txt").write_text("x", encoding="utf-8")
            self.assertEqual(find_reference_list(folder), folder / "references.txt")

    def test_report_lists_conversion_notes(self) -> None:
        """Notes appear in their own section after the download table."""
        outcome = DownloadOutcome(Reference("A", "A (2020)"), DownloadStatus.FAILED, detail="x")
        report = render_report([outcome], [ConversionNote("Gross (1998) ...", "no DOI found")])
        self.assertIn("## Check these citations", report)
        self.assertIn("| Gross (1998) ... | no DOI found |", report)
        self.assertNotIn("## Check these citations", render_report([outcome]))


if __name__ == "__main__":
    unittest.main()
