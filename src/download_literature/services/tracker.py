"""Reference-tracker workflow (ADR-005): which list items to process and how results update them.

The user's Markdown list is the input and the output: new lines are identified and added, only
pending items (plus needs-review items when the user is at the computer) are downloaded, and each
download outcome becomes the item's status, file and note.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import replace

from download_literature.domain.literature import DownloadOutcome, DownloadStatus, Reference
from download_literature.domain.tracker import ItemStatus, TrackedItem
from download_literature.services.literature import AUTHOR_COPY_NOTE
from download_literature.services.reference_builder import Resolution, WorkResolver

logger = logging.getLogger(__name__)

ResolveFn = Callable[[str, WorkResolver, set[str]], Resolution]
_RETRY = re.compile(r"重試|retry", re.IGNORECASE)
# PDFs from these servers are preprints (not peer reviewed), even when no other version exists
PREPRINT_HOSTS = re.compile(
    r"arxiv\.org|osf\.io|psyarxiv|biorxiv|medrxiv|ssrn\.com|preprints\.org|researchsquare"
)
PREPRINT_NOTE = "preprint (not peer reviewed)"


def apply_md_edits(items: list[TrackedItem], rows: dict[str, str] | None) -> list[TrackedItem]:
    """Apply the user's table edits: deleted rows leave the list, '重試' (retry) sets a row to pending.

    Args:
        items: Current items.
        rows: Key → status text from the Markdown table; None when the file has no table yet.

    Returns:
        Updated items in their original order.
    """
    if rows is None:
        return list(items)
    kept = []
    for item in items:
        if item.key not in rows:
            logger.info("item removed by user key=%s", item.key)
            continue
        kept.append(replace(item, status=ItemStatus.PENDING) if _RETRY.search(rows[item.key]) else item)
    return kept


def _identity(ref: Reference) -> set[str]:
    """Ids used to spot a work that is already listed.

    Args:
        ref: Reference.

    Returns:
        Lower-case DOI and normalised title.
    """
    ids = {f"doi:{ref.doi.lower()}"} if ref.doi else set()
    words = re.findall(r"[a-z0-9]+", ref.title.lower())
    return ids | ({"title:" + " ".join(words)} if words else set())


def _next_unresolved_key(items: list[TrackedItem]) -> str:
    """Build a key for an input that could not be identified.

    Args:
        items: Current items.

    Returns:
        `Unresolved_N` not used yet.
    """
    n = 1
    keys = {i.key for i in items}
    while f"Unresolved_{n}" in keys:
        n += 1
    return f"Unresolved_{n}"


def _new_item(line: str, res: Resolution, items: list[TrackedItem]) -> TrackedItem:
    """Build the list item for a newly added line.

    Args:
        line: The user's line.
        res: Its resolution.
        items: Items so far (for a free `Unresolved_N` key).

    Returns:
        A pending item, or a not-found item when the work was not identified.
    """
    if res.reference is None:
        return TrackedItem(
            _next_unresolved_key(items), line, None, res.apa, ItemStatus.NOT_FOUND, note=res.note
        )
    return TrackedItem(res.reference.key, line, res.reference, res.apa, ItemStatus.PENDING, check=res.note)


def add_new_entries(
    items: list[TrackedItem], lines: list[str], resolver: WorkResolver, resolve: ResolveFn
) -> tuple[list[TrackedItem], list[str]]:
    """Identify new lines and add them to the list.

    Args:
        items: Current items.
        lines: New lines from the pending section.
        resolver: Metadata service.
        resolve: Function turning one line into a Resolution (`reference_builder.resolve_entry`).

    Returns:
        (items with the new ones appended, lines skipped because the work is already listed).
    """
    result = list(items)
    taken = {i.key for i in items}
    known = set().union(*(_identity(i.reference) for i in items if i.reference))
    skipped = []
    for line in lines:
        res = resolve(line, resolver, taken)
        if res.reference is not None and _identity(res.reference) & known:
            skipped.append(line)
            continue
        item = _new_item(line, res, result)
        known |= _identity(item.reference) if item.reference else set()
        result.append(item)
    logger.info("new entries=%d added=%d skipped=%d", len(lines), len(result) - len(items), len(skipped))
    return result, skipped


def select_items(items: list[TrackedItem], interactive: bool) -> list[TrackedItem]:
    """Choose the items a run downloads.

    Args:
        items: All items.
        interactive: The user is at the computer (also retry items that need a person).

    Returns:
        Pending items with a reference, plus needs-review items when interactive.
    """
    wanted = {ItemStatus.PENDING} | ({ItemStatus.NEEDS_REVIEW} if interactive else set())
    return [i for i in items if i.status in wanted and i.reference is not None]


def _status(previous: ItemStatus, outcome: DownloadOutcome) -> ItemStatus:
    """Map a download outcome to a list status.

    Args:
        previous: Status before this run.
        outcome: Download outcome.

    Returns:
        New status.
    """
    if outcome.status is DownloadStatus.DOWNLOADED:
        copy = AUTHOR_COPY_NOTE in outcome.detail or PREPRINT_HOSTS.search(outcome.source)
        return ItemStatus.DOWNLOADED_COPY if copy else ItemStatus.DOWNLOADED
    if outcome.status is DownloadStatus.ALREADY_PRESENT:
        return ItemStatus.DOWNLOADED_COPY if previous is ItemStatus.DOWNLOADED_COPY else ItemStatus.DOWNLOADED
    return {
        DownloadStatus.MANUAL: ItemStatus.BORROW,
        DownloadStatus.NEEDS_REVIEW: ItemStatus.NEEDS_REVIEW,
    }.get(outcome.status, ItemStatus.UNAVAILABLE)


def _note(outcome: DownloadOutcome) -> str:
    """Note to keep for an outcome; preprint-server downloads are labelled as preprints.

    Args:
        outcome: Download outcome.

    Returns:
        Note text.
    """
    preprint = outcome.status is DownloadStatus.DOWNLOADED and PREPRINT_HOSTS.search(outcome.source)
    if preprint and AUTHOR_COPY_NOTE not in outcome.detail:
        return "; ".join(x for x in (PREPRINT_NOTE, outcome.detail) if x)
    return outcome.detail


def apply_outcomes(items: list[TrackedItem], outcomes: list[DownloadOutcome]) -> list[TrackedItem]:
    """Write download outcomes back into the list.

    Args:
        items: All items.
        outcomes: Outcomes of this run.

    Returns:
        Items with status, file, note and source updated for processed keys.
    """
    by_key = {o.reference.key: o for o in outcomes}
    updated = []
    for item in items:
        outcome = by_key.get(item.key)
        if outcome is None:
            updated.append(item)
            continue
        updated.append(
            replace(
                item,
                status=_status(item.status, outcome),
                file=outcome.path.name if outcome.path else "",
                note=_note(outcome),
                source=outcome.source or item.source,
            )
        )
    return updated


def _merge_reference(old: Reference, found: Reference | None) -> Reference:
    """Fill gaps of a migrated reference from a fresh identification (key, DOI and URLs are kept).

    Args:
        old: Reference from the previous list.
        found: Freshly identified reference, or None.

    Returns:
        The completed reference.
    """
    if found is None:
        return old
    return replace(
        old,
        title=old.title or found.title,
        author=old.author or found.author,
        doi=old.doi or found.doi,
        arxiv_id=old.arxiv_id or found.arxiv_id,
    )


def refresh_identification(
    items: list[TrackedItem], resolver: WorkResolver, resolve: ResolveFn
) -> list[TrackedItem]:
    """Give migrated items their APA text and identify again items set back to pending without a reference.

    Args:
        items: All items.
        resolver: Metadata service.
        resolve: Function turning one line into a Resolution.

    Returns:
        Updated items.
    """
    taken = {i.key for i in items}
    updated = []
    for item in items:
        if item.reference is not None and not item.apa:
            res = resolve(item.input or item.reference.citation, resolver, set())
            item = replace(
                item, apa=res.apa, reference=_merge_reference(item.reference, res.reference), check=res.note
            )
        elif item.reference is None and item.status is ItemStatus.PENDING:
            res = resolve(item.input, resolver, taken)
            status = ItemStatus.PENDING if res.reference else ItemStatus.NOT_FOUND
            key = res.reference.key if res.reference else item.key
            item = replace(
                item,
                key=key,
                reference=res.reference,
                apa=res.apa,
                status=status,
                note="" if res.reference else res.note,
                check=res.note if res.reference else "",
            )
        updated.append(item)
    return updated
