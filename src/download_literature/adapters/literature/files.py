"""File adapters: load the reference list (JSON) and store downloaded PDFs by key."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from download_literature.domain.literature import Reference, ReferenceKind, safe_filename
from download_literature.domain.tracker import ItemStatus, TrackedItem

logger = logging.getLogger(__name__)


class FilePdfStore:
    """Saves PDFs as `<folder>/<key>.pdf`."""

    def __init__(self, folder: Path) -> None:
        """Create the store.

        Args:
            folder: Output folder (created on first save).
        """
        self._folder = folder

    def _path(self, key: str) -> Path:
        """Build the file path for a key.

        Args:
            key: Reference key.

        Returns:
            Path of the PDF.
        """
        return self._folder / f"{safe_filename(key)}.pdf"

    def existing(self, key: str) -> Path | None:
        """Find an already saved PDF.

        Args:
            key: Reference key.

        Returns:
            The path when the file exists and is not empty, else None.
        """
        path = self._path(key)
        return path if path.is_file() and path.stat().st_size > 0 else None

    def set_aside(self, key: str) -> Path | None:
        """Move an existing PDF to `superseded/` so a better version can be downloaded.

        Args:
            key: Reference key.

        Returns:
            Where the old file now is, or None when there was no file.
        """
        current = self.existing(key)
        if current is None:
            return None
        target = self._folder / "superseded" / current.name
        target.parent.mkdir(parents=True, exist_ok=True)
        current.replace(target)
        return target

    def restore(self, key: str, aside: Path) -> Path:
        """Put a file moved by `set_aside` back in place.

        Args:
            key: Reference key.
            aside: Path returned by `set_aside`.

        Returns:
            The restored path.
        """
        path = self._path(key)
        aside.replace(path)
        return path

    def save(self, key: str, data: bytes) -> Path:
        """Write PDF bytes atomically (temp file, then rename).

        Args:
            key: Reference key.
            data: PDF content.

        Returns:
            The saved path.
        """
        self._folder.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path


def _ref_to_dict(ref: Reference) -> dict[str, object]:
    """Serialise a reference (empty fields omitted).

    Args:
        ref: Reference.

    Returns:
        JSON-ready dict.
    """
    item: dict[str, object] = {
        "key": ref.key,
        "citation": ref.citation,
        "title": ref.title,
        "kind": ref.kind.value,
        "doi": ref.doi,
        "arxiv_id": ref.arxiv_id,
        "pdf_urls": list(ref.pdf_urls),
        "author": ref.author,
    }
    return {k: v for k, v in item.items() if v}


def _ref_from_dict(item: dict[str, object]) -> Reference:
    """Rebuild a reference from its JSON form.

    Args:
        item: Dict written by `_ref_to_dict` (or an old reference-list entry).

    Returns:
        The reference.
    """
    urls = item.get("pdf_urls") or []
    return Reference(
        key=str(item["key"]),
        citation=str(item.get("citation", "")),
        doi=str(item.get("doi", "")),
        kind=ReferenceKind(str(item.get("kind", "article"))),
        arxiv_id=str(item.get("arxiv_id", "")),
        pdf_urls=tuple(str(u) for u in urls) if isinstance(urls, list) else (),
        title=str(item.get("title", "")),
        author=str(item.get("author", "")),
    )


def load_items(path: Path) -> list[TrackedItem]:
    """Load the list state; an old reference list (no `status`) is migrated to pending items.

    Args:
        path: State JSON (`DATA_DIR/input/references.json`); missing file = empty list.

    Returns:
        List items (migrated items have an empty `apa` until they are identified again).
    """
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for entry in raw:
        if "status" not in entry:  # old format: one reference per entry
            ref = _ref_from_dict(entry)
            items.append(TrackedItem(ref.key, ref.citation, ref, "", ItemStatus.PENDING))
            continue
        ref_data = entry.get("reference")
        items.append(
            TrackedItem(
                key=entry["key"],
                input=entry.get("input", ""),
                reference=_ref_from_dict(ref_data) if ref_data else None,
                apa=entry.get("apa", ""),
                status=ItemStatus(entry["status"]),
                file=entry.get("file", ""),
                note=entry.get("note", ""),
                source=entry.get("source", ""),
                check=entry.get("check", ""),
            )
        )
    logger.info("loaded list file=%s items=%d", path.name, len(items))
    return items


def save_items(path: Path, items: list[TrackedItem]) -> None:
    """Write the list state atomically.

    Args:
        path: State JSON path.
        items: List items.
    """
    data = []
    for item in items:
        entry: dict[str, object] = {
            "key": item.key,
            "input": item.input,
            "apa": item.apa,
            "status": item.status.value,
            "file": item.file,
            "note": item.note,
            "source": item.source,
            "check": item.check,
            "reference": _ref_to_dict(item.reference) if item.reference else None,
        }
        data.append({k: v for k, v in entry.items() if v or k in ("key", "status")})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    logger.info("saved list file=%s items=%d", path.name, len(items))
