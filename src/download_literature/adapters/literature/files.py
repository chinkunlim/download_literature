"""File adapters: load the reference list (JSON) and store downloaded PDFs by key."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from download_literature.domain.literature import Reference, ReferenceKind, safe_filename

logger = logging.getLogger(__name__)


def load_references(path: Path) -> list[Reference]:
    """Read a JSON list of references.

    Each item needs `key` and `citation`; optional `doi`, `kind` (article / chapter / book),
    `arxiv_id`, `pdf_urls` (list) and `title` (enables the wrong-paper check).

    Args:
        path: JSON file, usually in `DATA_DIR/input/`.

    Returns:
        References in file order.

    Raises:
        ValueError: When an item lacks `key` / `citation`, keys repeat, or `kind` is unknown.
    """
    items = json.loads(path.read_text(encoding="utf-8"))
    refs = [
        Reference(
            key=item["key"],
            citation=item["citation"],
            doi=item.get("doi", ""),
            kind=ReferenceKind(item.get("kind", "article")),
            arxiv_id=item.get("arxiv_id", ""),
            pdf_urls=tuple(item.get("pdf_urls", [])),
            title=item.get("title", ""),
        )
        for item in items
    ]
    keys = [ref.key for ref in refs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate reference keys in " + path.name)
    logger.info("loaded references file=%s count=%d", path.name, len(refs))
    return refs


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


def save_references(path: Path, refs: list[Reference]) -> None:
    """Write references as a JSON list readable by `load_references` (empty fields omitted).

    Args:
        path: Target JSON file; parent folders are created.
        refs: References to write.
    """
    items = []
    for ref in refs:
        item: dict[str, object] = {
            "key": ref.key,
            "citation": ref.citation,
            "title": ref.title,
            "kind": ref.kind.value,
            "doi": ref.doi,
            "arxiv_id": ref.arxiv_id,
            "pdf_urls": list(ref.pdf_urls),
        }
        items.append({k: v for k, v in item.items() if v})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    logger.info("saved references file=%s count=%d", path.name, len(refs))


REFERENCE_LIST_NAMES = ("references.txt", "references.md", "references.json")


def find_reference_list(folder: Path) -> Path | None:
    """Pick the reference list in the input folder.

    A pasted APA list (`references.txt` / `references.md`) wins over a converted `references.json`.

    Args:
        folder: Input folder, usually `DATA_DIR/input`.

    Returns:
        The first existing file in `REFERENCE_LIST_NAMES` order, or None.
    """
    return next((folder / name for name in REFERENCE_LIST_NAMES if (folder / name).is_file()), None)
