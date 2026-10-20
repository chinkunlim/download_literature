"""Offline tests for APA 7 formatting and the richer Crossref / OpenAlex metadata it needs."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.crossref import parse_crossref_work  # noqa: E402
from download_literature.adapters.literature.openalex import parse_openalex_work  # noqa: E402
from download_literature.domain.apa_format import format_apa, format_authors, sentence_case  # noqa: E402
from download_literature.domain.literature import ReferenceKind, WorkMeta  # noqa: E402

WEBB = WorkMeta(
    "10.1037/a0027600",
    "Dealing With Feeling: A Meta-Analysis of the Effectiveness of Strategies Derived From the Process Model "
    "of Emotion Regulation",
    2012,
    ReferenceKind.ARTICLE,
    "Webb",
    authors=(("Webb", "Thomas L."), ("Miles", "Eleanor"), ("Sheeran", "Paschal")),
    container="Psychological Bulletin",
    volume="138",
    issue="4",
    pages="775-808",
    genre="journal-article",
)


class AuthorsTest(unittest.TestCase):
    """APA author lists."""

    def test_initials_hyphens_and_ampersand(self) -> None:
        """Given names become initials (hyphenated kept); the last author follows ', &'."""
        authors = (("Li", "Han"), ("Lee", "Yu-Chen"), ("Kraut", "Robert E."))
        self.assertEqual(format_authors(authors), "Li, H., Lee, Y.-C., & Kraut, R. E.")

    def test_single_two_and_group_authors(self) -> None:
        """One author stands alone; two use ', &'; a group author keeps its name."""
        self.assertEqual(format_authors((("Gross", "James J."),)), "Gross, J. J.")
        self.assertEqual(
            format_authors((("Braun", "Virginia"), ("Clarke", "Victoria"))), "Braun, V., & Clarke, V."
        )
        self.assertEqual(format_authors((("World Health Organization", ""),)), "World Health Organization")

    def test_more_than_twenty_authors(self) -> None:
        """21+ authors: first 19, an ellipsis, then the last author."""
        authors = tuple((f"Name{i}", "A.") for i in range(1, 23))
        text = format_authors(authors)
        self.assertTrue(text.startswith("Name1, A., Name2, A.,"))
        self.assertIn("Name19, A., . . . Name22, A.", text)
        self.assertNotIn("Name20", text)


class SentenceCaseTest(unittest.TestCase):
    """Title case → APA sentence case."""

    def test_keeps_acronyms_and_capitalises_after_colon(self) -> None:
        """Acronyms, mixed-case names and numbers stay; the word after a colon is capitalised."""
        self.assertEqual(
            sentence_case("Your Brain on ChatGPT: Accumulation of Cognitive Debt When Using an AI Assistant"),
            "Your brain on ChatGPT: Accumulation of cognitive debt when using an AI assistant",
        )
        self.assertEqual(
            sentence_case("Self-Distancing: Theory, Research, and Current Directions"),
            "Self-distancing: Theory, research, and current directions",
        )
        self.assertEqual(
            sentence_case("Online Interventions During COVID-19"), "Online interventions during COVID-19"
        )


class FormatTest(unittest.TestCase):
    """Whole APA 7 references."""

    def test_journal_article(self) -> None:
        """Journal and volume in italics, issue in parentheses, en dash pages, DOI as URL."""
        self.assertEqual(
            format_apa(WEBB),
            "Webb, T. L., Miles, E., & Sheeran, P. (2012). Dealing with feeling: A meta-analysis of the "
            "effectiveness of strategies derived from the process model of emotion regulation. "
            "*Psychological Bulletin, 138*(4), 775–808. https://doi.org/10.1037/a0027600",
        )

    def test_title_override_keeps_user_casing(self) -> None:
        """A title written by the user (already APA cased) is used as-is."""
        text = format_apa(WEBB, title="Dealing with feeling: A meta-analysis of the Process Model")
        self.assertIn("(2012). Dealing with feeling: A meta-analysis of the Process Model. *Psych", text)

    def test_article_number(self) -> None:
        """Article numbers are written as 'Article N'."""
        meta = WorkMeta(
            "10.3389/fpsyt.2016.00215",
            "Serious Games",
            2017,
            ReferenceKind.ARTICLE,
            "Fleming",
            authors=(("Fleming", "Theresa M."),),
            container="Frontiers in Psychiatry",
            volume="7",
            article_number="215",
            genre="journal-article",
        )
        self.assertIn("*Frontiers in Psychiatry, 7*, Article 215. https://doi.org", format_apa(meta))

    def test_book(self) -> None:
        """Book titles are italic; the publisher follows; edition is shown when known."""
        meta = WorkMeta(
            "",
            "Feeling Good: The New Mood Therapy",
            1980,
            ReferenceKind.BOOK,
            "Burns",
            authors=(("Burns", "David D."),),
            publisher="Morrow",
            genre="book",
        )
        self.assertEqual(
            format_apa(meta), "Burns, D. D. (1980). *Feeling good: The new mood therapy*. Morrow."
        )
        later = WorkMeta(
            "",
            "Feeling Good",
            1999,
            ReferenceKind.BOOK,
            "Burns",
            authors=(("Burns", "David D."),),
            publisher="Avon",
            edition="Rev. ed.",
            genre="book",
        )
        self.assertEqual(format_apa(later), "Burns, D. D. (1999). *Feeling good* (Rev. ed.). Avon.")

    def test_chapter(self) -> None:
        """Chapters: 'In *Book* (Vol. n, pp. x–y). Publisher.'"""
        meta = WorkMeta(
            "10.1016/bs.aesp.2016.10.002",
            "Self-Distancing",
            2017,
            ReferenceKind.CHAPTER,
            "Kross",
            authors=(("Kross", "Ethan"), ("Ayduk", "Ozlem")),
            container="Advances in Experimental Social Psychology",
            volume="55",
            pages="81-136",
            publisher="Elsevier",
            genre="book-chapter",
        )
        self.assertEqual(
            format_apa(meta, title="Self-distancing: Theory, research, and current directions"),
            "Kross, E., & Ayduk, O. (2017). Self-distancing: Theory, research, and current directions. "
            "In *Advances in experimental social psychology* (Vol. 55, pp. 81–136). Elsevier. "
            "https://doi.org/10.1016/bs.aesp.2016.10.002",
        )

    def test_conference_paper(self) -> None:
        """Proceedings keep their name's capitalisation."""
        meta = WorkMeta(
            "10.1145/3613904.3642761",
            "Facilitating Self-Guided Mental Health Interventions",
            2024,
            ReferenceKind.ARTICLE,
            "Sharma",
            authors=(("Sharma", "Ashish"),),
            container="Proceedings of the CHI Conference on Human Factors in Computing Systems",
            pages="1-29",
            publisher="ACM",
            genre="proceedings-article",
        )
        self.assertIn(
            "In *Proceedings of the CHI Conference on Human Factors in Computing Systems* (pp. 1–29). ACM. "
            "https://doi.org/10.1145/3613904.3642761",
            format_apa(meta),
        )

    def test_preprint(self) -> None:
        """Preprints: italic title, [Preprint], repository name, DOI."""
        meta = WorkMeta(
            "10.48550/arxiv.2506.08872",
            "Your Brain on ChatGPT",
            2025,
            ReferenceKind.ARTICLE,
            "Kosmyna",
            authors=(("Kosmyna", "Nataliya"),),
            container="arXiv",
            genre="preprint",
        )
        self.assertEqual(
            format_apa(meta),
            "Kosmyna, N. (2025). *Your brain on ChatGPT* [Preprint]. arXiv. https://doi.org/10.48550/arxiv.2506.08872",
        )

    def test_missing_year(self) -> None:
        """Unknown year is written as n.d."""
        meta = WorkMeta("", "Report", None, ReferenceKind.BOOK, "Org", authors=(("Org", ""),), genre="book")
        self.assertTrue(format_apa(meta).startswith("Org. (n.d.)."))


