"""Request and response formats of the HTTP API (pydantic; validated at the boundary)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AddIn(BaseModel):
    """New entries: one per paragraph or bullet (APA, title, author + title or DOI)."""

    text: str = Field(min_length=1, max_length=200_000)


class AddOut(BaseModel):
    """Keys of the queued entries."""

    keys: list[str]


class ItemOut(BaseModel):
    """One reference as shown on the page."""

    key: str
    input: str
    apa: str
    apa_html: str
    status: str
    status_label: str
    kind: str
    file: str
    file_url: str
    source: str
    notes: str
    stage: str


class ProcessIn(BaseModel):
    """How to process the list."""

    interactive: bool = False
    use_browser: bool = True
    only: list[str] = Field(default_factory=list)
    refresh: list[str] = Field(default_factory=list)
    identify_only: bool = False


class JobOut(BaseModel):
    """Latest processing job."""

    id: int
    state: str
    total: int
    done: int
    message: str
    started_at: str
    finished_at: str | None


class StatusOut(BaseModel):
    """Overall progress."""

    running: bool
    job: JobOut | None
    counts: dict[str, int]
    stages: dict[str, str]
    last_error: str
    last_summary: str


class ApaOut(BaseModel):
    """APA 7 reference list for copying."""

    text: str
    html: str


class MessageOut(BaseModel):
    """Simple confirmation."""

    ok: bool
    message: str = ""
