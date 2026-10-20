"""Offline tests for resolving title-only / author+title inputs and for the combined metadata resolver."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.metadata import CombinedResolver  # noqa: E402
from download_literature.domain.literature import ReferenceKind, SourceError, WorkMeta  # noqa: E402
from download_literature.services.reference_builder import match_free_text, resolve_entry  # noqa: E402

BRAIN = WorkMeta(
    "10.48550/arxiv.2506.08872",
    "Your Brain on ChatGPT: Accumulation of Cognitive Debt when Using an AI Assistant for Essay Writing Task",
    2025,
    ReferenceKind.ARTICLE,
    "Kosmyna",
    authors=(("Kosmyna", "Nataliya"), ("Hauptmann", "Eugene")),
    container="arXiv",
    genre="preprint",
)
OTHER = WorkMeta(
    "10.1/other",
    "Your Brain on Chocolate",
    2019,
    ReferenceKind.ARTICLE,
    "Smith",
    authors=(("Smith", "Ann"),),
    container="Food Journal",
    genre="journal-article",
)


class FakeResolver:
    """Resolver with fixed answers."""

    def __init__(self, by_doi: dict[str, WorkMeta], hits: list[WorkMeta], fail: bool = False) -> None:
        self.dois, self.hits, self.fail = by_doi, hits, fail

    def by_doi(self, doi: str) -> WorkMeta | None:
        if self.fail:
            raise SourceError("down")
        return self.dois.get(doi)

    def search(self, citation: str) -> list[WorkMeta]:
        if self.fail:
            raise SourceError("down")
        return list(self.hits)


class MatchTest(unittest.TestCase):
    """Choosing the cited work for free text."""

    def test_full_title_only(self) -> None:
        """A full title matches even when another result shares a few words."""
        line = "Your Brain on ChatGPT: Accumulation of Cognitive Debt when Using an AI Assistant for Essays"
        self.assertEqual(match_free_text(line, [OTHER, BRAIN]), BRAIN)

    def test_author_and_partial_title(self) -> None:
        """'Author — short title' matches when the author is on the record."""
        self.assertEqual(match_free_text("Kosmyna — Your Brain on ChatGPT", [OTHER, BRAIN]), BRAIN)

    def test_partial_title_without_author_is_not_enough(self) -> None:
        """A few title words without an author are too weak to trust."""
        self.assertIsNone(match_free_text("Your Brain on ChatGPT", [OTHER, BRAIN]))

    def test_short_record_title_with_author_and_year(self) -> None:
        """A main-title-only record matches when author and year confirm it; years are not title words."""
        short = WorkMeta(
            "10.1016/bs.aesp.2016.10.002",
            "Self-Distancing",
            2017,
            ReferenceKind.CHAPTER,
            "Kross",
            authors=(("Kross", "Ethan"), ("Ayduk", "Ozlem")),
            genre="book-chapter",
        )
        line = "Kross & Ayduk 2017 self-distancing theory research current directions"
        self.assertEqual(match_free_text(line, [OTHER, short]), short)
        self.assertIsNone(match_free_text("Self-distancing theory research current directions", [short]))

    def test_year_must_agree(self) -> None:
        """A year in the input rules out records from other years."""
        self.assertIsNone(match_free_text("Kosmyna (2019) Your Brain on ChatGPT", [BRAIN]))


class ResolveEntryTest(unittest.TestCase):
    """One input line → reference + APA text."""

    def test_free_text_gets_apa_and_check_note(self) -> None:
        """Title-only input is resolved by search, formatted in APA 7 and flagged for a quick check."""
        res = resolve_entry("Kosmyna, Your Brain on ChatGPT", FakeResolver({}, [BRAIN]), set())
        assert res.reference is not None
        self.assertEqual(res.reference.doi, BRAIN.doi)
        self.assertEqual(res.reference.key, "Kosmyna_2025_BrainChatgpt")
        self.assertTrue(res.apa.startswith("Kosmyna, N., & Hauptmann, E. (2025). *Your brain on ChatGPT"))
        self.assertIn("title search", res.note)

    def test_apa_input_keeps_user_title_casing(self) -> None:
        """For an APA input confirmed by DOI the APA text uses the user's title."""
        line = (
            "Webb, T. L., Miles, E., & Sheeran, P. (2012). Dealing with feeling: A meta-analysis of the "
            "Process Model. Psychological Bulletin, 138(4), 775–808. https://doi.org/10.1037/a0027600"
        )
        meta = WorkMeta(
            "10.1037/a0027600",
            "Dealing With Feeling: A Meta-Analysis of the Process Model",
            2012,
            ReferenceKind.ARTICLE,
            "Webb",
            authors=(("Webb", "Thomas L."),),
            container="Psychological Bulletin",
            volume="138",
            issue="4",
            pages="775-808",
            genre="journal-article",
        )
        res = resolve_entry(line, FakeResolver({meta.doi: meta}, []), set())
        self.assertIn("(2012). Dealing with feeling: A meta-analysis of the Process Model. *Psych", res.apa)
        self.assertEqual(res.note, "")

    def test_unresolved_free_text(self) -> None:
        """Nothing found: no reference, the input is kept and a note explains it."""
        res = resolve_entry("Some unknown working paper", FakeResolver({}, [OTHER]), set())
        self.assertIsNone(res.reference)
        self.assertIn("not found", res.note)


class CombinedResolverTest(unittest.TestCase):
    """Crossref first, OpenAlex as fallback."""

    def test_doi_falls_back_to_second_resolver(self) -> None:
        """DataCite DOIs (arXiv) unknown to Crossref come from OpenAlex."""
        combined = CombinedResolver([FakeResolver({}, []), FakeResolver({BRAIN.doi: BRAIN}, [])])
        self.assertEqual(combined.by_doi(BRAIN.doi), BRAIN)

    def test_search_merges_results_and_survives_one_failure(self) -> None:
        """Results are concatenated without duplicate DOIs; one failing service does not stop the other."""
        combined = CombinedResolver(
            [FakeResolver({}, [], fail=True), FakeResolver({}, [BRAIN, BRAIN, OTHER])]
        )
        self.assertEqual(combined.search("x"), [BRAIN, OTHER])

    def test_all_failing_raises(self) -> None:
        """When every service fails the error is reported."""
        with self.assertRaises(SourceError):
            CombinedResolver([FakeResolver({}, [], fail=True)]).search("x")


if __name__ == "__main__":
    unittest.main()
