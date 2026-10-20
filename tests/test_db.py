"""Offline tests for the SQLite item store and job records (in-memory database)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.db.engine import create_db_engine, init_schema  # noqa: E402
from download_literature.adapters.db.repository import SqlItemStore  # noqa: E402
from download_literature.domain.literature import Reference, ReferenceKind  # noqa: E402
from download_literature.domain.tracker import ItemStatus, JobState, TrackedItem  # noqa: E402

WEBB = TrackedItem(
    "Webb_2012",
    "Webb 2012",
    Reference(
        "Webb_2012",
        "Webb",
        doi="10.1037/a0027600",
        title="Dealing with feeling",
        author="Webb",
        pdf_urls=("https://x/a.pdf",),
    ),
    "Webb, T. L. (2012).",
    ItemStatus.DOWNLOADED,
    file="Webb_2012.pdf",
    note="n",
    source="s",
    check="c",
)
LOST = TrackedItem("Unresolved_1", "unknown", None, "unknown", ItemStatus.NOT_FOUND)
BOOK = TrackedItem(
    "Beck_1976",
    "Beck",
    Reference("Beck_1976", "Beck", kind=ReferenceKind.BOOK, title="CT"),
    "Beck (1976).",
    ItemStatus.PENDING,
)


def _store() -> SqlItemStore:
    engine = create_db_engine("sqlite://")
    init_schema(engine)
    return SqlItemStore(engine)


class ItemStoreTest(unittest.TestCase):
    """Items in the database."""

    def test_round_trip_keeps_order_and_fields(self) -> None:
        """Items come back unchanged, in the order they were added."""
        store = _store()
        for item in (WEBB, LOST, BOOK):
            store.add(item)
        self.assertEqual(store.list_items(), [WEBB, LOST, BOOK])
        self.assertEqual(store.get("Beck_1976"), BOOK)
        self.assertIsNone(store.get("missing"))

    def test_update_only_existing_items(self) -> None:
        """Updating a deleted item does not bring it back."""
        store = _store()
        store.add(WEBB)
        self.assertTrue(store.update(WEBB.__class__(**{**WEBB.__dict__, "note": "new"})))
        self.assertEqual(store.get("Webb_2012").note, "new")  # type: ignore[union-attr]
        self.assertTrue(store.delete("Webb_2012"))
        self.assertFalse(store.update(WEBB))
        self.assertEqual(store.list_items(), [])
        self.assertFalse(store.delete("Webb_2012"))

    def test_rename_key(self) -> None:
        """An item identified later can change its key."""
        store = _store()
        store.add(LOST)
        found = TrackedItem(
            "Kosmyna_2025", "unknown", Reference("Kosmyna_2025", "k"), "K (2025).", ItemStatus.PENDING
        )
        self.assertTrue(store.replace_key("Unresolved_1", found))
        self.assertEqual([i.key for i in store.list_items()], ["Kosmyna_2025"])

    def test_stage(self) -> None:
        """The current processing step of an item can be set and read."""
        store = _store()
        store.add(BOOK)
        store.set_stage("Beck_1976", "EBSCO")
        self.assertEqual(store.stages(), {"Beck_1976": "EBSCO"})
        store.set_stage("Beck_1976", "")
        self.assertEqual(store.stages(), {})


class JobTest(unittest.TestCase):
    """Job records for progress."""

    def test_job_lifecycle(self) -> None:
        """A job is created, advanced and finished; the latest job is returned first."""
        store = _store()
        job_id = store.start_job("download", total=3)
        store.advance_job(job_id, done=1, message="Webb_2012")
        job = store.jobs(limit=1)[0]
        self.assertEqual(
            (job.id, job.kind, job.state, job.total, job.done, job.message),
            (job_id, "download", JobState.RUNNING, 3, 1, "Webb_2012"),
        )
        store.finish_job(job_id, JobState.DONE, "ok")
        job = store.jobs(limit=1)[0]
        self.assertEqual((job.state, job.message), (JobState.DONE, "ok"))
        self.assertIsNotNone(job.finished_at)


if __name__ == "__main__":
    unittest.main()
