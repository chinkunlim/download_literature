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


class JobState(str, Enum):
    """State of a background processing job."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class Job:
    """One processing run (from the command line, the web page or an API call).

    Attributes:
        id: Job number.
        kind: What the job does (e.g. `download`, `identify`).
        state: Running, done or failed.
        total: Number of items to process.
        done: Items finished so far.
        message: Latest progress text (e.g. the key being processed).
        started_at: Start time (ISO 8601, UTC).
        finished_at: End time; None while running.
    """

    id: int
    kind: str
    state: JobState
    total: int
    done: int
    message: str
    started_at: str
    finished_at: str | None


class AlreadyRunningError(Exception):
    """Another processing job is running (only one may use the browser and the list at a time)."""
