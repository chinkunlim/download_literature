"""APA 7 reference parsing (pure, no I/O).

Turns a pasted reference list (plain text or Markdown, one reference per paragraph) into
structured entries: first author, year, title, DOI, arXiv id, other URLs and a guess of the kind.
The guess is confirmed later against Crossref by `services.reference_builder`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from download_literature.domain.literature import ReferenceKind

_YEAR = re.compile(r"\((?:(\d{4})[a-z]?(?:,[^)]*)?|n\.\s?d\.|in press)\)\.?", re.IGNORECASE)
_DOI = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|\bdoi:\s*)(10\.\d{4,9}/\S+)|\b(10\.\d{4,9}/\S+)", re.IGNORECASE
)
_ARXIV = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|\barXiv:\s*)(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"]+")
_BULLET = re.compile(r"^(?:[-*+•]|\d+[.)])\s+")
_MD_LINK = re.compile(r"\[([^\]]*)\]\((\S+?)\)")
_UNDERSCORE_EMPHASIS = re.compile(r"(?<![\w/])_([^_\n]+?)_(?![\w/])")
_SENTENCE_END = re.compile(r"[.?!](?=\s|$)")
_NUMBERS = re.compile(r"\d+\s*\(\d+\)|\d+\s*[–-]\s*\d+|,\s*\d+\s*[,.]")
_NOT_SENTENCE_END = {"Vol", "vol", "pp", "p", "Ed", "Eds", "No", "no", "ed", "eds"}


@dataclass(frozen=True)
class ApaEntry:
    """One parsed APA reference.

    Attributes:
        raw: The reference text after Markdown clean-up.
        first_author: Family name of the first author (or the group author).
        year: Publication year; None for `n.d.` / `in press`.
        title: Work title without trailing period or bracketed description.
        doi: DOI without prefix; empty when none is written.
        arxiv_id: arXiv identifier without version; empty when none.
        urls: Other URLs in the entry (not doi.org / arxiv.org).
        kind_hint: Article, chapter or book, guessed from the text after the title.
    """

    raw: str
    first_author: str
    year: int | None
    title: str
    doi: str
    arxiv_id: str
    urls: tuple[str, ...]
    kind_hint: ReferenceKind


def _clean_line(line: str) -> str:
    """Remove Markdown list markers, emphasis and link syntax from one line.

    Args:
        line: Raw line.

    Returns:
        Plain text with single spaces.
    """
    text = _BULLET.sub("", line.strip())
    text = _MD_LINK.sub(
        lambda m: m.group(2) if m.group(1).startswith("http") else f"{m.group(1)} {m.group(2)}", text
    )
    text = text.replace("*", "")
    text = _UNDERSCORE_EMPHASIS.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def split_entries(text: str) -> list[str]:
    """Split a pasted reference list into one string per reference.

    A line containing an APA date such as `(2019).` starts a new reference; other lines continue the
    previous one (wrapped text). Markdown headings and text before the first reference are dropped.

    Args:
        text: Whole reference list.

    Returns:
        Cleaned reference strings in order.
    """
    entries: list[str] = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        line = _clean_line(raw)
        if not line:
            continue
        if _YEAR.search(line):
            entries.append(line)
        elif entries:
            entries[-1] = f"{entries[-1]} {line}"
    return entries


def _strip_trailing(value: str) -> str:
    """Drop punctuation that ends a sentence but is not part of an identifier.

    Args:
        value: DOI or URL as found in text.

    Returns:
        The value without trailing `.,;` and without an unbalanced closing parenthesis.
    """
    value = value.rstrip(".,;")
    if value.endswith(")") and value.count("(") < value.count(")"):
        value = value[:-1].rstrip(".,;")
    return value


def find_doi(text: str) -> str:
    """Find the DOI written in an entry.

    Args:
        text: Reference text.

    Returns:
        DOI without prefix, or empty.
    """
    match = _DOI.search(text)
    return _strip_trailing(match.group(1) or match.group(2)) if match else ""


def _split_title(rest: str) -> tuple[str, str]:
    """Split the text after the date into title and source.

    The title ends at the first `.`, `?` or `!` followed by a space, unless the period belongs to an
    initial or an abbreviation such as `Vol.`.

    Args:
        rest: Text after the `(year).` part, with URLs removed.

    Returns:
        (title, remainder).
    """
    for match in _SENTENCE_END.finditer(rest):
        pos = match.start()
        if rest[pos] == ".":
            token = rest[:pos].rsplit(" ", 1)[-1]
            if re.fullmatch(r"[A-Z]", token) or token in _NOT_SENTENCE_END:
                continue
        end = pos if rest[pos] == "." else pos + 1
        return rest[:end], rest[pos + 1 :]
    return rest.rstrip("."), ""


def _kind_hint(remainder: str, has_identifier: bool) -> ReferenceKind:
    """Guess the kind of work from the text after the title.

    Args:
        remainder: Source part (journal, book publisher, "In ..." for chapters).
        has_identifier: Whether a DOI or arXiv id was found.

    Returns:
        CHAPTER for "In ...", ARTICLE for volume / page numbers or identifiers, BOOK for a bare publisher.
    """
    source = remainder.strip()
    if source.startswith("In "):
        return ReferenceKind.CHAPTER
    if has_identifier or _NUMBERS.search(source) or not source:
        return ReferenceKind.ARTICLE
    return ReferenceKind.BOOK


def parse_apa(text: str) -> ApaEntry:
    """Parse one APA 7 reference.

    Args:
        text: One reference (already cleaned by `split_entries`, or plain text).

    Returns:
        The parsed entry.

    Raises:
        ValueError: When no APA date like `(2019)` or `(n.d.)` is found.
    """
    raw = _clean_line(text)
    date = _YEAR.search(raw)
    if date is None:
        raise ValueError("no APA date such as (2019) found")
    authors = raw[: date.start()].strip()
    doi = find_doi(raw)
    arxiv = _ARXIV.search(raw)
    urls = [_strip_trailing(u) for u in _URL.findall(raw)]
    other_urls = tuple(u for u in urls if "doi.org/" not in u and "arxiv.org/" not in u)
    rest = _URL.sub("", raw[date.end() :])
    rest = re.sub(r"\bdoi:\s*\S+", "", rest, flags=re.IGNORECASE).strip()
    title, remainder = _split_title(rest)
    title = re.sub(r"\s*\[[^\]]*\]\s*$", "", title).strip()
    return ApaEntry(
        raw=raw,
        first_author=authors.split(",")[0].strip().rstrip("."),
        year=int(date.group(1)) if date.group(1) else None,
        title=title,
        doi=doi,
        arxiv_id=arxiv.group(1) if arxiv else "",
        urls=other_urls,
        kind_hint=_kind_hint(remainder, bool(doi or arxiv)),
    )
