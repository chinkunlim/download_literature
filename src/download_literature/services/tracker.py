"""Reference-tracker workflow (ADR-005): which list items to process and how results update them.

The user's Markdown list is the input and the output: new lines are identified and added, only
pending items (plus needs-review items when the user is at the computer) are downloaded, and each
download outcome becomes the item's status, file and note.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from download_literature.domain.apa import parse_apa
from download_literature.domain.literature import DownloadOutcome, DownloadStatus, Reference
from download_literature.domain.tracker import ItemStatus, JobState, TrackedItem
from download_literature.services.literature import AUTHOR_COPY_NOTE, Sources, download_reference
from download_literature.services.reference_builder import LOOKUP_FAILED_NOTE, Resolution, WorkResolver

logger = logging.getLogger(__name__)

ResolveFn = Callable[[str, WorkResolver, set[str]], Resolution]
# PDFs from these servers are preprints (not peer reviewed), even when no other version exists
PREPRINT_HOSTS = re.compile(
    r"arxiv\.org|osf\.io|psyarxiv|biorxiv|medrxiv|ssrn\.com|preprints\.org|researchsquare"
)
PREPRINT_NOTE = "preprint (not peer reviewed)"


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


def apply_outcome(item: TrackedItem, outcome: DownloadOutcome) -> TrackedItem:
    """Write one download outcome into its item.

    Args:
        item: The item that was processed.
        outcome: Its download outcome.

    Returns:
        The item with status, file, note and source updated.
    """
    return replace(
        item,
        status=_status(item.status, outcome),
        file=outcome.path.name if outcome.path else "",
        note=_note(outcome),
        source=outcome.source or item.source,
    )


def apply_outcomes(items: list[TrackedItem], outcomes: list[DownloadOutcome]) -> list[TrackedItem]:
    """Write download outcomes back into the list.

    Args:
        items: All items.
        outcomes: Outcomes of this run.

    Returns:
        Items with status, file, note and source updated for processed keys.
    """
    by_key = {o.reference.key: o for o in outcomes}
    return [apply_outcome(i, by_key[i.key]) if i.key in by_key else i for i in items]


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


class ItemStore(Protocol):
    """Where the list lives (the SQL store in production)."""

    def list_items(self) -> list[TrackedItem]:
        """Return all items in order.

        Returns:
            Items.
        """
        ...

    def get(self, key: str) -> TrackedItem | None:
        """Return one item.

        Args:
            key: Item key.

        Returns:
            The item, or None when deleted.
        """
        ...

    def add(self, item: TrackedItem) -> None:
        """Append an item.

        Args:
            item: New item.
        """
        ...

    def update(self, item: TrackedItem) -> bool:
        """Update an existing item.

        Args:
            item: Item with new values.

        Returns:
            False when it no longer exists.
        """
        ...

    def delete(self, key: str) -> bool:
        """Remove an item.

        Args:
            key: Item key.

        Returns:
            False when it did not exist.
        """
        ...

    def replace_key(self, old_key: str, item: TrackedItem) -> bool:
        """Replace an item whose key changes.

        Args:
            old_key: Current key.
            item: New values.

        Returns:
            False when the old item no longer exists.
        """
        ...

    def set_stage(self, key: str, stage: str) -> None:
        """Record the step an item is in.

        Args:
            key: Item key.
            stage: Step name; empty when idle.
        """
        ...

    def start_job(self, kind: str, total: int) -> int:
        """Record a new job.

        Args:
            kind: Job kind.
            total: Number of items.

        Returns:
            Job id.
        """
        ...

    def advance_job(self, job_id: int, done: int, message: str) -> None:
        """Update job progress.

        Args:
            job_id: Job id.
            done: Items finished.
            message: Progress text.
        """
        ...

    def finish_job(self, job_id: int, state: JobState, message: str) -> None:
        """Mark a job finished.

        Args:
            job_id: Job id.
            state: Done or failed.
            message: Summary.
        """
        ...


def split_pending(text: str) -> list[str]:
    """Split the pending text into entries.

    Bullets ('- ', '* ', '1.') start entries; blank lines separate entries; inside a block, a line without
    an APA date continues the previous line only when that line is an APA reference (wrapped text),
    otherwise every line (e.g. a list of titles) is its own entry.

    Args:
        text: Pending section text.

    Returns:
        Entries with whitespace normalised.
    """
    entries: list[str] = []
    joinable = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((">", "#")):
            joinable = False
            continue
        bullet = re.match(r"^(?:[-*+•]|\d+[.)])\s+", line)
        line = re.sub(r"\s+", " ", line[bullet.end() :] if bullet else line).strip()
        if not line:
            continue
        has_date = _has_apa_date(line)
        if joinable and not bullet and not has_date:
            entries[-1] = f"{entries[-1]} {line}"
            continue
        entries.append(line)
        joinable = has_date
    return entries


def _has_apa_date(line: str) -> bool:
    """Tell whether a line contains an APA date such as `(2019).`.

    Args:
        line: Text.

    Returns:
        True when it parses as the start of an APA reference.
    """
    try:
        parse_apa(line)
    except ValueError:
        return False
    return True


def download_items(
    store: ItemStore, keys: list[str], sources: Sources, refresh: frozenset[str] = frozenset()
) -> int:
    """Download items one by one, recording each step and the result as it happens.

    Items deleted meanwhile are skipped (never re-created).

    Args:
        store: Item store.
        keys: Keys to process, in order.
        sources: Download sources.
        refresh: Keys whose existing PDF should be replaced by a better copy if found.

    Returns:
        The job id.
    """
    job_id = store.start_job("download", len(keys))
    tracked = replace(sources, progress=store.set_stage)
    try:
        for done, key in enumerate(keys, start=1):
            item = store.get(key)
            if item is not None and item.reference is not None:
                store.set_stage(key, "開始")
                outcome = download_reference(item.reference, tracked, key in refresh)
                store.update(apply_outcome(item, outcome))
                store.set_stage(key, "")
            store.advance_job(job_id, done, key)
    except BaseException as exc:  # also Ctrl-C: the job must never stay "running" (ISSUE-005)
        for key in keys:
            store.set_stage(key, "")
        store.finish_job(job_id, JobState.FAILED, str(exc) or type(exc).__name__)
        raise
    store.finish_job(job_id, JobState.DONE, f"{len(keys)} processed")
    return job_id


def queue_entries(store: ItemStore, lines: list[str]) -> list[str]:
    """Add raw entries at once as pending items (identified later, during processing).

    Args:
        store: Item store.
        lines: Entries as the user wrote them.

    Returns:
        Keys of the queued items.
    """
    items = store.list_items()
    keys = []
    for line in (raw.strip() for raw in lines):
        if not line:
            continue
        item = TrackedItem(_next_unresolved_key(items), line, None, line, ItemStatus.PENDING)
        store.add(item)
        items.append(item)
        keys.append(item.key)
    logger.info("queued entries=%d", len(keys))
    return keys


@dataclass(frozen=True)
class IdentifyResult:
    """Outcome of identifying pending entries.

    Attributes:
        changed: Items identified or updated.
        duplicates: Entries removed because the work was already in the list.
    """

    changed: int
    duplicates: list[str]


def _identified(item: TrackedItem, res: Resolution) -> TrackedItem:
    """Apply a resolution to a pending raw entry.

    Args:
        item: Pending item without a reference.
        res: Its resolution.

    Returns:
        Identified item (pending), not-found item, or still-pending item when the lookup failed.
    """
    if res.reference is not None:
        return replace(
            item, key=res.reference.key, reference=res.reference, apa=res.apa, check=res.note, note=""
        )
    if res.note.startswith(LOOKUP_FAILED_NOTE):  # temporary: try again next time (not "not found")
        return replace(item, note=res.note)
    return replace(item, status=ItemStatus.NOT_FOUND, apa=res.apa, note=res.note)


def _complete_migrated(
    store: ItemStore, item: TrackedItem, resolver: WorkResolver, resolve: ResolveFn
) -> None:
    """Give an item migrated from the old list its APA text and missing reference fields.

    Args:
        store: Item store.
        item: Migrated item (has a reference, no APA yet).
        resolver: Metadata service.
        resolve: Function turning one line into a Resolution.
    """
    assert item.reference is not None
    res = resolve(item.input or item.reference.citation, resolver, set())
    merged = _merge_reference(item.reference, res.reference)
    store.update(replace(item, apa=res.apa, reference=merged, check=res.note))


def identify_pending(store: ItemStore, resolver: WorkResolver, resolve: ResolveFn) -> IdentifyResult:
    """Identify pending raw entries and give migrated items their APA text.

    Args:
        store: Item store.
        resolver: Metadata service.
        resolve: Function turning one line into a Resolution.

    Returns:
        Number of items changed and entries dropped as duplicates.
    """
    items = store.list_items()
    known = set().union(*(_identity(i.reference) for i in items if i.reference))
    taken = {i.key for i in items}
    changed, duplicates = 0, []
    for item in items:
        if item.reference is not None and not item.apa:
            _complete_migrated(store, item, resolver, resolve)
            changed += 1
            continue
        if item.reference is not None or item.status is not ItemStatus.PENDING:
            continue
        new = _identified(item, resolve(item.input, resolver, taken))
        if new.reference is not None and _identity(new.reference) & known:
            store.delete(item.key)
            duplicates.append(item.input)
            continue
        known |= _identity(new.reference) if new.reference else set()
        store.replace_key(item.key, new) if new.key != item.key else store.update(new)
        changed += 1
    return IdentifyResult(changed, duplicates)
