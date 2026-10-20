"""Input list file `references.md` (ADR-005, ADR-006): what the user wants downloaded.

Layout:
    # 文獻清單（輸入）
    > instructions
    ## 待處理      ← the user adds entries: one per paragraph or bullet (APA, author + title, title, DOI)
    ## 已處理      ← written by the program: one compact line per item (status, key, start of the APA text)

Full results live in `output/report.md` and on the web page; this file only says what to fetch.
Shared helpers (status labels, Chinese notes, source names) are also used by `report_md`.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from download_literature.domain.tracker import ItemStatus, TrackedItem

STATUS_LABELS = {
    ItemStatus.PENDING: "⏳ 待處理",
    ItemStatus.DOWNLOADED: "✅ 已下載（正式版）",
    ItemStatus.DOWNLOADED_COPY: "🟡 已下載（作者稿／預印本）",
    ItemStatus.NEEDS_REVIEW: "⚠️ 需人工處理",
    ItemStatus.BORROW: "📕 需借閱",
    ItemStatus.UNAVAILABLE: "❌ 無法取得",
    ItemStatus.NOT_FOUND: "❓ 找不到文獻",
}


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


def source_name(url: str) -> str:
    """Short name of where a PDF came from.

    Args:
        url: Source URL.

    Returns:
        e.g. EBSCO, arXiv, or the host name.
    """
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return next((name for domain, name in _SOURCE_NAMES.items() if host.endswith(domain)), host)


PENDING_HEADING = "## 待處理"
DONE_HEADING = "## 已處理"
_INPUT_INTRO = [
    "> 在「待處理」加入文獻：每筆一段（或每行一個 `- ` 項目），",
    "> 可以是完整 APA、作者＋標題、只有標題或 DOI。從 Word 貼上的 APA 換行也沒關係，",
    "> 筆與筆之間空一行即可。執行 `uv run fetch-literature` 或在網頁按「開始處理」。",
    "> 處理完的文獻會移到「已處理」。完整結果請看 `output/report.md` 或網頁。",
]


def pending_text(text: str) -> str:
    """Return the raw text of the pending section.

    Args:
        text: Content of references.md (empty for a new file).

    Returns:
        Text between "## 待處理" and the next heading.
    """
    match = re.search(rf"^{PENDING_HEADING}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def apa_sort_key(item: TrackedItem) -> str:
    """Sort key for APA reference-list order.

    Args:
        item: List item.

    Returns:
        Lower-case letters and digits of the APA text.
    """
    return re.sub(r"[^a-z0-9 ]", "", item.apa.lower())


def short_apa(item: TrackedItem, length: int = 90) -> str:
    """Start of the APA text, without Markdown italics, for one-line lists.

    Args:
        item: List item.
        length: Maximum characters.

    Returns:
        Shortened text.
    """
    text = item.apa.replace("*", "")
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def render_input_md(items: list[TrackedItem], pending: list[str]) -> str:
    """Write references.md.

    Args:
        items: All processed items.
        pending: Entries still waiting (normally empty after a run).

    Returns:
        Markdown text.
    """
    done = [
        f"- {STATUS_LABELS[i.status].split()[0]} {i.key} — {short_apa(i)}"
        for i in sorted(items, key=apa_sort_key)
    ]
    lines = [
        "# 文獻清單（輸入）",
        "",
        *_INPUT_INTRO,
        "",
        PENDING_HEADING,
        "",
        *pending,
        "",
        f"{DONE_HEADING}（{len(items)} 筆）",
        "",
        *done,
    ]
    return "\n".join(lines) + "\n"
