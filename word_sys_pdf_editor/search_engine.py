from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import pymupdf as fitz


@dataclass
class SearchMatch:
    """Represents a text hit located within a PDF document."""
    page_index: int
    bbox: Tuple[float, float, float, float]
    text: str

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        return self.bbox


class DocumentSearchEngine:
    """Fast in-memory text search engine navigating through digital and OCR-recognized text."""

    def __init__(self, doc: Optional[fitz.Document] = None):
        self.doc: Optional[fitz.Document] = doc
        self.query: str = ""
        self.case_sensitive: bool = False
        self.matches: List[SearchMatch] = []
        self.current_match_index: int = -1

    def set_document(self, doc: Optional[fitz.Document]):
        """Bind search engine to a new or reloaded document session."""
        if self.doc != doc:
            self.doc = doc
            self.clear()

    def clear(self):
        """Reset search query and clear all cached search hits."""
        self.query = ""
        self.matches.clear()
        self.current_match_index = -1

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def current_index(self) -> int:
        return self.current_match_index

    def search(self, doc_or_query: Any, query: Optional[str] = None, case_sensitive: bool = False) -> List[SearchMatch]:
        """Search entire document across visible text and invisible OCR render mode 3 layers."""
        if query is not None or not isinstance(doc_or_query, str):
            self.doc = doc_or_query
            actual_query = query or ""
        else:
            actual_query = doc_or_query

        self.query = actual_query.strip() if actual_query else ""
        self.case_sensitive = case_sensitive
        self.matches.clear()
        self.current_match_index = -1

        if not self.doc or not self.query or len(self.doc) == 0:
            return self.matches

        for page_idx in range(len(self.doc)):
            try:
                page = self.doc[page_idx]
                hits = page.search_for(self.query)
                if not hits:
                    continue

                for hit in hits:
                    if self.case_sensitive:
                        try:
                            extracted = page.get_text("text", clip=hit).strip()
                            if self.query not in extracted:
                                continue
                        except Exception:
                            pass

                    match = SearchMatch(
                        page_index=page_idx,
                        bbox=(hit.x0, hit.y0, hit.x1, hit.y1),
                        text=self.query,
                    )
                    self.matches.append(match)
            except Exception as err:
                print(f"Warning: search failed on page {page_idx}: {err}")

        if self.matches:
            self.current_match_index = 0

        return self.matches

    def find_nearest_match(self, page_index: int = 0, y_offset: float = 0.0, current_page: Optional[int] = None) -> Optional[SearchMatch]:
        """Find match closest to given page and vertical scroll offset."""
        if current_page is not None:
            page_index = current_page

        if not self.matches:
            self.current_match_index = -1
            return None

        for idx, match in enumerate(self.matches):
            if match.page_index == page_index and match.bbox[1] >= y_offset:
                self.current_match_index = idx
                return match
            elif match.page_index > page_index:
                self.current_match_index = idx
                return match

        self.current_match_index = 0
        return self.matches[0]

    def get_current_match(self) -> Optional[SearchMatch]:
        """Return the currently focused match object."""
        if 0 <= self.current_match_index < len(self.matches):
            return self.matches[self.current_match_index]
        return None

    def next_match(self) -> Optional[SearchMatch]:
        """Advance to next match with circular wrap-around."""
        if not self.matches:
            return None
        self.current_match_index = (self.current_match_index + 1) % len(self.matches)
        return self.matches[self.current_match_index]

    def prev_match(self) -> Optional[SearchMatch]:
        """Retreat to previous match with circular wrap-around."""
        if not self.matches:
            return None
        self.current_match_index = (self.current_match_index - 1) % len(self.matches)
        return self.matches[self.current_match_index]

    def get_matches_for_page(self, page_index: int) -> List[SearchMatch]:
        """Return all match hits located on the specified page index."""
        if not self.matches:
            return []
        return [m for m in self.matches if m.page_index == page_index]

