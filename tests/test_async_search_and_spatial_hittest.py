from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch
import fitz
from gi.repository import GLib

from word_sys_pdf_editor.models import SpatialGridIndex, EditableText, EditableImage, EditableShape, EditableStroke
from word_sys_pdf_editor.search_engine import DocumentSearchEngine, SearchMatch


class TestSpatialGridIndex(unittest.TestCase):
    def test_empty_grid(self):
        grid = SpatialGridIndex(cell_size=64.0)
        self.assertEqual(grid.query_point(100.0, 100.0), [])
        self.assertEqual(grid.query_rect((50.0, 50.0, 150.0, 150.0)), [])

    def test_single_cell_insertion_and_query(self):
        grid = SpatialGridIndex(cell_size=64.0)
        obj1 = {"id": "obj1", "bbox": (10.0, 10.0, 30.0, 30.0)}
        grid.insert(obj1, obj1["bbox"])

        hits = grid.query_point(20.0, 20.0)
        self.assertIn(obj1, hits)

        # Far away point outside cell (0, 0)
        miss = grid.query_point(200.0, 200.0)
        self.assertEqual(miss, [])

    def test_multi_cell_spanning_insertion(self):
        grid = SpatialGridIndex(cell_size=64.0)
        # Spans cell (0, 0) to cell (2, 2)
        obj_large = {"id": "large", "bbox": (10.0, 10.0, 140.0, 140.0)}
        grid.insert(obj_large, obj_large["bbox"])

        self.assertIn(obj_large, grid.query_point(20.0, 20.0))
        self.assertIn(obj_large, grid.query_point(70.0, 70.0))
        self.assertIn(obj_large, grid.query_point(130.0, 130.0))
        self.assertEqual(grid.query_point(300.0, 300.0), [])

    def test_tolerance_query_across_boundaries(self):
        grid = SpatialGridIndex(cell_size=64.0)
        # Placed near edge of cell (0, 0) at x=62
        obj_edge = {"id": "edge", "bbox": (58.0, 10.0, 62.0, 30.0)}
        grid.insert(obj_edge, obj_edge["bbox"])

        # Query just past cell boundary at x=65 with tolerance 5.0
        hits = grid.query_point(65.0, 20.0, tolerance=5.0)
        self.assertIn(obj_edge, hits)

    def test_query_rect(self):
        grid = SpatialGridIndex(cell_size=64.0)
        obj1 = {"id": "1", "bbox": (10.0, 10.0, 20.0, 20.0)}
        obj2 = {"id": "2", "bbox": (100.0, 100.0, 120.0, 120.0)}
        grid.insert(obj1, obj1["bbox"])
        grid.insert(obj2, obj2["bbox"])

        window_query = grid.query_rect((0.0, 0.0, 50.0, 50.0))
        self.assertIn(obj1, window_query)
        self.assertNotIn(obj2, window_query)

    def test_clear(self):
        grid = SpatialGridIndex(cell_size=64.0)
        obj = {"id": "test", "bbox": (10.0, 10.0, 20.0, 20.0)}
        grid.insert(obj, obj["bbox"])
        self.assertEqual(len(grid.query_point(15.0, 15.0)), 1)
        grid.clear()
        self.assertEqual(len(grid.query_point(15.0, 15.0)), 0)


