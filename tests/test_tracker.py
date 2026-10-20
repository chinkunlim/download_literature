"""Offline tests for the Markdown reference tracker: edits, rendering, selection and status updates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.literature.report_md import render_report_md  # noqa: E402
from download_literature.domain.literature import DownloadOutcome, DownloadStatus, Reference, ReferenceKind  # noqa: E402
from download_literature.domain.tracker import ItemStatus, TrackedItem  # noqa: E402
from download_literature.services.literature import AUTHOR_COPY_NOTE  # noqa: E402
from download_literature.services.tracker import (  # noqa: E402
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

_UNUSED = """# 文獻清單

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


class SelectTest(unittest.TestCase):
    """Choosing what a run processes."""

    def test_unattended_and_interactive(self) -> None:
        """Pending always; needs-review only when interactive; done / borrow never."""
        pending = TrackedItem("P_1", "p", Reference("P_1", "p"), "p", ItemStatus.PENDING)
        items = [WEBB, BECK, GROSS, pending, LOST]
        self.assertEqual([i.key for i in select_items(items, interactive=False)], ["P_1"])
        self.assertEqual([i.key for i in select_items(items, interactive=True)], ["Gross_1998", "P_1"])


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
        self.assertIn("預印本", render_report_md([updated], "out", "now"))

    def test_notes_use_chinese_separators(self) -> None:
        """Joined notes are separated with '；'."""
        item = TrackedItem(
            "B", "b", None, "b", ItemStatus.BORROW, note="book: borrow from the library; latest edition: 2000"
        )
        text = render_report_md([item], "out", "now")
        self.assertIn("書籍：請向圖書館借閱；最新版本：2000", text)


if __name__ == "__main__":
    unittest.main()
