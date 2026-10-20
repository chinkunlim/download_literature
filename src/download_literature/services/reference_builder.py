"""Reference-list conversion: APA text → verified `Reference` objects (ADR-002).

Each entry is parsed, then confirmed on a metadata service (Crossref): a written DOI is looked up,
a missing DOI is searched and only accepted when title and year agree. Problems become notes for
the report instead of stopping the batch.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from download_literature.domain.apa import ApaEntry, find_doi, parse_apa
from download_literature.domain.apa_format import format_apa, format_entry
from download_literature.domain.literature import (
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
    "your",
    "my",
    "our",
    "their",
    "his",
    "her",
    "its",
}
_YEAR_IN_TEXT = re.compile(r"\b(19|20)\d{2}\b")
FREE_TEXT_NOTE = "matched by title search; check the APA entry"


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
        author=work.first_author if work and work.first_author else entry.first_author,
    )


@dataclass(frozen=True)
class Resolution:
    """Result of resolving one input line.

    Attributes:
        input: The line as the user wrote it.
        reference: Reference to download, or None when the work could not be identified.
        work: Confirmed metadata, or None.
        apa: APA 7 reference (from metadata; the input text when nothing was found).
        note: What the user should check; empty when all is well.
    """

    input: str
    reference: Reference | None
    work: WorkMeta | None
    apa: str
    note: str


def _keywords(text: str) -> list[str]:
    """Lower-case ASCII words of four or more letters.

    Args:
        text: Any text.

    Returns:
        Keywords in order.
    """
    return [w for w in re.findall(r"[a-z0-9]+", _ascii(text).lower()) if len(w) >= 4]


def match_free_text(text: str, works: list[WorkMeta]) -> WorkMeta | None:
    """Pick the work a title-only / author+title input refers to.

    Accepted when at least 80% of the input's keywords (author names and years removed) are in the title,
    the year (if written) is within one year, and either most of the title was given or an author's
    family name appears in the input. A record holding only its main title is accepted when all of it
    appears in the input together with an author's name and a matching year.

    Args:
        text: User input such as `Kosmyna — Your Brain on ChatGPT`.
        works: Search results in ranking order.

    Returns:
        The first acceptable work, or None.
    """
    year = _YEAR_IN_TEXT.search(text)
    for work in works:
        surnames = {_ascii(f).lower() for f, _ in work.authors}
        words = [w for w in _keywords(text) if w not in surnames and not w.isdigit()]
        title_words = set(_keywords(work.title))
        if not words or not title_words:
            continue
        joined = "".join(_keywords(work.title))
        input_cover = sum(1 for w in words if w in title_words or w in joined) / len(words)
        title_cover = len(title_words & set(words)) / len(title_words)
        has_author = any(name and name in _ascii(text).lower() for name in surnames)
        year_ok = not year or work.year is None or abs(int(year.group(0)) - work.year) <= 1
        if input_cover >= 0.8 and year_ok and (title_cover >= 0.5 or has_author):
            return work
        # Crossref may hold only the main title (e.g. "Self-Distancing"): accept it when the whole record
        # title is in the input and author and a written year confirm it
        if title_cover == 1.0 and has_author and year is not None and year_ok:
            return work
    return None


def _arxiv_id(doi: str) -> str:
    """Get the arXiv id from an arXiv DataCite DOI.

    Args:
        doi: DOI such as `10.48550/arXiv.2506.08872`.

    Returns:
        `2506.08872`, or empty for other DOIs.
    """
    match = re.match(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", doi, re.IGNORECASE)
    return match.group(1) if match else ""


def _from_work(text: str, work: WorkMeta, taken: set[str], note: str) -> Resolution:
    """Build a resolution from confirmed metadata alone.

    Args:
        text: User input.
        work: Confirmed metadata.
        taken: Keys already used.
        note: Note for the user.

    Returns:
        The resolution with an APA entry from the metadata.
    """
    apa = format_apa(work)
    ref = Reference(
        key=make_key(work.first_author, work.year, work.title, taken),
        citation=apa,
        doi=work.doi,
        kind=work.kind,
        arxiv_id=_arxiv_id(work.doi),
        title=work.title,
        author=work.first_author,
    )
    return Resolution(text, ref, work, apa, note)


def _resolve_free_text(text: str, resolver: WorkResolver, taken: set[str]) -> Resolution:
    """Resolve an input that is not an APA reference (title, author + title, or a bare DOI).

    Args:
        text: User input.
        resolver: Metadata service.
        taken: Keys already used.

    Returns:
        The resolution.
    """
    doi = find_doi(text)
    try:
        work = resolver.by_doi(doi) if doi else match_free_text(text, resolver.search(text))
    except SourceError as exc:
        return Resolution(text, None, None, text, f"metadata lookup failed ({exc}); run again later")
    if work is None:
        return Resolution(text, None, None, text, "not found by title search; add authors, year or a DOI")
    return _from_work(text, work, taken, "" if doi else FREE_TEXT_NOTE)


def resolve_entry(text: str, resolver: WorkResolver, taken: set[str]) -> Resolution:
    """Resolve one input line: an APA reference, a title, author + title, or a DOI.

    Args:
        text: One line from the user's list.
        resolver: Metadata service (Crossref + OpenAlex).
        taken: Keys already used; the new key is added.

    Returns:
        The resolution (reference, APA 7 text and a note).
    """
    try:
        entry = parse_apa(text)
    except ValueError:
        return _resolve_free_text(text, resolver, taken)
    work, note = _confirm(entry, resolver)
    ref = _to_reference(entry, work, taken)
    apa = format_apa(work, title=entry.title) if work else format_entry(entry)
    return Resolution(entry.raw, ref, work, apa, note)
