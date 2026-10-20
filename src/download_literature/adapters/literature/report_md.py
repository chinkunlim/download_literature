"""Report file `output/report.md` (ADR-006): full results as lists (no wide tables).

Sections: summary counts → items that need the user → every reference (APA, status, file, source,
notes) → a plain APA 7th reference list ready to copy. Written from the database after every run.
"""

from __future__ import annotations

from collections import Counter

from download_literature.adapters.literature.tracker_md import (
    STATUS_LABELS,
    apa_sort_key,
    source_name,
    translate_note,
)
from download_literature.domain.apa import parse_apa
from download_literature.domain.tracker import ItemStatus, TrackedItem

ATTENTION = (ItemStatus.NEEDS_REVIEW, ItemStatus.NOT_FOUND, ItemStatus.UNAVAILABLE, ItemStatus.BORROW)


def _notes(item: TrackedItem) -> str:
    """Join an item's notes in Chinese.

    Args:
        item: List item.

    Returns:
        Notes separated by '；'.
    """
    return "；".join(x for x in (translate_note(item.check), translate_note(item.note)) if x)


def _is_apa(text: str) -> bool:
    """Tell whether an input is already a full APA reference.

    Args:
        text: User input.

    Returns:
        True when it has an APA date such as `(2019).`.
    """
    try:
        parse_apa(text)
    except ValueError:
        return False
    return True


def _block(item: TrackedItem, file_base: str) -> list[str]:
    """Render one reference as a heading plus a bullet list.

    Args:
        item: List item.
        file_base: Path from the report to the PDF folder.

    Returns:
        Markdown lines.
    """
    lines = [f"### {STATUS_LABELS[item.status]} · {item.key}", "", f"- APA：{item.apa}"]
    if item.file:
        lines.append(f"- 檔案：[{item.file}]({file_base}/{item.file})")
    if item.source and item.file:
        lines.append(f"- 來源：{source_name(item.source)}")
    if _notes(item):
        lines.append(f"- 備註：{_notes(item)}")
    if item.input and not _is_apa(item.input):  # a full APA input would only repeat the APA line
        lines.append(f"- 原始輸入：{item.input}")
    return [*lines, ""]


def render_report_md(items: list[TrackedItem], file_base: str, generated_at: str) -> str:
    """Write report.md.

    Args:
        items: All items.
        file_base: Path from the report to the PDF folder (for file links).
        generated_at: Time shown in the header.

    Returns:
        Markdown text.
    """
    ordered = sorted(items, key=apa_sort_key)
    counts = Counter(i.status for i in items)
    summary = "｜".join(f"{STATUS_LABELS[s]} {counts[s]}" for s in ItemStatus if counts[s])
    attention = [i for i in ordered if i.status in ATTENTION]
    lines = [
        "# 文獻下載報告",
        "",
        f"更新時間：{generated_at}｜共 {len(items)} 筆",
        "",
        summary,
        "",
        "## 需要你處理",
        "",
    ]
    lines += [f"- {STATUS_LABELS[i.status]} · {i.key}：{_notes(i) or '—'}" for i in attention] or ["- 沒有"]
    lines += ["", "## 全部文獻", ""]
    for item in ordered:
        lines += _block(item, file_base)
    lines += ["## APA 7th 參考文獻（可直接複製）", ""]
    lines += [f"{i.apa}\n" for i in ordered if i.reference is not None]
    return "\n".join(lines).rstrip() + "\n"
