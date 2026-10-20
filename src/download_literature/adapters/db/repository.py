"""SQL item store: the reference list and job records in the database (ADR-006).

All writes are per item, so the web page, the command line and API callers can change the list
while a job runs without overwriting each other (a job only updates rows that still exist).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from download_literature.adapters.db.engine import session_scope
from download_literature.adapters.db.models import ItemRow, JobRow
from download_literature.domain.literature import Reference, ReferenceKind
from download_literature.domain.tracker import ItemStatus, Job, JobState, TrackedItem

logger = logging.getLogger(__name__)


def _now() -> str:
    """Current UTC time.

    Returns:
        ISO 8601 timestamp.
    """
    return datetime.now(UTC).isoformat(timespec="seconds")


def _columns(item: TrackedItem) -> dict[str, object]:
    """Map an item to column values (everything except `position`).

    Args:
        item: List item.

    Returns:
        Column name → value.
    """
    ref = item.reference
    return {
        "key": item.key,
        "input": item.input,
        "apa": item.apa,
        "status": item.status.value,
        "file": item.file,
        "note": item.note,
        "source": item.source,
        "check_note": item.check,
        "has_reference": ref is not None,
        "citation": ref.citation if ref else "",
        "doi": ref.doi if ref else "",
        "kind": ref.kind.value if ref else "article",
        "arxiv_id": ref.arxiv_id if ref else "",
        "pdf_urls": json.dumps(list(ref.pdf_urls) if ref else []),
        "title": ref.title if ref else "",
        "author": ref.author if ref else "",
        "updated_at": _now(),
    }


def _item(row: ItemRow) -> TrackedItem:
    """Map a row to a domain item.

    Args:
        row: Database row.

    Returns:
        The item.
    """
    ref = None
    if row.has_reference:
        ref = Reference(
            key=row.key,
            citation=row.citation,
            doi=row.doi,
            kind=ReferenceKind(row.kind),
            arxiv_id=row.arxiv_id,
            pdf_urls=tuple(json.loads(row.pdf_urls or "[]")),
            title=row.title,
            author=row.author,
        )
    return TrackedItem(
        row.key,
        row.input,
        ref,
        row.apa,
        ItemStatus(row.status),
        row.file,
        row.note,
        row.source,
        row.check_note,
    )


def _job(row: JobRow) -> Job:
    """Map a job row to a domain job.

    Args:
        row: Database row.

    Returns:
        The job.
    """
    return Job(
        row.id,
        row.kind,
        JobState(row.state),
        row.total,
        row.done,
        row.message,
        row.started_at,
        row.finished_at,
    )


class SqlItemStore:
    """Reference list and jobs stored with SQLAlchemy."""

    def __init__(self, engine: Engine) -> None:
        """Create the store.

        Args:
            engine: Database engine (schema already created / migrated).
        """
        self._factory: sessionmaker[Session] = sessionmaker(engine, expire_on_commit=False)

    def list_items(self) -> list[TrackedItem]:
        """Return all items in the order they were added.

        Returns:
            Items.
        """
        with session_scope(self._factory) as s:
            return [_item(r) for r in s.scalars(select(ItemRow).order_by(ItemRow.position))]

    def get(self, key: str) -> TrackedItem | None:
        """Return one item.

        Args:
            key: Item key.

        Returns:
            The item, or None.
        """
        with session_scope(self._factory) as s:
            row = s.get(ItemRow, key)
            return _item(row) if row else None

    def add(self, item: TrackedItem) -> None:
        """Append an item to the list.

        Args:
            item: New item (its key must be unused).
        """
        with session_scope(self._factory) as s:
            position = (s.scalar(select(func.max(ItemRow.position))) or 0) + 1
            s.add(ItemRow(position=position, **_columns(item)))
        logger.info("item added key=%s status=%s", item.key, item.status.value)

    def update(self, item: TrackedItem) -> bool:
        """Update an existing item (deleted items are not re-created).

        Args:
            item: Item with new values.

        Returns:
            False when the item no longer exists.
        """
        with session_scope(self._factory) as s:
            result = s.execute(update(ItemRow).where(ItemRow.key == item.key).values(**_columns(item)))
            return bool(getattr(result, "rowcount", 0))

    def replace_key(self, old_key: str, item: TrackedItem) -> bool:
        """Replace an item whose key changes (an unresolved entry identified later), keeping its position.

        Args:
            old_key: Current key.
            item: New item values (with the new key).

        Returns:
            False when the old item no longer exists.
        """
        with session_scope(self._factory) as s:
            row = s.get(ItemRow, old_key)
            if row is None:
                return False
            position = row.position
            s.delete(row)
            s.flush()
            s.add(ItemRow(position=position, **_columns(item)))
            return True

    def delete(self, key: str) -> bool:
        """Remove an item from the list.

        Args:
            key: Item key.

        Returns:
            False when it did not exist.
        """
        with session_scope(self._factory) as s:
            result = s.execute(delete(ItemRow).where(ItemRow.key == key))
            removed = bool(getattr(result, "rowcount", 0))
        logger.info("item deleted key=%s removed=%s", key, removed)
        return removed

    def set_stage(self, key: str, stage: str) -> None:
        """Record the step an item is in (shown as progress).

        Args:
            key: Item key.
            stage: Step name; empty when idle.
        """
        with session_scope(self._factory) as s:
            s.execute(update(ItemRow).where(ItemRow.key == key).values(stage=stage))

    def stages(self) -> dict[str, str]:
        """Return the items that are being processed.

        Returns:
            Key → current step.
        """
        with session_scope(self._factory) as s:
            rows = s.execute(select(ItemRow.key, ItemRow.stage).where(ItemRow.stage != "")).all()
            return {k: st for k, st in rows}

    def start_job(self, kind: str, total: int) -> int:
        """Record a new running job.

        Args:
            kind: Job kind (e.g. `download`).
            total: Number of items.

        Returns:
            Job id.
        """
        with session_scope(self._factory) as s:
            row = JobRow(
                kind=kind, state=JobState.RUNNING.value, total=total, done=0, message="", started_at=_now()
            )
            s.add(row)
            s.flush()
            return int(row.id)

    def advance_job(self, job_id: int, done: int, message: str) -> None:
        """Update a job's progress.

        Args:
            job_id: Job id.
            done: Items finished.
            message: Progress text.
        """
        with session_scope(self._factory) as s:
            s.execute(update(JobRow).where(JobRow.id == job_id).values(done=done, message=message))

    def finish_job(self, job_id: int, state: JobState, message: str) -> None:
        """Mark a job finished.

        Args:
            job_id: Job id.
            state: Done or failed.
            message: Summary or error text.
        """
        with session_scope(self._factory) as s:
            values = {"state": state.value, "message": message, "finished_at": _now()}
            s.execute(update(JobRow).where(JobRow.id == job_id).values(**values))

    def jobs(self, limit: int = 10) -> list[Job]:
        """Return recent jobs, newest first.

        Args:
            limit: Maximum number of jobs.

        Returns:
            Jobs.
        """
        with session_scope(self._factory) as s:
            rows = s.scalars(select(JobRow).order_by(JobRow.id.desc()).limit(limit))
            return [_job(r) for r in rows]
