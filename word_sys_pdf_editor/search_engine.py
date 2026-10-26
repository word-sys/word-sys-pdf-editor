from __future__ import annotations

import re
import unicodedata
import threading
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple
from gi.repository import GLib
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
        self._async_search_id: int = 0
        self._async_lock = threading.Lock()
        self._is_searching: bool = False

    def cancel_async_search(self):
        """Cancel any running background search worker."""
        with self._async_lock:
            self._async_search_id += 1
            self._is_searching = False

    def is_searching(self) -> bool:
        """Return True if an async search worker is actively scanning pages."""
        with self._async_lock:
            return self._is_searching

    def set_document(self, doc: Optional[fitz.Document]):
        """Bind search engine to a new or reloaded document session."""
        if self.doc != doc:
            self.cancel_async_search()
            self.doc = doc
            self.clear()

    def clear(self):
        """Reset search query and clear all cached search hits."""
        self.cancel_async_search()
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

    def search_page(
        self,
        page_idx: int,
        query: str,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> List[SearchMatch]:
        """Search a single page and return all match hits."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            return []
        if page_idx < 0 or page_idx >= len(self.doc):
            return []
        page_matches = []
        try:
            page = self.doc[page_idx]
            hits = page.search_for(query)
            accent_fallback_used = False
            if not hits and not case_sensitive:
                norm_query = _normalize_text_for_search(query).lower()
                words = page.get_text("words")
                for w in words:
                    w_text = w[4]
                    clean_w = w_text.strip(".,;:!?()[]{}\"'“”‘’—")
                    norm_w = _normalize_text_for_search(clean_w).lower()
                    if whole_word:
                        matched = (norm_query == norm_w)
                    else:
                        matched = (norm_query in norm_w)
                    if matched:
                        hits.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                        accent_fallback_used = True

            if not hits:
                return []

            for hit in hits:
                if not accent_fallback_used:
                    if case_sensitive:
                        try:
                            extracted = page.get_text("text", clip=hit).strip()
                            if query not in extracted:
                                continue
                        except Exception:
                            pass

                    if whole_word:
                        try:
                            clip_rect = fitz.Rect(max(0.0, hit.x0 - 10.0), hit.y0 - 2.0, hit.x1 + 10.0, hit.y1 + 2.0)
                            extracted = page.get_text("text", clip=clip_rect).strip()
                            flags = 0 if case_sensitive else re.IGNORECASE
                            pattern = r'(?<!\w)' + re.escape(query) + r'(?!\w)'
                            if not re.search(pattern, extracted, flags):
                                continue
                        except Exception:
                            pass

                match = SearchMatch(
                    page_index=page_idx,
                    bbox=(hit.x0, hit.y0, hit.x1, hit.y1),
                    text=query,
                )
                page_matches.append(match)
        except Exception as err:
            print(f"Warning: search failed on page {page_idx}: {err}")
        return page_matches

    def search_page_regex(
        self,
        page_idx: int,
        compiled_regex: re.Pattern,
    ) -> List[SearchMatch]:
        """Search a single page using a compiled regular expression and return match hits."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            return []
        if page_idx < 0 or page_idx >= len(self.doc):
            return []
        page_matches = []
        try:
            page = self.doc[page_idx]
            page_text = page.get_text("text")
            if not page_text:
                return []
            seen_rects = set()
            for match in compiled_regex.finditer(page_text):
                m_text = match.group(0).strip()
                if not m_text:
                    continue
                rects = page.search_for(m_text)
                for r in rects:
                    r_key = (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
                    if r_key not in seen_rects:
                        seen_rects.add(r_key)
                        page_matches.append(SearchMatch(
                            page_index=page_idx,
                            bbox=(r.x0, r.y0, r.x1, r.y1),
                            text=m_text,
                        ))
        except Exception as err:
            print(f"Warning: regex search failed on page {page_idx}: {err}")
        return page_matches

    def search(
        self,
        doc_or_query: Any,
        query: Optional[str] = None,
        case_sensitive: bool = False,
        whole_word: bool = False,
        page_indices: Optional[List[int]] = None,
    ) -> List[SearchMatch]:
        """Search document across visible text and invisible OCR render mode 3 layers."""
        self.cancel_async_search()
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

        target_pages = page_indices if page_indices is not None else list(range(len(self.doc)))
        for page_idx in target_pages:
            self.matches.extend(self.search_page(page_idx, self.query, self.case_sensitive, self.whole_word))

        if self.matches:
            self.current_match_index = 0

        return self.matches

    def start_async_search(
        self,
        doc: Optional[fitz.Document],
        query: Optional[str] = None,
        case_sensitive: bool = False,
        whole_word: bool = False,
        pii_key: Optional[str] = None,
        page_indices: Optional[List[int]] = None,
        chunk_size: int = 10,
        on_chunk: Optional[Callable[[List[SearchMatch], int, int], None]] = None,
        on_complete: Optional[Callable[[List[SearchMatch]], None]] = None,
        sync: bool = False,
    ) -> int:
        """Start async progressive search scanning pages in chunks on a background worker thread."""
        with self._async_lock:
            self._async_search_id += 1
            search_id = self._async_search_id
            self._is_searching = True

        self.doc = doc
        self.query = query.strip() if query else ""
        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.matches.clear()
        self.current_match_index = -1
        self.last_wrapped = False

        if not self.doc or getattr(self.doc, "is_closed", False) or len(self.doc) == 0 or (not self.query and not pii_key):
            with self._async_lock:
                self._is_searching = False
            if on_complete:
                on_complete([])
            return search_id

        target_pages = list(page_indices) if page_indices is not None else list(range(len(self.doc)))
        total_pages = len(target_pages)

        compiled_regex = None
        if pii_key:
            preset = PII_PATTERNS.get(pii_key)
            if preset:
                compiled_regex = re.compile(preset["regex"], re.IGNORECASE)
                self.query = preset["regex"]

        def _execute_worker():
            for i in range(0, total_pages, chunk_size):
                with self._async_lock:
                    if search_id != self._async_search_id:
                        return
                chunk_slice = target_pages[i:i + chunk_size]
                chunk_hits = []
                for p_idx in chunk_slice:
                    with self._async_lock:
                        if search_id != self._async_search_id:
                            return
                    if compiled_regex:
                        hits = self.search_page_regex(p_idx, compiled_regex)
                    else:
                        hits = self.search_page(p_idx, self.query, self.case_sensitive, self.whole_word)
                    chunk_hits.extend(hits)

                processed = min(i + chunk_size, total_pages)

                def _dispatch_chunk(c_hits=chunk_hits, p_count=processed, sid=search_id):
                    with self._async_lock:
                        if sid != self._async_search_id:
                            return False
                    self.matches.extend(c_hits)
                    if self.current_match_index < 0 and self.matches:
                        self.current_match_index = 0
                    if on_chunk:
                        on_chunk(c_hits, p_count, total_pages)
                    return False

                if sync:
                    _dispatch_chunk()
                else:
                    GLib.idle_add(_dispatch_chunk)

            def _dispatch_finish(sid=search_id):
                with self._async_lock:
                    if sid != self._async_search_id:
                        return False
                    self._is_searching = False
                if on_complete:
                    on_complete(self.matches)
                return False

            if sync:
                _dispatch_finish()
            else:
                GLib.idle_add(_dispatch_finish)

        if sync:
            _execute_worker()
        else:
            worker_thread = threading.Thread(
                target=_execute_worker,
                daemon=True,
                name=f"SearchWorker-{search_id}"
            )
            worker_thread.start()

        return search_id

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
            self.matches.extend(self.search_page_regex(page_idx, compiled))

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


