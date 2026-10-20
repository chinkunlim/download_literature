"""PDF text adapter: extracts first-page text with pypdf for the wrong-paper check."""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PyPdfError

logger = logging.getLogger(__name__)
# pypdf warns about every font it cannot fully decode; that noise does not affect title checks
logging.getLogger("pypdf").setLevel(logging.ERROR)


class PypdfTextReader:
    """Reads the text layer of the first pages of a PDF."""

    def __init__(self, pages: int = 2) -> None:
        """Create the reader.

        Args:
            pages: How many leading pages to read (cover pages often come first).
        """
        self._pages = pages

    def first_pages_text(self, data: bytes) -> str:
        """Extract text from the first pages.

        Args:
            data: PDF content.

        Returns:
            Extracted text; empty when the PDF has no text layer or cannot be parsed.
        """
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages[: self._pages])
        except (PyPdfError, ValueError, KeyError, TypeError) as exc:
            logger.warning("pdf text extraction failed: %s", exc)
            return ""
