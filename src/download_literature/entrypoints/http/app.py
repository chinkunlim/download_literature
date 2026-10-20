"""FastAPI application: the web page and the JSON API used by the page, scripts and Open WebUI (ADR-008).

Routes are thin: validate input → call the shared `Runner` (or the job manager) → format the output.
Only local use is allowed: requests must come to 127.0.0.1 / localhost (DNS-rebinding guard) and
changes from another site's page (foreign `Origin`) are refused.
"""

from __future__ import annotations

import html
import logging
import re
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from download_literature.adapters.literature.tracker_md import (
    STATUS_LABELS,
    apa_sort_key,
    source_name,
    translate_note,
)
from download_literature.domain.tracker import TrackedItem
from download_literature.entrypoints.http.jobs import JobManager
from download_literature.entrypoints.http.schemas import (
    AddIn,
    AddOut,
    ApaOut,
    ItemOut,
    JobOut,
    MessageOut,
    ProcessIn,
    StatusOut,
)
from download_literature.entrypoints.runner import ProcessOptions, Runner
from download_literature.services.tracker import split_pending

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"


def apa_html(apa: str) -> str:
    """Render APA Markdown italics as HTML.

    Args:
        apa: APA text with `*italic*` parts.

    Returns:
        Escaped HTML with `<i>` tags.
    """
    return re.sub(r"\*([^*]+)\*", r"<i>\1</i>", html.escape(apa))


def _item_out(item: TrackedItem, stage: str) -> ItemOut:
    """Convert an item for the page.

    Args:
        item: List item.
        stage: Current processing step ("" when idle).

    Returns:
        API representation.
    """
    notes = "；".join(x for x in (translate_note(item.check), translate_note(item.note)) if x)
    return ItemOut(
        key=item.key,
        input=item.input,
        apa=item.apa,
        apa_html=apa_html(item.apa),
        status=item.status.value,
        status_label=STATUS_LABELS[item.status],
        kind=item.reference.kind.value if item.reference else "",
        file=item.file,
        file_url=f"/files/{item.key}" if item.file else "",
        source=source_name(item.source) if item.source and item.file else "",
        notes=notes,
        stage=stage,
    )


