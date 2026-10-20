"""Offline tests for the two Markdown files: the input list (references.md) and the report (report.md)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.report_md import render_report_md  # noqa: E402
from download_literature.adapters.literature.tracker_md import pending_text, render_input_md  # noqa: E402
from download_literature.domain.literature import Reference, ReferenceKind  # noqa: E402
from download_literature.domain.tracker import ItemStatus, TrackedItem  # noqa: E402

WEBB = TrackedItem(
    "Webb_2012",
    "Webb 2012",
    Reference("Webb_2012", "Webb", doi="10.1/w", title="Dealing with feeling"),
    "Webb, T. L. (2012). Dealing with feeling. *Psychological Bulletin, 138*(4), 775–808.",
    ItemStatus.DOWNLOADED,
    file="Webb_2012.pdf",
    source="https://research.ebsco.com/c/x",
)
BECK = TrackedItem(
    "Beck_1976",
    "Beck",
    Reference("Beck_1976", "Beck", kind=ReferenceKind.BOOK, title="CT"),
    "Beck, A. T. (1976). *Cognitive therapy and the emotional disorders*. IUP.",
    ItemStatus.BORROW,
    note="book: borrow from the library; latest edition: 1991, Penguin",
)
GROSS = TrackedItem(
    "Gross_1998",
    "Gross",
    Reference("Gross_1998", "Gross", doi="10.1/g"),
    "Gross, J. J. (1998). Emerging.",
    ItemStatus.NEEDS_REVIEW,
    note="needs you at www.sciencedirect.com: run with --interactive",
)


class InputMdTest(unittest.TestCase):
    """The input list file."""

    def test_pending_text_is_read_between_headings(self) -> None:
        """Only the pending section is read; the processed list is ignored."""
        text = render_input_md([WEBB], ["Your Brain on ChatGPT"])
        self.assertEqual(pending_text(text).strip(), "Your Brain on ChatGPT")
        self.assertEqual(pending_text("").strip(), "")

    def test_processed_list_is_compact_and_ordered(self) -> None:
        """Processed items are one line each (icon, key, start of the APA text), in APA order."""
        text = render_input_md([WEBB, BECK, GROSS], [])
        lines = [line for line in text.splitlines() if line.startswith("- ")]
        self.assertTrue(lines[0].startswith("- 📕 Beck_1976 — Beck, A. T. (1976)."))
        self.assertTrue(lines[1].startswith("- ⚠️ Gross_1998"))
        self.assertTrue(lines[2].startswith("- ✅ Webb_2012"))
        self.assertNotIn("|", text)
        self.assertIn("report.md", text)


class ReportMdTest(unittest.TestCase):
    """The report file."""

    def test_list_layout_attention_section_and_apa_list(self) -> None:
        """No tables; items needing the user come first; a plain APA list closes the report."""
        text = render_report_md([WEBB, BECK, GROSS], "../literature", "2026-10-20 18:00")
        self.assertNotIn("|---", text)
        attention = text[text.index("## 需要你處理") : text.index("## 全部文獻")]
        self.assertIn("Gross_1998", attention)
        self.assertNotIn("Webb_2012", attention)
        self.assertIn("- 檔案：[Webb_2012.pdf](../literature/Webb_2012.pdf)", text)
        self.assertIn("- 來源：EBSCO", text)
        self.assertIn("最新版本：1991, Penguin", text)
        apa = text[text.index("## APA 7th 參考文獻") :]
        self.assertLess(apa.index("Beck, A. T."), apa.index("Webb, T. L."))
        self.assertIn("2026-10-20 18:00", text)


class OriginalInputTest(unittest.TestCase):
    """When the report repeats what the user typed."""

    def test_original_input_only_for_short_inputs(self) -> None:
        """A title-only input is shown; a full APA input (same information) is not."""
        short = TrackedItem(
            "K_2025", "Your Brain on ChatGPT", None, "Kosmyna, N. (2025). *Your brain*.", ItemStatus.NOT_FOUND
        )
        full = TrackedItem(
            "G_1998",
            "Gross, J. J. (1998). The emerging field. RGP, 2(3), 271–299.",
            None,
            "Gross, J. J. (1998). The emerging field. *RGP, 2*(3), 271–299.",
            ItemStatus.NOT_FOUND,
        )
        text = render_report_md([short, full], "lit", "now")
        self.assertIn("- 原始輸入：Your Brain on ChatGPT", text)
        self.assertNotIn("- 原始輸入：Gross", text)


if __name__ == "__main__":
    unittest.main()
