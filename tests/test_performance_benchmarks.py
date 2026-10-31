"""Practical Benchmark and Regression Checks for word-sys-pdf-editor.

Covers measurable, stable performance and memory checks:
1. Open time for a large synthetic document (1,000 pages).
2. Save time and UI responsiveness during background & incremental save.
3. Undo-stack memory after a sequence of image edits.
4. Stroke point reduction and geometric fidelity.
5. Hit-test and search latency across a 1,000-page document.
"""

import io
import math
import os
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import MagicMock

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import (
    EditableImage,
    EditableStroke,
    EditableText,
    SpatialGridIndex,
    simplify_stroke_points,
    snapshot_object_state,
)
from word_sys_pdf_editor.search_engine import DocumentSearchEngine
from word_sys_pdf_editor.undo_manager import EditObjectCommand, UndoManager
from word_sys_pdf_editor.utils import point_to_segment_distance
from word_sys_pdf_editor.window import PdfEditorWindow


class TestPerformanceBenchmarks(unittest.TestCase):
    """Practical benchmark and regression suite with generous thresholds based on measured baselines."""

    def test_large_synthetic_document_open_latency(self):
        """1. Open time for a 1,000-page synthetic document stays well within interactive bounds."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name

        try:
            doc = fitz.open()
            for idx in range(1000):
                page = doc.new_page(width=595, height=842)
                if idx < 5 or idx % 200 == 0:
                    page.insert_text((50, 70), f"Synthetic Page {idx + 1}", fontsize=12)
            doc.save(pdf_path)
            doc.close()

            win = PdfEditorWindow()
            win.font_scan_in_progress = False

            t0 = time.perf_counter()
            loaded_doc, err = pdf_handler.load_pdf_document(pdf_path)
            self.assertIsNone(err)
            self.assertIsNotNone(loaded_doc)
            win._finish_loading(loaded_doc, None, pdf_path, 0, win._active_session)
            open_ms = (time.perf_counter() - t0) * 1000.0

            self.assertEqual(len(win.doc), 1000)
            # Measured baseline ~25-70 ms; generous threshold 500 ms for slower CI machines
            self.assertLess(
                open_ms,
                500.0,
                f"Opening 1,000-page document took {open_ms:.1f} ms (expected < 500 ms)",
            )

            loaded_doc.close()
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_save_latency_and_ui_responsiveness_during_save(self):
        """2. Incremental quick save is faster than full rewrite and background save returns without blocking UI."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_full:
            full_path = tmp_full.name

        try:
            doc = fitz.open()
            for idx in range(80):
                page = doc.new_page(width=595, height=842)
                page.insert_text((50, 80), f"Document section {idx} — benchmark payload " * 3, fontsize=11)
                page.draw_rect(fitz.Rect(40, 40, 555, 800), color=(0.2, 0.3, 0.5), width=1.0)
            doc.save(pdf_path, garbage=4, deflate=True)
            doc.close()

            # Compare incremental save vs full rewrite on an edited 80-page document
            live_doc = fitz.open(pdf_path)
            live_doc[0].insert_text((50, 140), "Incremental quick edit")
            t_incr0 = time.perf_counter()
            ok_incr, err_incr = pdf_handler.save_document(live_doc, pdf_path, incremental=True)
            incr_ms = (time.perf_counter() - t_incr0) * 1000.0
            self.assertTrue(ok_incr, err_incr)

            live_doc[1].insert_text((50, 140), "Full rewrite comparison edit")
            t_full0 = time.perf_counter()
            ok_full, err_full = pdf_handler.save_document(live_doc, full_path, incremental=False)
            full_ms = (time.perf_counter() - t_full0) * 1000.0
            self.assertTrue(ok_full, err_full)

            # Measured baseline: incr ~1.5-4 ms, full ~20-45 ms; generous cap < 250 ms
            self.assertLess(incr_ms, 250.0, f"Incremental save took {incr_ms:.1f} ms")
            self.assertLess(incr_ms, full_ms, f"Expected incremental save ({incr_ms:.2f} ms) < full save ({full_ms:.2f} ms)")

            # Verify background save in PdfEditorWindow returns immediately and keeps UI responsive
            win = PdfEditorWindow()
            win.font_scan_in_progress = False
            win.doc = live_doc
            win._active_session.doc = live_doc
            win._active_session.pdf_path = pdf_path
            win.load_document = MagicMock()

            completed = []
            t_call0 = time.perf_counter()
            win.save_document(
                pdf_path,
                incremental=True,
                background=True,
                on_finish=lambda ok, err: completed.append((ok, err)),
            )
            dispatch_ms = (time.perf_counter() - t_call0) * 1000.0

            # Main-thread dispatch returns in well under 50 ms (measured ~1-3 ms)
            self.assertLess(dispatch_ms, 50.0, f"Background save dispatch blocked main thread for {dispatch_ms:.1f} ms")

            win.wait_for_save(timeout=5.0)
            self.assertEqual(len(completed), 1)
            self.assertTrue(completed[0][0], completed[0][1])

            live_doc.close()
        finally:
            for p in (pdf_path, full_path):
                if os.path.exists(p):
                    os.remove(p)

    def test_undo_stack_memory_after_image_edit_sequence(self):
        """3. Undo-stack memory after 25 sequential edits on a 5 MB image stays under 150 KB via payload sharing."""
        doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        try:
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 24, 24)
            buf = io.BytesIO()
            surf.write_to_png(buf)
            large_image_bytes = bytearray(buf.getvalue() + b"\x00" * (5 * 1024 * 1024))

            img = EditableImage(
                bbox=(40.0, 40.0, 180.0, 180.0),
                page_number=0,
                xref=None,
                image_bytes=large_image_bytes,
                is_new=True,
            )
            img.is_baked = True

            dummy_win = MagicMock()
            dummy_win.doc = doc
            dummy_win.current_page_index = 0
            dummy_win.editable_images = [img]
            dummy_win.editable_texts = []
            dummy_win.editable_shapes = []
            dummy_win.editable_strokes = []
            dummy_win.form_fields = []
            undo_mgr = UndoManager(dummy_win)
            dummy_win.undo_manager = undo_mgr

            tracemalloc.start()
            snap_before = tracemalloc.take_snapshot()

            for step in range(25):
                old_state = snapshot_object_state(img)
                nx = 40.0 + (step + 1) * 4.0
                ny = 40.0 + (step + 1) * 3.0
                img.bbox = (nx, ny, nx + 140.0, ny + 140.0)
                img.x, img.y = nx, ny
                new_state = snapshot_object_state(img)
                img.__dict__.update(old_state)

                cmd = EditObjectCommand(dummy_win, img, old_state, new_state)
                cmd.execute()
                undo_mgr.add_command(cmd)

            snap_after = tracemalloc.take_snapshot()
            tracemalloc.stop()

            stats = snap_after.compare_to(snap_before, "lineno")
            undo_alloc_bytes = sum(
                s.size_diff
                for s in stats
                if "undo_manager.py" in str(s.traceback) or "models.py" in str(s.traceback)
            )

            # Measured baseline ~25-32 KB (vs >200 MB before reference sharing); generous cap 150 KB
            self.assertLess(
                undo_alloc_bytes,
                150 * 1024,
                f"25 image edits allocated {undo_alloc_bytes} bytes in undo stack (expected < 150 KB)",
            )
            self.assertEqual(len(undo_mgr.undo_stack), 25)
            for cmd in undo_mgr.undo_stack:
                self.assertIs(cmd.old_properties["image_bytes"], large_image_bytes)
                self.assertIs(cmd.new_properties["image_bytes"], large_image_bytes)
        finally:
            doc.close()

    def test_stroke_point_reduction_and_geometric_fidelity(self):
        """4. RDP stroke simplification achieves >85% point reduction quickly while preserving <= tolerance error."""
        raw_points = [
            (
                25.0 + i * 0.45,
                180.0 + 35.0 * math.sin(i * 2.0 * math.pi / 250.0) + 8.0 * math.cos(i * 0.09),
            )
            for i in range(1000)
        ]
        tolerance = 0.5

        t0 = time.perf_counter()
        simplified = simplify_stroke_points(raw_points, tolerance=tolerance)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Measured baseline ~1.5-4 ms; generous cap 50 ms
        self.assertLess(elapsed_ms, 50.0, f"Simplifying 1,000-point stroke took {elapsed_ms:.2f} ms")
        # Point reduction > 85% (1,000 points -> < 150 points)
        self.assertLess(len(simplified), 150, f"Expected < 150 simplified points, got {len(simplified)}")
        self.assertEqual(simplified[0], raw_points[0])
        self.assertEqual(simplified[-1], raw_points[-1])

        max_deviation = 0.0
        for px, py in raw_points:
            seg_dist = min(
                point_to_segment_distance(
                    px, py, simplified[j][0], simplified[j][1], simplified[j + 1][0], simplified[j + 1][1]
                )
                for j in range(len(simplified) - 1)
            )
            if seg_dist > max_deviation:
                max_deviation = seg_dist

        self.assertLessEqual(
            max_deviation,
            tolerance + 1e-9,
            f"Maximum geometric deviation {max_deviation:.6f} exceeded tolerance {tolerance}",
        )

    def test_hittest_and_search_latency_across_1000_page_document(self):
        """5. Spatial hit-testing and full-document search across a 1,000-page document stay well within latency bounds."""
        doc = fitz.open()
        try:
            for idx in range(1000):
                page = doc.new_page(width=595, height=842)
                if idx % 100 == 0:
                    page.insert_text((60, 120), f"MilestoneToken-{idx:04d} summary line", fontsize=11)
                else:
                    page.insert_text((60, 120), f"Standard page body content {idx}", fontsize=11)

            # 5a. SpatialGridIndex hit-test across 1,000 page objects
            grid = SpatialGridIndex(cell_size=64.0)
            for idx in range(1000):
                bx = float((idx % 20) * 28)
                by = float((idx // 20) * 16)
                txt = EditableText(x=bx, y=by, text=f"Obj {idx}", page_number=0)
                txt.bbox = (bx, by, bx + 24.0, by + 12.0)
                grid.insert(txt, txt.bbox)

            t_hit0 = time.perf_counter()
            for q in range(500):
                qx = float((q * 13) % 560)
                qy = float((q * 17) % 800)
                _ = grid.query_point(qx, qy, tolerance=2.0)
            avg_hit_ms = ((time.perf_counter() - t_hit0) * 1000.0) / 500.0

            # Measured baseline ~0.003-0.010 ms/query; generous cap 0.20 ms/query
            self.assertLess(
                avg_hit_ms,
                0.20,
                f"Spatial hit-test averaged {avg_hit_ms:.4f} ms/query (expected < 0.20 ms)",
            )

            # 5b. Search latency across all 1,000 pages
            engine = DocumentSearchEngine(doc)
            t_search0 = time.perf_counter()
            matches = engine.search(doc, "MilestoneToken")
            search_ms = (time.perf_counter() - t_search0) * 1000.0

            self.assertEqual(len(matches), 10)
            # Measured baseline ~40-90 ms across 1,000 pages; generous cap 1,500 ms
            self.assertLess(
                search_ms,
                1500.0,
                f"Searching 1,000-page document took {search_ms:.1f} ms (expected < 1,500 ms)",
            )
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
