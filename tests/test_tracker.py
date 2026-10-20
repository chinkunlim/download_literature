"""Offline tests for the Markdown reference tracker: edits, rendering, selection and status updates."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.files import load_items, save_items  # noqa: E402
from download_literature.adapters.literature.tracker_md import parse_tracker_md, render_tracker_md  # noqa: E402
from download_literature.domain.literature import DownloadOutcome, DownloadStatus, Reference, ReferenceKind  # noqa: E402
from download_literature.domain.tracker import ItemStatus, TrackedItem  # noqa: E402
from download_literature.services.literature import AUTHOR_COPY_NOTE  # noqa: E402
from download_literature.services.reference_builder import Resolution  # noqa: E402
from download_literature.services.tracker import (  # noqa: E402
    add_new_entries,
    apply_md_edits,
    apply_outcomes,
    select_items,
)

WEBB_REF = Reference("Webb_2012", "Webb", doi="10.1037/a0027600", title="Dealing with feeling")
WEBB = TrackedItem(
    "Webb_2012",
    "Webb 2012",
    WEBB_REF,
    "Webb, T. L. (2012). *Dealing with feeling*.",
    ItemStatus.DOWNLOADED,
    file="Webb_2012.pdf",
    source="https://research.ebsco.com/x",
)
BECK_REF = Reference("Beck_1976", "Beck", kind=ReferenceKind.BOOK, title="Cognitive therapy")
BECK = TrackedItem(
    "Beck_1976",
    "Beck 1976",
    BECK_REF,
    "Beck, A. T. (1976). *Cognitive therapy*. IUP.",
    ItemStatus.BORROW,
    note="book: borrow from the library; latest edition: 1991, Penguin",
)
GROSS = TrackedItem(
    "Gross_1998",
    "Gross",
    Reference("Gross_1998", "Gross", doi="10.1037/x", title="Emerging"),
    "Gross, J. J. (1998). Emerging. *RGP*.",
    ItemStatus.NEEDS_REVIEW,
    note="needs you at www.sciencedirect.com: run with --interactive",
)
LOST = TrackedItem(
    "Unresolved_1",
    "Some unknown paper",
    None,
    "Some unknown paper",
    ItemStatus.NOT_FOUND,
    note="not found by title search; add authors, year or a DOI",
)

MD = """# 文獻清單

> 說明文字

## 待處理

- Your Brain on ChatGPT
* Kosmyna — another one
-

## 文獻清單（APA 7th）

| Key | APA 7th | 狀態 | 檔案 | 備註 |
|---|---|---|---|---|
| Webb_2012 | Webb, T. L. (2012). | ✅ 已下載（正式版） | x | y |
| Gross_1998 | Gross | 重試 | | |
"""


class ParseTest(unittest.TestCase):
    """Reading the user's edits from the Markdown file."""

    def test_pending_lines_and_row_statuses(self) -> None:
        """Pending bullets (any marker) are read; empty bullets ignored; table rows give key → status."""
        edits = parse_tracker_md(MD)
        self.assertEqual(edits.pending, ["Your Brain on ChatGPT", "Kosmyna — another one"])
        self.assertEqual(edits.rows, {"Webb_2012": "✅ 已下載（正式版）", "Gross_1998": "重試"})

    def test_missing_file_content(self) -> None:
        """An empty file has no edits (rows None = table not present)."""
        edits = parse_tracker_md("")
        self.assertEqual(edits.pending, [])
        self.assertIsNone(edits.rows)


class RenderTest(unittest.TestCase):
    """Writing the Markdown file."""

    def test_table_sorted_with_chinese_status_and_links(self) -> None:
        """Rows are in APA (alphabetical) order, statuses and notes are in Chinese, files are linked."""
        text = render_tracker_md([WEBB, BECK, GROSS], "../output/literature")
        rows = [line for line in text.splitlines() if line.startswith("| ") and "_" in line.split("|")[1]]
        self.assertEqual([r.split("|")[1].strip() for r in rows], ["Beck_1976", "Gross_1998", "Webb_2012"])
        self.assertIn("📕 需借閱", text)
        self.assertIn("最新版本：1991, Penguin", text)
        self.assertIn("⚠️ 需人工處理", text)
        self.assertIn("[Webb_2012.pdf](../output/literature/Webb_2012.pdf)", text)
        self.assertIn("來源：EBSCO", text)
        self.assertIn("## 待處理", text)

    def test_round_trip_keeps_rows(self) -> None:
        """What is rendered parses back to the same keys and statuses."""
        edits = parse_tracker_md(render_tracker_md([WEBB, LOST], "out"))
        assert edits.rows is not None
        self.assertEqual(set(edits.rows), {"Webb_2012", "Unresolved_1"})
        self.assertEqual(edits.pending, [])

    def test_pipes_in_text_are_escaped(self) -> None:
        """A '|' inside a citation does not break the table."""
        item = TrackedItem("A_1", "a", None, "Title | with pipe", ItemStatus.NOT_FOUND)
        edits = parse_tracker_md(render_tracker_md([item], "out"))
        self.assertEqual(edits.rows, {"A_1": "❓ 找不到文獻"})


class EditsTest(unittest.TestCase):
    """Applying the user's table edits."""

    def test_retry_and_deleted_rows(self) -> None:
        """'重試' sets a row back to pending; rows removed from the table leave the list."""
        items = apply_md_edits([WEBB, BECK, GROSS], {"Webb_2012": "✅", "Gross_1998": "重試"})
        self.assertEqual([i.key for i in items], ["Webb_2012", "Gross_1998"])
        self.assertEqual(items[1].status, ItemStatus.PENDING)

    def test_no_table_keeps_everything(self) -> None:
        """Without a table in the file (first run) nothing is deleted."""
        self.assertEqual(apply_md_edits([WEBB, BECK], None), [WEBB, BECK])


