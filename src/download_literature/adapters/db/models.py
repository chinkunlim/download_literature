"""ORM models: `items` (one row per reference in the user's list) and `jobs` (processing runs).

Only the db adapter imports these; other layers get domain objects (`TrackedItem`, `Job`).
Every change here needs an Alembic migration (`uv run alembic revision --autogenerate -m ...`).
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all tables."""


class ItemRow(Base):
    """One reference of the list.

    Columns mirror `domain.tracker.TrackedItem`; the reference part is stored inline
    (`has_reference` false = not identified yet). `position` keeps the order of addition.
    """

    __tablename__ = "items"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, index=True)
    input: Mapped[str] = mapped_column(Text, default="")
    apa: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    file: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    check_note: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(100), default="")
    has_reference: Mapped[bool] = mapped_column(default=False)
    citation: Mapped[str] = mapped_column(Text, default="")
    doi: Mapped[str] = mapped_column(String(300), default="", index=True)
    kind: Mapped[str] = mapped_column(String(16), default="article")
    arxiv_id: Mapped[str] = mapped_column(String(40), default="")
    pdf_urls: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    title: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[str] = mapped_column(String(40), default="")


class JobRow(Base):
    """One processing run."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
