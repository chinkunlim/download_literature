"""Tests for the web app and HTTP API (TestClient; temporary data folder; processing is faked)."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from download_literature.config.settings import AppConfig  # noqa: E402
from download_literature.domain.tracker import ItemStatus  # noqa: E402
from download_literature.entrypoints.http.app import create_app  # noqa: E402
from download_literature.entrypoints.http.jobs import JobManager  # noqa: E402
from download_literature.entrypoints.runner import ProcessOptions, Runner, RunSummary  # noqa: E402
from download_literature.services.tracker import IdentifyResult  # noqa: E402

PDF = b"%PDF-1.4\n" + b"q" * 100


class WebTest(unittest.TestCase):
    """Pages and API endpoints."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        config = AppConfig(app_env="test", log_to_file=False, data_dir=Path(self.tmp.name))
        self.runner = Runner(config)
        self.gate = threading.Event()
        self.calls: list[ProcessOptions] = []

        def fake_process(options: ProcessOptions) -> RunSummary:
            self.calls.append(options)
            self.gate.wait(5)
            return RunSummary([], IdentifyResult(1, ["Rethinking rumination"]), [], None)

        self.jobs = JobManager(fake_process)
        self.client = TestClient(create_app(self.runner, self.jobs, port=8765))

    def tearDown(self) -> None:
        self.gate.set()
        self.jobs.wait(5)
        self.tmp.cleanup()

    def test_home_page(self) -> None:
        """The single-page app is served at /."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("文獻下載", resp.text)

    def test_add_list_retry_reidentify_delete(self) -> None:
        """Entries are added (split like the md file), listed, retried, re-identified and deleted."""
        resp = self.client.post("/api/items", json={"text": "- Title one\n- Title two"})
        self.assertEqual(resp.json()["keys"], ["Unresolved_1", "Unresolved_2"])
        items = self.client.get("/api/items").json()
        self.assertEqual(
            [(i["key"], i["status"]) for i in items],
            [("Unresolved_1", "pending"), ("Unresolved_2", "pending")],
        )
        self.assertEqual(items[0]["status_label"], "⏳ 待處理")
        self.assertEqual(self.client.delete("/api/items/Unresolved_2").status_code, 200)
        self.assertEqual(self.client.delete("/api/items/Unresolved_2").status_code, 404)
        self.assertEqual(len(self.client.get("/api/items").json()), 1)
        self.assertEqual(self.client.post("/api/items/Missing/retry").status_code, 404)

    def test_process_job_and_busy(self) -> None:
        """Starting a job returns 202; a second start while running returns 409; status shows the run."""
        resp = self.client.post("/api/process", json={"interactive": True})
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(self.client.post("/api/process", json={}).status_code, 409)
        self.assertTrue(self.client.get("/api/status").json()["running"])
        self.gate.set()
        self.jobs.wait(5)
        status = self.client.get("/api/status").json()
        self.assertFalse(status["running"])
        self.assertEqual(status["last_error"], "")
        self.assertIn("略過重複：Rethinking rumination", status["last_summary"])
        self.assertIn("辨識 1", status["last_summary"])
        self.assertTrue(self.calls[0].interactive)

    def test_pdf_and_apa_export(self) -> None:
        """Downloaded PDFs are served by key; the APA list is offered as text and HTML (italics kept)."""
        self.client.post("/api/items", json={"text": "x"})
        item = self.runner.store.get("Unresolved_1")
        assert item is not None
        from dataclasses import replace

        from download_literature.domain.literature import Reference

        ref = Reference("Unresolved_1", "x", title="x")
        self.runner.store.update(
            replace(
                item,
                reference=ref,
                apa="Doe, J. (2020). *A book*. Pub.",
                status=ItemStatus.DOWNLOADED,
                file="Unresolved_1.pdf",
            )
        )
        self.runner.config.literature_dir.mkdir(parents=True, exist_ok=True)
        (self.runner.config.literature_dir / "Unresolved_1.pdf").write_bytes(PDF)
        resp = self.client.get("/files/Unresolved_1")
        self.assertEqual((resp.status_code, resp.content[:5]), (200, b"%PDF-"))
        self.assertEqual(self.client.get("/files/Nope").status_code, 404)
        apa = self.client.get("/api/apa").json()
        self.assertEqual(apa["text"], "Doe, J. (2020). A book. Pub.")
        self.assertIn("<i>A book</i>", apa["html"])
        self.assertEqual(self.client.get("/api/report.md").status_code, 200)

    def test_cross_site_requests_are_refused(self) -> None:
        """Changes from another website's page (foreign Origin) or a foreign Host are rejected."""
        resp = self.client.post("/api/items", json={"text": "x"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get("/api/items", headers={"Host": "evil.example"})
        self.assertEqual(resp.status_code, 403)
        ok = self.client.post("/api/items", json={"text": "x"}, headers={"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(ok.status_code, 200)


class ExtraHostTest(unittest.TestCase):
    """Extra host names (e.g. Open WebUI in Docker calling host.docker.internal)."""

    def test_configured_extra_host_is_accepted(self) -> None:
        """A host listed in the settings is allowed; others are still refused."""
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(
                app_env="test",
                log_to_file=False,
                data_dir=Path(tmp),
                http_allowed_hosts=("host.docker.internal",),
            )
            runner = Runner(config)
            client = TestClient(create_app(runner, JobManager(runner.process), port=8765))
            ok = client.get("/api/items", headers={"Host": "host.docker.internal:8765"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(client.get("/api/items", headers={"Host": "evil.example"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
