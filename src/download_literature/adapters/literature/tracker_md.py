"""Markdown reference list (ADR-005): the file the user edits and reads.

Layout:
    # 文獻清單
    > instructions
    ## 待處理            ← the user adds one line per work (APA, author + title, title or DOI)
    ## 文獻清單（APA 7th） ← table written by the program: Key | APA 7th | 狀態 | 檔案 | 備註

`parse_tracker_md` reads the user's edits (new lines; key → status cell, where '重試' means retry and a
removed row means delete). `render_tracker_md` writes the whole file, rows in APA alphabetical order,
statuses and notes in Chinese.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from download_literature.domain.tracker import ItemStatus, TrackedItem

PENDING_HEADING = "## 待處理"
TABLE_HEADING = "## 文獻清單（APA 7th）"
TABLE_HEADER = "| Key | APA 7th | 狀態 | 檔案 | 備註 |"

STATUS_LABELS = {
    ItemStatus.PENDING: "⏳ 待處理",
    ItemStatus.DOWNLOADED: "✅ 已下載（正式版）",
    ItemStatus.DOWNLOADED_COPY: "🟡 已下載（作者稿／預印本）",
    ItemStatus.NEEDS_REVIEW: "⚠️ 需人工處理",
    ItemStatus.BORROW: "📕 需借閱",
    ItemStatus.UNAVAILABLE: "❌ 無法取得",
    ItemStatus.NOT_FOUND: "❓ 找不到文獻",
}

INTRO = "\n".join(
    [
        "> **使用方式**：在「待處理」每行寫一筆文獻（完整 APA、作者＋標題、只有標題或 DOI 都可以），"
        "然後執行 `uv run fetch-literature`。",
        "> 程式只處理新加入的文獻，以及狀態欄改成「重試」的列；處理完會移到下方表格，並補上 APA 7th 格式。"
        "刪除表格的整列，就是把那筆文獻從清單移除。",
        ">",
        "> **狀態說明**：✅ 已下載（正式版）｜🟡 已下載（作者稿／預印本，引用頁碼請以正式版為準）｜"
        "⚠️ 需人工處理（在電腦前執行 `uv run fetch-literature --interactive`）｜📕 需借閱｜"
        "❌ 無法取得（可寫信向作者索取或申請館際合作）｜❓ 找不到文獻（請補上作者、年份或 DOI 後重新加入）",
    ]
)

_NOTE_TRANSLATIONS: list[tuple[str, str]] = [
    (
        r"author/preprint copy: check page numbers against the published version",
        "作者稿／預印本：引用頁碼請以正式版為準",
    ),
    (r"needs you at ([^:;]+): run with --interactive", r"需要人工驗證（\1）：在電腦前執行 --interactive"),
    (r"preprint \(not peer reviewed\)", "預印本（未經同儕審查）"),
    (r"book: borrow from the library", "書籍：請向圖書館借閱"),
    (r"latest edition: ", "最新版本："),
    (r"matched by title search; check the APA entry", "依標題搜尋配對，請確認 APA 資料"),
    (r"no better copy found; kept the previous copy", "沒有找到更好的版本，保留原檔"),
    (
        r"no PDF from open access, EBSCO or publisher",
        "開放取用、EBSCO、出版社都沒有全文（可寫信向作者索取或申請館際合作）",
    ),
    (r"not found by title search; add authors, year or a DOI", "找不到這篇文獻：請補上作者、年份或 DOI"),
    (r"no DOI found; check the citation or add a URL", "找不到 DOI：請檢查引文或補上網址"),
    (r"DOI (\S+) not found on Crossref; check the DOI", r"DOI \1 查不到，請檢查"),
    (r"DOI title differs from the citation: ", "DOI 對應的標題與引文不同："),
    (r"metadata lookup failed \([^)]*\)[^;]*", "查詢書目資料失敗，稍後再試"),
]
_SOURCE_NAMES = {"research.ebsco.com": "EBSCO", "arxiv.org": "arXiv", "archive.org": "Internet Archive"}


@dataclass(frozen=True)
class TrackerEdits:
    """What the user changed in the Markdown file.

    Attributes:
        pending: New lines from the pending section.
        rows: Key → status cell of each table row; None when the file has no table.
    """

    pending: list[str]
    rows: dict[str, str] | None


def _split_row(line: str) -> list[str]:
    """Split a Markdown table row into cells (escaped pipes stay in the cell).

    Args:
        line: Row text starting with '|'.

    Returns:
        Cell texts, stripped.
    """
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def parse_tracker_md(text: str) -> TrackerEdits:
    """Read the user's edits from the list file.

    Args:
        text: Markdown file content (empty for a new file).

    Returns:
        New pending lines and the table's key → status cells.
    """
    pending: list[str] = []
    rows: dict[str, str] | None = None
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = (
                "pending"
                if line.startswith(PENDING_HEADING)
                else "table"
                if line.startswith(TABLE_HEADING)
                else ""
            )
            if section == "table":
                rows = {}
            continue
        stripped = line.strip()
        if section == "pending" and stripped and not stripped.startswith(">"):
            entry = re.sub(r"^(?:[-*+•]|\d+[.)])\s*", "", stripped).strip()
            if entry:
                pending.append(entry)
        elif section == "table" and rows is not None and stripped.startswith("|"):
            cells = _split_row(stripped)
            if len(cells) >= 3 and cells[0] not in ("Key", "") and not set(cells[0]) <= {"-", ":"}:
                rows[cells[0]] = cells[2]
    return TrackerEdits(pending, rows)


def translate_note(note: str) -> str:
    """Translate the program's English notes into Chinese for the list.

    Args:
        note: Note text.

    Returns:
        Chinese note (unknown parts are kept).
    """
    for pattern, replacement in _NOTE_TRANSLATIONS:
        note = re.sub(pattern, replacement, note)
    return note.replace("; ", "；")


def _source_name(url: str) -> str:
    """Short name of where a PDF came from.

    Args:
        url: Source URL.

    Returns:
        e.g. EBSCO, arXiv, or the host name.
    """
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return next((name for domain, name in _SOURCE_NAMES.items() if host.endswith(domain)), host)


def _cell(text: str) -> str:
    """Make text safe for a table cell.

    Args:
        text: Any text.

    Returns:
        Single-line text with pipes escaped.
    """
    return re.sub(r"\s+", " ", text).replace("|", "\\|").strip()


def _row(item: TrackedItem, file_base: str) -> str:
    """Render one table row.

    Args:
        item: List item.
        file_base: Path from the Markdown file to the PDF folder.

    Returns:
        Markdown row.
    """
    link = f"[{item.file}]({file_base}/{item.file})" if item.file else ""
    source = f"來源：{_source_name(item.source)}" if item.source and item.file else ""
    notes = "；".join(x for x in (translate_note(item.check), translate_note(item.note), source) if x)
    cells = [item.key, item.apa, STATUS_LABELS[item.status], link, notes]
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def render_tracker_md(items: list[TrackedItem], file_base: str) -> str:
    """Write the whole list file.

    Args:
        items: All items.
        file_base: Path from the Markdown file to the PDF folder (used for file links).

    Returns:
        Markdown text with an empty pending section and the table in APA alphabetical order.
    """
    rows = [_row(i, file_base) for i in sorted(items, key=lambda i: re.sub(r"[^a-z0-9 ]", "", i.apa.lower()))]
    lines = [
        "# 文獻清單",
        "",
        INTRO,
        "",
        PENDING_HEADING,
        "",
        "- ",
        "",
        TABLE_HEADING,
        "",
        TABLE_HEADER,
        "|---|---|---|---|---|",
        *rows,
    ]
    return "\n".join(lines) + "\n"
