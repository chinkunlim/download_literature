"""Combined metadata resolver: asks several services in order (Crossref first, then OpenAlex).

Crossref has the richest bibliographic data for published works; OpenAlex also covers DataCite DOIs
(arXiv preprints) and finds works from a bare title. One failing service does not stop the others.
"""

from __future__ import annotations

import logging
from typing import Protocol

from download_literature.domain.literature import SourceError, WorkMeta

logger = logging.getLogger(__name__)


class _Resolver(Protocol):
    """One metadata service."""

    def by_doi(self, doi: str) -> WorkMeta | None:
        """Look up a DOI.

        Args:
            doi: DOI without prefix.

        Returns:
            The work, or None.
        """
        ...

    def search(self, citation: str) -> list[WorkMeta]:
        """Search by text.

        Args:
            citation: Citation or title text.

        Returns:
            Matches, unverified.
        """
        ...


class CombinedResolver:
    """Tries metadata services in order."""

    def __init__(self, resolvers: list[_Resolver]) -> None:
        """Create the resolver.

        Args:
            resolvers: Services in preference order (e.g. Crossref, OpenAlex).
        """
        self._resolvers = resolvers

    def by_doi(self, doi: str) -> WorkMeta | None:
        """Look up a DOI in each service until one knows it.

        Args:
            doi: DOI without prefix.

        Returns:
            The first record found, or None.

        Raises:
            SourceError: When every service failed.
        """
        errors = 0
        for resolver in self._resolvers:
            try:
                work = resolver.by_doi(doi)
            except SourceError as exc:
                logger.warning("metadata by_doi failed service=%s: %s", type(resolver).__name__, exc)
                errors += 1
                continue
            if work is not None:
                return work
        if errors == len(self._resolvers):
            raise SourceError("all metadata services failed")
        return None

    def search(self, citation: str) -> list[WorkMeta]:
        """Search every service and merge the results (first service's results first, no duplicate DOIs).

        Args:
            citation: Citation or title text.

        Returns:
            Merged matches.

        Raises:
            SourceError: When every service failed.
        """
        merged: list[WorkMeta] = []
        seen: set[str] = set()
        errors = 0
        for resolver in self._resolvers:
            try:
                works = resolver.search(citation)
            except SourceError as exc:
                logger.warning("metadata search failed service=%s: %s", type(resolver).__name__, exc)
                errors += 1
                continue
            for work in works:
                ident = work.doi.lower() or work.title.lower()
                if ident not in seen:
                    seen.add(ident)
                    merged.append(work)
        if errors == len(self._resolvers):
            raise SourceError("all metadata services failed")
        return merged