class MetadataParseTest(unittest.TestCase):
    """Crossref and OpenAlex records carry what APA needs."""

    def test_crossref_full_record(self) -> None:
        """Authors, container, volume, issue, pages, article number, publisher and type are read."""
        item = {
            "DOI": "10.3389/fpsyt.2016.00215",
            "type": "journal-article",
            "title": ["Serious Games"],
            "author": [{"family": "Fleming", "given": "Theresa M."}, {"name": "The Study Group"}],
            "container-title": ["Frontiers in Psychiatry"],
            "volume": "7",
            "page": "215",
            "article-number": "215",
            "publisher": "Frontiers Media SA",
            "issued": {"date-parts": [[2017, 1]]},
        }
        work = parse_crossref_work(item)
        assert work is not None
        self.assertEqual(work.authors, (("Fleming", "Theresa M."), ("The Study Group", "")))
        self.assertEqual(
            (work.container, work.volume, work.article_number), ("Frontiers in Psychiatry", "7", "215")
        )
        self.assertEqual(work.genre, "journal-article")

    def test_openalex_preprint(self) -> None:
        """An OpenAlex arXiv record becomes a preprint with split author names."""
        work = parse_openalex_work(
            {
                "doi": "https://doi.org/10.48550/arxiv.2506.08872",
                "display_name": "Your Brain on ChatGPT: Accumulation of Cognitive Debt",
                "publication_year": 2025,
                "type": "preprint",
                "authorships": [
                    {"author": {"display_name": "Nataliya Kosmyna"}},
                    {"author": {"display_name": "Eugene Hauptmann"}},
                ],
                "primary_location": {"source": {"display_name": "arXiv (Cornell University)"}},
                "biblio": {"volume": None, "issue": None, "first_page": None, "last_page": None},
            }
        )
        assert work is not None
        self.assertEqual(work.doi, "10.48550/arxiv.2506.08872")
        self.assertEqual(work.authors, (("Kosmyna", "Nataliya"), ("Hauptmann", "Eugene")))
        self.assertEqual((work.genre, work.container), ("preprint", "arXiv"))


if __name__ == "__main__":
    unittest.main()