class TestAsyncChunkedSearchEngine(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        for i in range(25):
            page = self.doc.new_page(width=400, height=300)
            if i % 5 == 0:
                page.insert_text((50, 100), f"SecretKey-ABC-{i:03d}")
            if i % 7 == 0:
                page.insert_text((50, 150), "user.contact@organization.org")

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_sync_execution_mode(self):
        engine = DocumentSearchEngine(self.doc)
        chunk_records = []
        completed_results = []

        def on_chunk(hits, processed, total):
            chunk_records.append((len(hits), processed, total))

        def on_complete(matches):
            completed_results.append(list(matches))

        token = engine.start_async_search(
            doc=self.doc,
            query="SecretKey",
            chunk_size=5,
            on_chunk=on_chunk,
            on_complete=on_complete,
            sync=True,
        )

        self.assertGreater(token, 0)
        self.assertEqual(len(completed_results), 1)
        self.assertEqual(len(completed_results[0]), 5)  # pages 0, 5, 10, 15, 20
        self.assertEqual(len(chunk_records), 5)  # 25 pages / 5 chunk_size

    def test_async_background_thread_search(self):
        engine = DocumentSearchEngine(self.doc)
        done_flag = [False]
        final_matches = []

        def on_complete(matches):
            final_matches.extend(matches)
            done_flag[0] = True

        engine.start_async_search(
            doc=self.doc,
            query="SecretKey",
            chunk_size=10,
            on_complete=on_complete,
            sync=False,
        )

        # Spin main loop iterations to receive GLib.idle_add callbacks
        timeout = time.time() + 3.0
        while not done_flag[0] and time.time() < timeout:
            ctx = GLib.main_context_default()
            while ctx.iteration(False):
                pass
            time.sleep(0.01)

        self.assertTrue(done_flag[0], "Async search worker failed to complete within timeout")
        self.assertEqual(len(final_matches), 5)

    def test_async_cancellation_supersedes_previous(self):
        engine = DocumentSearchEngine(self.doc)
        second_finished = [False]
        second_matches = []

        # Start search 1
        engine.start_async_search(
            doc=self.doc,
            query="SecretKey",
            chunk_size=2,
            sync=False,
        )

        # Immediately cancel and start search 2 for a different query
        def on_complete_second(matches):
            second_matches.extend(matches)
            second_finished[0] = True

        engine.start_async_search(
            doc=self.doc,
            pii_key="email",
            chunk_size=10,
            on_complete=on_complete_second,
            sync=False,
        )

        timeout = time.time() + 3.0
        while not second_finished[0] and time.time() < timeout:
            ctx = GLib.main_context_default()
            while ctx.iteration(False):
                pass
            time.sleep(0.01)

        self.assertTrue(second_finished[0])
        # PII email appears on pages 0, 7, 14, 21 -> 4 matches
        self.assertEqual(len(second_matches), 4)


class TestWindowSpatialHitTestIntegration(unittest.TestCase):
    def test_window_spatial_grid_caching_and_hit_test(self):
        from word_sys_pdf_editor.window import PdfEditorWindow

        win = PdfEditorWindow()
        doc = fitz.open()
        doc.new_page(width=500, height=700)
        win.doc = doc
        win.current_page_index = 0
        win.zoom_level = 1.0

        # Inject 100 text objects
        win.editable_texts = []
        for i in range(100):
            t = EditableText(
                x=50.0,
                y=float(10 + i * 20),
                text=f"Line {i}",
                page_number=0,
            )
            t.bbox = (50.0, float(10 + i * 20), 170.0, float(25 + i * 20))
            win.editable_texts.append(t)

        # Spatial index is initially unpopulated
        self.assertNotIn((0, "text"), win._spatial_indices)

        # First hit test builds and caches the spatial index
        hit = win._find_text_at_pos(60.0, 15.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.text, "Line 0")
        self.assertIn((0, "text"), win._spatial_indices)

        # Invalidation clears the spatial index
        win._invalidate_spatial_index(0)
        self.assertNotIn((0, "text"), win._spatial_indices)

        # Test image spatial hit test
        img = EditableImage(bbox=(200.0, 200.0, 280.0, 280.0), page_number=0, xref=0, image_bytes=b"")
        win.editable_images = [img]
        hit_img = win._find_image_at_pos(220.0, 220.0)
        self.assertIs(hit_img, img)

        # Test shape spatial hit test
        shape = EditableShape(shape_type="rectangle", bbox=(300.0, 300.0, 350.0, 350.0), page_number=0)
        win.editable_shapes = [shape]
        hit_shape = win._find_shape_at_pos(310.0, 310.0)
        self.assertIs(hit_shape, shape)

        # Test stroke spatial hit test
        stroke = EditableStroke(points=[(400.0, 400.0), (450.0, 450.0)], page_number=0)
        stroke.bbox = (400.0, 400.0, 450.0, 450.0)
        win.editable_strokes = [stroke]
        hit_stroke = win._find_stroke_at_pos(420.0, 420.0)
        self.assertIs(hit_stroke, stroke)

        # Test pointer motion throttling
        win._last_pointer_motion_time = time.monotonic()
        win._last_pointer_pos = (100.0, 100.0)

        # Micro motion under 1.5 pixels within 10ms is throttled
        mock_controller = MagicMock()
        with patch.object(win, "canvas_to_page_coords") as mock_coords:
            win._on_pointer_motion(mock_controller, 100.5, 100.5)
            mock_coords.assert_not_called()

        doc.close()
        win.destroy()

    def test_thousand_object_spatial_benchmark(self):
        grid = SpatialGridIndex(cell_size=64.0)
        for i in range(1000):
            bx = (i % 20) * 28.0
            by = (i // 20) * 16.0
            grid.insert(f"item_{i}", (bx, by, bx + 24.0, by + 12.0))

        t0 = time.perf_counter()
        query_count = 500
        for i in range(query_count):
            px = float((i * 7) % 595)
            py = float((i * 11) % 842)
            _ = grid.query_point(px, py, tolerance=2.0)
        elapsed_total = (time.perf_counter() - t0) * 1000.0
        avg_per_query = elapsed_total / query_count

        # Spatial lookup must execute in under 0.05ms (50 microseconds) per query
        self.assertLess(avg_per_query, 0.05, f"Spatial query too slow: {avg_per_query:.4f} ms per query")


if __name__ == "__main__":
    unittest.main()
