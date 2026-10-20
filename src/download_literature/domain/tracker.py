"""Domain model of the reference tracker: one item per line of the user's Markdown list (ADR-005)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from download_literature.domain.literature import Reference


class ItemStatus(str, Enum):
    """Where an item of the list stands."""

    PENDING = "pending"
    DOWNLOADED = "downloaded"
    DOWNLOADED_COPY = "downloaded_copy"
    NEEDS_REVIEW = "needs_review"
    BORROW = "borrow"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class TrackedItem:
    """One entry of the user's reference list.

    Attributes:
        key: Unique key (file name stem); `Unresolved_N` for inputs not identified yet.
        input: The line as the user wrote it.
        reference: What to download; None when the work could not be identified.
        apa: APA 7 reference (the input text when not identified).
        status: Current status.
        file: Saved PDF file name; empty when none.
        note: Latest download note (blocked sites, author copy, latest book edition, ...).
        source: URL the PDF came from.
        check: Note from identifying the work (e.g. matched by title search) that stays visible.
    """

    key: str
    input: str
    reference: Reference | None
    apa: str
    status: ItemStatus
    file: str = ""
    note: str = ""
    source: str = ""
    check: str = ""
