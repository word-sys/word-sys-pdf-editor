from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
import pymupdf as fitz


PII_PATTERNS = {
    "ssn": {
        "id": "ssn",
        "label_key": "pii_pattern_ssn",
        "default_label": "Social Security Number (SSN)",
        "regex": r"\b\d{3}-\d{2}-\d{4}\b",
    },
    "credit_card": {
        "id": "credit_card",
        "label_key": "pii_pattern_credit_card",
        "default_label": "Credit Card Number",
        "regex": r"\b(?:\d{4}[ -]?){3}\d{4}\b",
    },
    "email": {
        "id": "email",
        "label_key": "pii_pattern_email",
        "default_label": "Email Address",
        "regex": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    },
    "phone": {
        "id": "phone",
        "label_key": "pii_pattern_phone",
        "default_label": "Phone Number",
        "regex": r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    },
    "date": {
        "id": "date",
        "label_key": "pii_pattern_date",
        "default_label": "Date",
        "regex": r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
    },
}


def _normalize_text_for_search(text: str) -> str:
    """Normalize text by stripping diacritics and handling special cases like Turkish dotted I."""
    text = text.replace('İ', 'I').replace('ı', 'i')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


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
        self.whole_word: bool = False
        self.matches: List[SearchMatch] = []
        self.current_match_index: int = -1
        self.last_wrapped: bool = False

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
        self.last_wrapped = False

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def current_index(self) -> int:
        return self.current_match_index

    def search(
        self,
        doc_or_query: Any,
        query: Optional[str] = None,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> List[SearchMatch]:
        """Search entire document across visible text and invisible OCR render mode 3 layers."""
        if query is not None or not isinstance(doc_or_query, str):
            self.doc = doc_or_query
            actual_query = query or ""
        else:
            actual_query = doc_or_query

        self.query = actual_query.strip() if actual_query else ""
        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.matches.clear()
        self.current_match_index = -1
        self.last_wrapped = False

        if not self.doc or getattr(self.doc, "is_closed", False) or not self.query or len(self.doc) == 0:
            return self.matches

        for page_idx in range(len(self.doc)):
            try:
                page = self.doc[page_idx]
                hits = page.search_for(self.query)
                accent_fallback_used = False
                if not hits and not self.case_sensitive:
                    norm_query = _normalize_text_for_search(self.query).lower()
                    words = page.get_text("words")
                    for w in words:
                        w_text = w[4]
                        clean_w = w_text.strip(".,;:!?()[]{}\"'“”‘’—")
                        norm_w = _normalize_text_for_search(clean_w).lower()
                        if self.whole_word:
                            matched = (norm_query == norm_w)
                        else:
                            matched = (norm_query in norm_w)
                        if matched:
                            hits.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                            accent_fallback_used = True

                if not hits:
                    continue

                for hit in hits:
                    if not accent_fallback_used:
                        if self.case_sensitive:
                            try:
                                extracted = page.get_text("text", clip=hit).strip()
                                if self.query not in extracted:
                                    continue
                            except Exception:
                                pass

                        if self.whole_word:
                            try:
                                # Expand horizontal clip by 10 points to capture surrounding word boundaries
                                clip_rect = fitz.Rect(max(0.0, hit.x0 - 10.0), hit.y0 - 2.0, hit.x1 + 10.0, hit.y1 + 2.0)
                                extracted = page.get_text("text", clip=clip_rect).strip()
                                flags = 0 if self.case_sensitive else re.IGNORECASE
                                pattern = r'(?<!\w)' + re.escape(self.query) + r'(?!\w)'
                                if not re.search(pattern, extracted, flags):
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
            self.last_wrapped = False
            return None
        prev_idx = self.current_match_index
        self.current_match_index = (self.current_match_index + 1) % len(self.matches)
        self.last_wrapped = (self.current_match_index == 0 and prev_idx == len(self.matches) - 1 and len(self.matches) > 1)
        return self.matches[self.current_match_index]

    def prev_match(self) -> Optional[SearchMatch]:
        """Retreat to previous match with circular wrap-around."""
        if not self.matches:
            self.last_wrapped = False
            return None
        prev_idx = self.current_match_index
        self.current_match_index = (self.current_match_index - 1) % len(self.matches)
        self.last_wrapped = (self.current_match_index == len(self.matches) - 1 and prev_idx == 0 and len(self.matches) > 1)
        return self.matches[self.current_match_index]

    def get_matches_for_page(self, page_index: int) -> List[SearchMatch]:
        """Return all match hits located on the specified page index."""
        if not self.matches:
            return []
        return [m for m in self.matches if m.page_index == page_index]

    def search_regex(
        self,
        doc_or_pattern: Any,
        pattern: Optional[str] = None,
        page_indices: Optional[List[int]] = None,
        flags: int = re.IGNORECASE,
    ) -> List[SearchMatch]:
        """Search document using a regular expression pattern and return all matches with bounding boxes."""
        if pattern is not None or not isinstance(doc_or_pattern, str):
            self.doc = doc_or_pattern
            actual_pattern = pattern or ""
        else:
            actual_pattern = doc_or_pattern

        self.query = actual_pattern
        self.matches.clear()
        self.current_match_index = -1
        self.last_wrapped = False

        if not self.doc or getattr(self.doc, "is_closed", False) or not actual_pattern or len(self.doc) == 0:
            return self.matches

        try:
            compiled = re.compile(actual_pattern, flags)
        except re.error as err:
            print(f"Warning: invalid regex '{actual_pattern}': {err}")
            return self.matches

        target_pages = page_indices if page_indices is not None else list(range(len(self.doc)))

        for page_idx in target_pages:
            if page_idx < 0 or page_idx >= len(self.doc):
                continue
            try:
                page = self.doc[page_idx]
                page_text = page.get_text("text")
                if not page_text:
                    continue

                seen_rects = set()
                for match in compiled.finditer(page_text):
                    m_text = match.group(0).strip()
                    if not m_text:
                        continue
                    rects = page.search_for(m_text)
                    for r in rects:
                        r_key = (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
                        if r_key not in seen_rects:
                            seen_rects.add(r_key)
                            self.matches.append(SearchMatch(
                                page_index=page_idx,
                                bbox=(r.x0, r.y0, r.x1, r.y1),
                                text=m_text
                            ))
            except Exception as err:
                print(f"Warning: regex search failed on page {page_idx}: {err}")

        if self.matches:
            self.current_match_index = 0

        return self.matches

    def search_pii(
        self,
        doc_or_pattern_key: Any,
        pattern_key: Optional[str] = None,
        page_indices: Optional[List[int]] = None,
    ) -> List[SearchMatch]:
        """Search document for standard PII pattern presets (ssn, credit_card, email, phone, date)."""
        if pattern_key is not None or not isinstance(doc_or_pattern_key, str):
            doc = doc_or_pattern_key
            key = pattern_key or "ssn"
        else:
            doc = self.doc
            key = doc_or_pattern_key

        preset = PII_PATTERNS.get(key)
        if not preset:
            return []

        return self.search_regex(doc, preset["regex"], page_indices=page_indices)