class SelectTest(unittest.TestCase):
    """Choosing what a run processes."""

    def test_unattended_and_interactive(self) -> None:
        """Pending always; needs-review only when interactive; done / borrow never."""
        pending = TrackedItem("P_1", "p", Reference("P_1", "p"), "p", ItemStatus.PENDING)
        items = [WEBB, BECK, GROSS, pending, LOST]
        self.assertEqual([i.key for i in select_items(items, interactive=False)], ["P_1"])
        self.assertEqual([i.key for i in select_items(items, interactive=True)], ["Gross_1998", "P_1"])


class FakeResolver:
    """Metadata resolver returning nothing (resolution is faked via resolve)."""

    def by_doi(self, doi: str) -> None:
        return None

    def search(self, citation: str) -> list:  # type: ignore[type-arg]
        return []


class AddEntriesTest(unittest.TestCase):
    """Turning pending lines into list items."""

    def test_new_duplicate_and_unresolved(self) -> None:
        """New works become pending items; a DOI already listed is skipped; unknown inputs are kept as ❓."""

        def resolve(text: str, resolver: object, taken: set[str]) -> Resolution:
            if text == "dup":
                ref = Reference("Webb_2012_b", "w", doi="10.1037/A0027600", title="Dealing with feeling")
                return Resolution(text, ref, None, "apa dup", "")
            if text == "lost":
                return Resolution(text, None, None, text, "not found by title search")
            ref = Reference("New_2025", "n", doi="10.1/new", title="New")
            return Resolution(text, ref, None, "New, A. (2025). New.", "matched by title search")

        items, skipped = add_new_entries([WEBB], ["new", "dup", "lost"], FakeResolver(), resolve)
        self.assertEqual([i.key for i in items], ["Webb_2012", "New_2025", "Unresolved_1"])
        self.assertEqual(items[1].status, ItemStatus.PENDING)
        self.assertEqual(items[2].status, ItemStatus.NOT_FOUND)
        self.assertEqual(skipped, ["dup"])


class OutcomeTest(unittest.TestCase):
    """Mapping download outcomes to list statuses."""

    def test_statuses(self) -> None:
        """Official, author copy, already present (copy kept), manual, review and failure map correctly."""
        p = Path("/x/A.pdf")
        items = [
            TrackedItem(
                k, k, Reference(k, k), k, ItemStatus.PENDING if k != "D" else ItemStatus.DOWNLOADED_COPY
            )
            for k in ("A", "B", "D", "E", "F", "G")
        ]
        outcomes = [
            DownloadOutcome(items[0].reference, DownloadStatus.DOWNLOADED, "https://dl.acm.org/x", p),  # type: ignore[arg-type]
            DownloadOutcome(
                items[1].reference, DownloadStatus.DOWNLOADED, "https://arxiv.org/x", p, AUTHOR_COPY_NOTE
            ),  # type: ignore[arg-type]
            DownloadOutcome(items[2].reference, DownloadStatus.ALREADY_PRESENT, path=p),  # type: ignore[arg-type]
            DownloadOutcome(items[3].reference, DownloadStatus.MANUAL, detail="book"),  # type: ignore[arg-type]
            DownloadOutcome(items[4].reference, DownloadStatus.NEEDS_REVIEW, detail="needs you"),  # type: ignore[arg-type]
            DownloadOutcome(items[5].reference, DownloadStatus.FAILED, detail="none"),  # type: ignore[arg-type]
        ]
        updated = {i.key: i for i in apply_outcomes(items, outcomes)}
        self.assertEqual(updated["A"].status, ItemStatus.DOWNLOADED)
        self.assertEqual(updated["A"].file, "A.pdf")
        self.assertEqual(updated["B"].status, ItemStatus.DOWNLOADED_COPY)
        self.assertEqual(updated["D"].status, ItemStatus.DOWNLOADED_COPY)
        self.assertEqual(updated["E"].status, ItemStatus.BORROW)
        self.assertEqual(updated["F"].status, ItemStatus.NEEDS_REVIEW)
        self.assertEqual(updated["G"].status, ItemStatus.UNAVAILABLE)


class PreprintAndNoteTest(unittest.TestCase):
    """Preprint servers and note formatting."""

    def test_preprint_server_download_is_marked_as_copy(self) -> None:
        """A PDF from arXiv / OSF is not shown as the peer-reviewed version."""
        item = TrackedItem("K", "k", Reference("K", "k"), "k", ItemStatus.PENDING)
        outcome = DownloadOutcome(
            item.reference,
            DownloadStatus.DOWNLOADED,
            "https://arxiv.org/pdf/2506.08872",  # type: ignore[arg-type]
            Path("/x/K.pdf"),
        )
        [updated] = apply_outcomes([item], [outcome])
        self.assertEqual(updated.status, ItemStatus.DOWNLOADED_COPY)
        self.assertIn("預印本", render_tracker_md([updated], "out"))

    def test_notes_use_chinese_separators(self) -> None:
        """Joined notes are separated with '；'."""
        item = TrackedItem(
            "B", "b", None, "b", ItemStatus.BORROW, note="book: borrow from the library; latest edition: 2000"
        )
        text = render_tracker_md([item], "out")
        self.assertIn("書籍：請向圖書館借閱；最新版本：2000", text)


class StorageTest(unittest.TestCase):
    """Saving and loading the list state."""

    def test_round_trip(self) -> None:
        """Items with and without references survive a save / load."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "references.json"
            save_items(path, [WEBB, BECK, LOST])
            self.assertEqual(load_items(path), [WEBB, BECK, LOST])


if __name__ == "__main__":
    unittest.main()
