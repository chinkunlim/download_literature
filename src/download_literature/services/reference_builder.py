"""Reference-list conversion: APA text → verified `Reference` objects (ADR-002).

Each entry is parsed, then confirmed on a metadata service (Crossref): a written DOI is looked up,
a missing DOI is searched and only accepted when title and year agree. Problems become notes for
the report instead of stopping the batch.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import replace
from typing import Protocol

from download_literature.domain.apa import ApaEntry, parse_apa
from download_literature.domain.literature import (
    ConversionNote,
    Reference,
    ReferenceKind,
    SourceError,
    WorkMeta,
    title_matches,
)

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "in",
    "on",
    "for",
    "to",
    "with",
    "from",
    "by",
    "at",
    "as",
    "is",
}


class WorkResolver(Protocol):
    """Looks up bibliographic metadata."""

    def by_doi(self, doi: str) -> WorkMeta | None:
        """Look up a DOI.

        Args:
            doi: DOI without prefix.

        Returns:
            The work, or None when unknown.
        """
        ...

    def search(self, citation: str) -> list[WorkMeta]:
        """Search by citation text.

        Args:
            citation: Reference text.

        Returns:
            Best matches, unverified.
        """
        ...


def _ascii(text: str) -> str:
    """Fold accents to ASCII.

    Args:
        text: Any text.

    Returns:
        ASCII-only text.
    """
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def make_key(first_author: str, year: int | None, title: str, taken: set[str]) -> str:
    """Build a unique, file-name-safe key such as `Gross_1998_EmergingField`.

    Args:
        first_author: First author's family name.
        year: Publication year; None becomes `nd`.
        title: Title; its first two non-stopwords are used.
        taken: Keys already used; the new key is added to it.

    Returns:
        The new key (suffixed `_b`, `_c`, ... on collision).
    """
    author = re.sub(r"[^A-Za-z-]", "", _ascii(first_author)) or "Anon"
    words = [w for w in re.findall(r"[A-Za-z0-9]+", _ascii(title)) if w.lower() not in _STOPWORDS]
    base = f"{author}_{year or 'nd'}_{''.join(w.capitalize() for w in words[:2])}".rstrip("_")
    key, suffix = base, ord("b")
    while key in taken:
        key, suffix = f"{base}_{chr(suffix)}", suffix + 1
    taken.add(key)
    return key


def _authors_match(entry: ApaEntry, work: WorkMeta) -> bool | None:
    """Compare first authors.

    Args:
        entry: Parsed citation.
        work: Candidate record.

    Returns:
        True / False when both names are known, None when either is missing.
    """
    cited, found = _ascii(entry.first_author).lower(), _ascii(work.first_author).lower()
    if not cited or not found:
        return None
    return cited in found or found in cited


def _titles_agree(entry: ApaEntry, work: WorkMeta, same_author: bool | None) -> bool:
    """Compare titles, allowing Crossref's main-title-only records.

    Args:
        entry: Parsed citation.
        work: Candidate record.
        same_author: Result of `_authors_match`.

    Returns:
        True when the titles agree both ways, or when the candidate's (shorter) title has at least three
        words that all appear in the cited title and the first author is confirmed.
    """
    if title_matches(entry.title, work.title, 0.8) and title_matches(work.title, entry.title, 0.8):
        return True
    short_title_words = [w for w in re.findall(r"[a-z0-9]+", work.title.lower()) if len(w) >= 4]
    return bool(same_author) and len(short_title_words) >= 3 and title_matches(work.title, entry.title, 1.0)


def _same_work(entry: ApaEntry, work: WorkMeta) -> bool:
    """Check that a search hit is the cited work.

    Args:
        entry: Parsed citation.
        work: Candidate from the metadata service.

    Returns:
        True when the titles agree (see `_titles_agree`), the year is within one year, the first
        authors do not differ (a commentary quoting the title has another author), and a cited book is
        not matched to a journal article (such as a book review).
    """
    same_author = _authors_match(entry, work)
    year_ok = entry.year is None or work.year is None or abs(entry.year - work.year) <= 1
    kind_ok = not (entry.kind_hint is ReferenceKind.BOOK and work.kind is ReferenceKind.ARTICLE)
    return same_author is not False and year_ok and kind_ok and _titles_agree(entry, work, same_author)


def _confirm(entry: ApaEntry, resolver: WorkResolver) -> tuple[WorkMeta | None, str]:
    """Find the metadata record for an entry.

    Args:
        entry: Parsed citation.
        resolver: Metadata service.

    Returns:
        (work or None, note text or empty).
    """
    try:
        if entry.doi:
            work = resolver.by_doi(entry.doi)
            if work is None:
                return None, f"DOI {entry.doi} not found on Crossref; check the DOI"
            if not (
                title_matches(entry.title, work.title, 0.6) or title_matches(work.title, entry.title, 0.8)
            ):
                return work, f"DOI title differs from the citation: {work.title!r}"
            return work, ""
        hits = [w for w in resolver.search(entry.raw) if _same_work(entry, w)]
    except SourceError as exc:
        return None, f"metadata lookup failed ({exc}); using the citation as written"
    if hits:
        return hits[0], ""
    if entry.kind_hint is ReferenceKind.BOOK or entry.arxiv_id or entry.urls:
        return None, ""
    return None, "no DOI found; check the citation or add a URL"


def _to_reference(entry: ApaEntry, work: WorkMeta | None, taken: set[str]) -> Reference:
    """Combine a parsed entry and its metadata into a Reference.

    Args:
        entry: Parsed citation.
        work: Confirmed metadata, or None.
        taken: Keys already used.

    Returns:
        The reference (Crossref title and kind preferred when confirmed).
    """
    # Crossref may store only the main title (e.g. "Self-Distancing"); keep the fuller citation title then
    agree = (
        work is not None
        and title_matches(entry.title, work.title, 0.8)
        and title_matches(work.title, entry.title, 0.8)
    )
    title = work.title if work is not None and agree else entry.title
    return Reference(
        key=make_key(entry.first_author, entry.year, entry.title, taken),
        citation=entry.raw,
        doi=work.doi if work else entry.doi,
        kind=work.kind if work else entry.kind_hint,
        arxiv_id=entry.arxiv_id,
        pdf_urls=entry.urls,
        title=title,
    )


def build_references(
    entries: list[str], resolver: WorkResolver
) -> tuple[list[Reference], list[ConversionNote]]:
    """Convert APA entries into references, confirming each one on the metadata service.

    Args:
        entries: Reference strings from `domain.apa.split_entries`.
        resolver: Metadata service (e.g. Crossref).

    Returns:
        (references in list order, notes for entries that need a human look).
    """
    refs: list[Reference] = []
    notes: list[ConversionNote] = []
    taken: set[str] = set()
    for text in entries:
        try:
            entry = parse_apa(text)
        except ValueError as exc:
            notes.append(ConversionNote(text, f"could not parse: {exc}"))
            continue
        work, note = _confirm(entry, resolver)
        refs.append(_to_reference(entry, work, taken))
        if note:
            notes.append(ConversionNote(entry.raw, note))
    logger.info("converted references count=%d notes=%d", len(refs), len(notes))
    return refs, notes


def _identity(ref: Reference) -> list[str]:
    """Return the ids used to recognise the same work across conversions.

    Args:
        ref: Reference.

    Returns:
        Lower-case DOI (if any) and normalised title (if any).
    """
    ids = [f"doi:{ref.doi.lower()}"] if ref.doi else []
    words = re.findall(r"[a-z0-9]+", ref.title.lower())
    return ids + ([f"title:{' '.join(words)}"] if words else [])


def merge_with_existing(new: list[Reference], old: list[Reference]) -> list[Reference]:
    """Keep keys and manual edits from a previous conversion of the same list.

    The new list decides which works are included and their order. For a work already in the old
    list (same DOI or title) the old key, kind, title and extra URLs are kept, so downloaded files
    and hand-made fixes survive.

    Args:
        new: Freshly converted references.
        old: References from the existing JSON file.

    Returns:
        Merged references with unique keys.
    """
    index = {ident: ref for ref in old for ident in _identity(ref)}
    merged: list[Reference] = []
    used: set[str] = set()
    for ref in new:
        prev = next((index[i] for i in _identity(ref) if i in index), None)
        if prev is not None and prev.key not in used:
            urls = tuple(dict.fromkeys(prev.pdf_urls + ref.pdf_urls))
            ref = replace(
                ref,
                key=prev.key,
                kind=prev.kind,
                title=prev.title or ref.title,
                pdf_urls=urls,
                doi=ref.doi or prev.doi,
                arxiv_id=ref.arxiv_id or prev.arxiv_id,
            )
        if ref.key in used:
            ref = replace(ref, key=make_key(ref.key, None, "", used))
        used.add(ref.key)
        merged.append(ref)
    return merged