class LocalOnly(BaseHTTPMiddleware):
    """Refuse requests not addressed to this machine, and changes coming from other websites."""

    def __init__(self, app: object, hosts: set[str], origins: set[str]) -> None:
        """Create the middleware.

        Args:
            app: ASGI app.
            hosts: Allowed Host headers.
            origins: Allowed Origin headers for state-changing requests.
        """
        super().__init__(app)  # type: ignore[arg-type]
        self._hosts = hosts
        self._origins = origins

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Check Host and Origin before handling the request.

        Args:
            request: Incoming request.
            call_next: Next handler.

        Returns:
            The response, or 403.
        """
        origin = request.headers.get("origin")
        changing = request.method not in ("GET", "HEAD", "OPTIONS")
        if request.headers.get("host", "") not in self._hosts or (
            changing and origin and origin not in self._origins
        ):
            logger.warning(
                "refused request host=%s origin=%s path=%s",
                request.headers.get("host"),
                origin,
                request.url.path,
            )
            return JSONResponse({"detail": "only local requests from this app are allowed"}, status_code=403)
        return await call_next(request)


router = APIRouter()


def _runner(request: Request) -> Runner:
    """Shared runner of this app.

    Args:
        request: Incoming request.

    Returns:
        The runner set by `create_app`.
    """
    runner: Runner = request.app.state.runner
    return runner


def _jobs(request: Request) -> JobManager:
    """Job manager of this app.

    Args:
        request: Incoming request.

    Returns:
        The job manager set by `create_app`.
    """
    jobs: JobManager = request.app.state.jobs
    return jobs


def _existing(request: Request, key: str) -> Runner:
    """Return the runner after checking that an item exists.

    Args:
        request: Incoming request.
        key: Item key.

    Returns:
        The runner.

    Raises:
        HTTPException: 404 when the item does not exist.
    """
    runner = _runner(request)
    if runner.store.get(key) is None:
        raise HTTPException(status_code=404, detail="no such item")
    return runner


@router.get("/api/items", response_model=list[ItemOut])
def list_items(request: Request) -> list[ItemOut]:
    """List all references (APA order) with their current processing step.

    Args:
        request: Incoming request.

    Returns:
        Items.
    """
    runner = _runner(request)
    stages = runner.store.stages()
    return [_item_out(i, stages.get(i.key, "")) for i in sorted(runner.store.list_items(), key=apa_sort_key)]


@router.post("/api/items", response_model=AddOut)
def add_items(request: Request, body: AddIn) -> AddOut:
    """Add entries (one per paragraph or bullet); they are identified when the list is processed.

    Args:
        request: Incoming request.
        body: The pasted text.

    Returns:
        Keys of the queued entries.
    """
    return AddOut(keys=_runner(request).add_entries(split_pending(body.text)))


@router.post("/api/items/{key}/retry", response_model=MessageOut)
def retry_item(request: Request, key: str) -> MessageOut:
    """Process an item again at the next run.

    Args:
        request: Incoming request.
        key: Item key.

    Returns:
        Confirmation.
    """
    return MessageOut(ok=bool(_existing(request, key).retry({key})))


@router.post("/api/items/{key}/reidentify", response_model=MessageOut)
def reidentify_item(request: Request, key: str) -> MessageOut:
    """Look an item up again (new APA text) at the next run.

    Args:
        request: Incoming request.
        key: Item key.

    Returns:
        Confirmation.
    """
    return MessageOut(ok=bool(_existing(request, key).reidentify({key})))


@router.delete("/api/items/{key}", response_model=MessageOut)
def delete_item(request: Request, key: str) -> MessageOut:
    """Remove an item from the list (its PDF stays on disk).

    Args:
        request: Incoming request.
        key: Item key.

    Returns:
        Confirmation.
    """
    return MessageOut(ok=bool(_existing(request, key).delete({key})))


@router.post("/api/process", status_code=202, response_model=MessageOut)
def process(request: Request, body: ProcessIn) -> MessageOut:
    """Start processing the list in the background.

    Args:
        request: Incoming request.
        body: Process options.

    Returns:
        Confirmation (409 when a job is already running).
    """
    options = ProcessOptions(
        body.interactive,
        300,
        body.use_browser,
        frozenset(body.only),
        frozenset(body.refresh),
        body.identify_only,
    )
    if not _jobs(request).start(options):
        raise HTTPException(status_code=409, detail="a job is already running")
    return MessageOut(ok=True, message="started")


@router.get("/api/status", response_model=StatusOut)
def status(request: Request) -> StatusOut:
    """Report the running job, counts per status and items being processed.

    Args:
        request: Incoming request.

    Returns:
        Status.
    """
    runner, jobs = _runner(request), _jobs(request)
    latest = runner.store.jobs(limit=1)
    job = latest[0] if latest else None
    job_out = (
        JobOut(
            id=job.id,
            state=job.state.value,
            total=job.total,
            done=job.done,
            message=job.message,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
        if job
        else None
    )
    counts = Counter(i.status.value for i in runner.store.list_items())
    return StatusOut(
        running=jobs.running(),
        job=job_out,
        counts=dict(counts),
        stages=runner.store.stages(),
        last_error=jobs.last_error,
        last_summary=jobs.summary_text(),
    )


@router.get("/files/{key}")
def pdf(request: Request, key: str) -> FileResponse:
    """Open a downloaded PDF in the browser.

    Args:
        request: Incoming request.
        key: Item key.

    Returns:
        The PDF file.

    Raises:
        HTTPException: 404 when there is no PDF for the item.
    """
    runner = _runner(request)
    item = runner.store.get(key)
    folder = runner.config.literature_dir.resolve()
    path = (folder / item.file).resolve() if item and item.file else None
    if path is None or path.parent != folder or not path.is_file():
        raise HTTPException(status_code=404, detail="no PDF for this item")
    return FileResponse(
        path, media_type="application/pdf", content_disposition_type="inline", filename=path.name
    )


@router.get("/api/apa", response_model=ApaOut)
def apa_list(request: Request) -> ApaOut:
    """APA 7 reference list (identified items, APA order) as plain text and as HTML with italics.

    Args:
        request: Incoming request.

    Returns:
        Text and HTML versions.
    """
    items = [
        i for i in sorted(_runner(request).store.list_items(), key=apa_sort_key) if i.reference is not None
    ]
    return ApaOut(
        text="\n".join(i.apa.replace("*", "") for i in items),
        html="".join(f"<p>{apa_html(i.apa)}</p>" for i in items),
    )


@router.get("/api/report.md", response_class=PlainTextResponse)
def report(request: Request) -> PlainTextResponse:
    """The current report.md (downloaded as a file).

    Args:
        request: Incoming request.

    Returns:
        The report as Markdown.
    """
    runner = _runner(request)
    runner.write_files()
    return PlainTextResponse(
        runner.report_md.read_text(encoding="utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="report.md"'},
    )


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """The single-page app.

    Returns:
        The page.
    """
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


def create_app(runner: Runner, jobs: JobManager, port: int) -> FastAPI:
    """Assemble the web app.

    Args:
        runner: Shared runner (database, files, processing).
        jobs: Background job manager.
        port: Port the app is served on (for the local Host / Origin checks).

    Returns:
        The FastAPI application.
    """
    app = FastAPI(title="文獻下載", docs_url="/docs")
    extra = {f"{h}:{port}" for h in runner.config.http_allowed_hosts}
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", "testserver"} | extra
    app.add_middleware(
        LocalOnly, hosts=hosts, origins={f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    )

    app.state.runner = runner
    app.state.jobs = jobs
    app.include_router(router)
    return app
