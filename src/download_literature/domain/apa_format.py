"""APA 7th edition reference formatting (pure, no I/O).

Builds the reference-list entry from `WorkMeta`: authors, date, title, source and DOI, for journal
articles, conference papers, book chapters, books and preprints. Italics are written in Markdown
(`*...*`). Titles from metadata services are converted to sentence case; a title the user typed
(already APA-cased) can be passed instead. Editors of edited books are not available from Crossref
and are omitted.
"""

from __future__ import annotations

import re

from download_literature.domain.apa import ApaEntry
from download_literature.domain.literature import ReferenceKind, WorkMeta, has_cjk

_SENTENCE_BREAK = (":", "?", "!", ".")


def _initials(given: str) -> str:
    """Turn given names into APA initials.

    Args:
        given: Given names such as `Thomas L.` or `Yu-Chen`.

    Returns:
        Initials such as `T. L.` or `Y.-C.`.
    """
    parts = []
    for name in given.replace(".", " ").split():
        parts.append("-".join(f"{piece[0]}." for piece in name.split("-") if piece))
    return " ".join(parts)


def _author(family: str, given: str) -> str:
    """Format one author.

    Args:
        family: Family name (or group name).
        given: Given names; empty for a group author.

    Returns:
        `Family, G. N.` or the group name.
    """
    if not given.strip():
        return family
    if family.isupper() and len(family) > 1:  # some records store surnames in capitals ("NEFF")
        family = family.title()
    return f"{family}, {_initials(given)}"


def format_authors(authors: tuple[tuple[str, str], ...]) -> str:
    """Format an APA 7 author list (up to 20 names; 21+ → first 19, ellipsis, last).

    Args:
        authors: (family, given) pairs.

    Returns:
        The author part without the trailing period.
    """
    names = [_author(f, g) for f, g in authors]
    if len(names) > 20:
        return ", ".join(names[:19]) + ", . . . " + names[-1]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _case_word(word: str, capitalise: bool) -> str:
    """Apply sentence case to one word.

    Args:
        word: Word, possibly hyphenated or with punctuation.
        capitalise: Whether the word starts a sentence or subtitle.

    Returns:
        The word with case adjusted; acronyms, mixed-case names and words with digits are kept.
    """
    pieces = word.split("-")
    out = []
    for i, piece in enumerate(pieces):
        letters = re.sub(r"[^A-Za-z]", "", piece)
        keep = any(c.isdigit() for c in piece) or sum(c.isupper() for c in letters) > 1 or piece == "I"
        if keep:
            out.append(piece)
        elif capitalise and i == 0:
            out.append(piece[:1].upper() + piece[1:].lower())
        else:
            out.append(piece.lower())
    return "-".join(out)


def sentence_case(title: str) -> str:
    """Convert a title to APA sentence case.

    The first word and the first word after a colon, question or exclamation mark are capitalised.
    Acronyms (AI), mixed-case names (ChatGPT) and words with digits (COVID-19) keep their case.
    Proper nouns cannot be detected and become lower case.

    Args:
        title: Title in any case.

    Returns:
        Sentence-case title.
    """
    words = title.split()
    out = []
    for i, word in enumerate(words):
        starts = i == 0 or words[i - 1].endswith(_SENTENCE_BREAK)
        out.append(_case_word(word, starts))
    return " ".join(out)


def _pages(pages: str) -> str:
    """Use an en dash in page ranges.

    Args:
        pages: Page range such as `775-808`.

    Returns:
        `775–808`.
    """
    return re.sub(r"\s*[-–—]\s*", "–", pages.strip())


def _end(text: str) -> str:
    """End a reference element with a period unless it already ends with ? or !.

    Args:
        text: Element text.

    Returns:
        Text ending in punctuation.
    """
    return text if text.endswith(("?", "!", ".")) else f"{text}."


def _source(meta: WorkMeta) -> str:
    """Build the source part (journal, proceedings, book or repository).

    Args:
        meta: Work metadata.

    Returns:
        Source text including its final period, or empty.
    """
    if meta.genre in ("book", "monograph", "edited-book"):
        return f"{meta.publisher}." if meta.publisher else ""
    if meta.genre == "preprint":
        return f"{meta.container or 'Preprint server'}."
    if meta.genre in ("book-chapter", "proceedings-article"):
        container = sentence_case(meta.container) if meta.genre == "book-chapter" else meta.container
        details = [f"Vol. {meta.volume}"] if meta.volume and meta.genre == "book-chapter" else []
        details += [f"pp. {_pages(meta.pages)}"] if meta.pages else []
        detail_text = f" ({', '.join(details)})" if details else ""
        publisher = f" {meta.publisher}." if meta.publisher else ""
        return f"In *{container}*{detail_text}.{publisher}" if container else publisher.strip()
    journal = meta.container + (f", {meta.volume}" if meta.volume else "")
    text = f"*{journal}*" + (f"({meta.issue})" if meta.issue else "")
    if meta.article_number:
        text += f", Article {meta.article_number}"
    elif meta.pages:
        text += f", {_pages(meta.pages)}"
    return f"{text}." if meta.container else ""


