"""Offline tests for the store-based workflow: importing lines, identifying, downloading with progress."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from download_literature.adapters.db.engine import create_db_engine, init_schema  # noqa: E402
from download_literature.adapters.db.repository import SqlItemStore  # noqa: E402
from download_literature.adapters.literature.files import FilePdfStore  # noqa: E402
from download_literature.domain.literature import Reference  # noqa: E402
from download_literature.domain.tracker import ItemStatus, JobState  # noqa: E402
from download_literature.services.literature import Sources  # noqa: E402
from download_literature.services.reference_builder import Resolution  # noqa: E402
from download_literature.services.tracker import (  # noqa: E402
    download_items,
    identify_pending,
    queue_entries,
    split_pending,
)

PDF = b"%PDF-1.5\n" + b"z" * 300


def _store() -> SqlItemStore:
    engine = create_db_engine("sqlite://")
    init_schema(engine)
    return SqlItemStore(engine)


def _resolve(text: str, resolver: object, taken: set[str]) -> Resolution:
    """Fake resolver: 'lost' is not found; anything else becomes Key_<text>."""
    if text == "lost":
        return Resolution(text, None, None, text, "not found by title search")
    key = f"Key_{text.replace(' ', '')}"
    taken.add(key)
    ref = Reference(key, text, doi=f"10.1/{text}", title=text)
    return Resolution(text, ref, None, f"APA {text}", "")


class SplitPendingTest(unittest.TestCase):
    """Turning the pending section into entries."""

    def test_bullets_titles_and_wrapped_apa(self) -> None:
        """Bullets and title lines are separate; a wrapped APA reference is joined; blank lines separate."""
        text = (
            "- Title one\n"
            "- Title two\n"
            "\n"
            "Plain title three\n"
            "Plain title four\n"
            "\n"
            "Gross, J. J. (1998). The emerging field of emotion regulation.\n"
            "Review of General Psychology, 2(3), 271–299.\n"
            "Webb, T. L. (2012). Dealing with feeling. Psych Bull, 1, 2.\n"
        )
        self.assertEqual(
            split_pending(text),
            [
                "Title one",
                "Title two",
                "Plain title three",
                "Plain title four",
                "Gross, J. J. (1998). The emerging field of emotion regulation. Review of General "
                "Psychology, 2(3), 271–299.",
                "Webb, T. L. (2012). Dealing with feeling. Psych Bull, 1, 2.",
            ],
        )


class QueueAndIdentifyTest(unittest.TestCase):
    """Adding raw entries instantly, identifying them during processing."""

    def test_queue_then_identify(self) -> None:
        """Queued lines are pending at once; identification finds, flags unknown, and drops duplicates."""
        store = _store()
        self.assertEqual(
            queue_entries(store, ["a", "lost", "a", "  "]), ["Unresolved_1", "Unresolved_2", "Unresolved_3"]
        )
        self.assertEqual({i.status for i in store.list_items()}, {ItemStatus.PENDING})
        result = identify_pending(store, object(), _resolve)  # type: ignore[arg-type]
        self.assertEqual(result.duplicates, ["a"])
        items = store.list_items()
        self.assertEqual([i.key for i in items], ["Key_a", "Unresolved_2"])
        self.assertEqual(items[1].status, ItemStatus.NOT_FOUND)


class FakeFinder:
    """No open-access copies."""

    def find_pdf_locations(self, doi: str) -> list:  # type: ignore[type-arg]
        return []


class FakeHttp:
    """Nothing over plain HTTP."""

    def fetch(self, url: str) -> bytes | None:
        return None


class DownloadTest(unittest.TestCase):
    """Downloading stored items."""

    def test_progress_status_and_deleted_items(self) -> None:
        """Items get their step while processed, a final status, and deleted keys are skipped."""
        store = _store()
        seen: list[dict[str, str]] = []

        class Route:
            label = "EBSCO"

            def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
                seen.append(store.stages())
                return (PDF, "https://research.ebsco.com/x") if reference.key == "Key_a" else None

        queue_entries(store, ["a", "b"])
        identify_pending(store, object(), _resolve)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as tmp:
            sources = Sources(FakeFinder(), FakeHttp(), (Route(),), FilePdfStore(Path(tmp)))
            job_id = download_items(store, ["Key_a", "Key_b", "Gone_1"], sources)
        items = {i.key: i for i in store.list_items()}
        self.assertEqual(items["Key_a"].status, ItemStatus.DOWNLOADED)
        self.assertEqual(items["Key_a"].file, "Key_a.pdf")
        self.assertEqual(items["Key_b"].status, ItemStatus.UNAVAILABLE)
        self.assertEqual(seen[0], {"Key_a": "EBSCO"})
        self.assertEqual(store.stages(), {})
        job = store.jobs(1)[0]
        self.assertEqual((job.id, job.state, job.done, job.total), (job_id, JobState.DONE, 3, 3))

    def test_interrupted_run_is_recorded_as_failed(self) -> None:
        """Ctrl-C during a download ends the job as failed and clears the step (never stuck 'running')."""
        store = _store()

        class Route:
            def fetch_pdf(self, reference: Reference) -> tuple[bytes, str] | None:
                store.set_stage(reference.key, "EBSCO")
                raise KeyboardInterrupt

        queue_entries(store, ["a"])
        identify_pending(store, object(), _resolve)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as tmp:
            sources = Sources(FakeFinder(), FakeHttp(), (Route(),), FilePdfStore(Path(tmp)))
            with self.assertRaises(KeyboardInterrupt):
                download_items(store, ["Key_a"], sources)
        self.assertEqual(store.stages(), {})
        self.assertEqual(store.jobs(1)[0].state, JobState.FAILED)


if __name__ == "__main__":
    unittest.main()