def _chinese_source(meta: WorkMeta) -> str:
    """Build the source part of a Chinese reference (full-width punctuation).

    Args:
        meta: Work metadata.

    Returns:
        Source text ending in '。', or empty.
    """
    if meta.genre in ("book", "monograph", "edited-book"):
        return f"{meta.publisher}。" if meta.publisher else ""
    if meta.genre == "book-chapter":
        pages = f"（頁{_pages(meta.pages)}）" if meta.pages else ""
        return f"載於{meta.container}{pages}。" + (f"{meta.publisher}。" if meta.publisher else "")
    if not meta.container:
        return ""
    journal = meta.container + (f"，{meta.volume}" if meta.volume else "")
    text = f"*{journal}*" + (f"({meta.issue})" if meta.issue else "")
    text += f"，{_pages(meta.pages)}" if meta.pages else ""
    return f"{text}。"


def format_apa_chinese(meta: WorkMeta, title: str = "") -> str:
    """Format a Chinese reference in APA 7 (Taiwan) style: names joined with '、', full-width punctuation.

    Args:
        meta: Work metadata.
        title: Title to use instead of the metadata title.

    Returns:
        One reference in Markdown.
    """
    authors = "、".join(f for f, _ in meta.authors) or meta.first_author
    year = str(meta.year) if meta.year else "無日期"
    shown = (title or meta.title).rstrip("。.")
    book = meta.genre in ("book", "monograph", "edited-book")
    title_part = f"*{shown}*。" if book else f"{shown}。"
    link = f"https://doi.org/{meta.doi}" if meta.doi else ""
    return f"{authors}（{year}）。{title_part}{_chinese_source(meta)}{link}"


def format_apa(meta: WorkMeta, title: str = "") -> str:
    """Format an APA 7 reference-list entry.

    Args:
        meta: Work metadata.
        title: Title to use instead of the sentence-cased metadata title (e.g. as typed by the user).

    Returns:
        One reference in Markdown (italics as `*...*`).
    """
    if has_cjk(title or meta.title):
        return format_apa_chinese(meta, title)
    authors = format_authors(meta.authors) or meta.first_author
    year = str(meta.year) if meta.year else "n.d."
    shown = title or sentence_case(meta.title)
    italic_title = meta.genre in ("book", "monograph", "edited-book", "preprint")
    if italic_title:
        edition = f" ({meta.edition})" if meta.edition else ""
        label = " [Preprint]" if meta.genre == "preprint" else ""
        title_part = f"*{shown.rstrip('.')}*{edition}{label}."
    else:
        title_part = _end(shown)
    parts = [_end(authors) if authors else "", f"({year}).", title_part, _source(meta)]
    if meta.doi:
        parts.append(f"https://doi.org/{meta.doi}")
    return " ".join(p for p in parts if p)


def format_entry(entry: ApaEntry) -> str:
    """Re-write a parsed APA entry that no database could confirm (e.g. an older book).

    Args:
        entry: Parsed user entry.

    Returns:
        APA text built from the entry's own parts; book titles are italic.
    """
    if has_cjk(entry.title):
        year = f"（{entry.year}）。" if entry.year else "（無日期）。"
        title = f"*{entry.title}*。" if entry.kind_hint is ReferenceKind.BOOK else f"{entry.title}。"
        link = f"https://doi.org/{entry.doi}" if entry.doi else " ".join(entry.urls)
        return f"{entry.authors_text}{year}{title}{entry.source_text}{link}"
    year = f"({entry.year})." if entry.year else "(n.d.)."
    title = f"*{entry.title}*." if entry.kind_hint is ReferenceKind.BOOK else _end(entry.title)
    link = f"https://doi.org/{entry.doi}" if entry.doi else " ".join(entry.urls)
    parts = [_end(entry.authors_text) if entry.authors_text else "", year, title, entry.source_text, link]
    return " ".join(p for p in parts if p)
