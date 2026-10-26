import math
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor.window import PdfEditorWindow, UniformPageOffsets


class TestUniformPageOffsets(unittest.TestCase):
    """Verify UniformPageOffsets zero-allocation virtual sequence."""

    def test_virtual_list_indexing_and_bounds(self):
        u = UniformPageOffsets(count=10, gap=16.0, pw=595.0, ph=842.0)
        self.assertEqual(len(u), 10)
        self.assertTrue(bool(u))

        # First item
        self.assertEqual(u[0], (0.0, 16.0, 595.0, 842.0))

        # Second item (y = 16 + 842 + 16 = 874)
        self.assertEqual(u[1], (0.0, 874.0, 595.0, 842.0))

        # Negative indexing
        self.assertEqual(u[-1], (0.0, 16.0 + 9 * (842.0 + 16.0), 595.0, 842.0))
        self.assertEqual(u[-2], u[8])

        # Bounds checks
        with self.assertRaises(IndexError):
            _ = u[10]
        with self.assertRaises(IndexError):
            _ = u[-11]

        # Type check
        with self.assertRaises(TypeError):
            _ = u["invalid"]

    def test_slicing_and_iteration(self):
        u = UniformPageOffsets(count=5, gap=10.0, pw=500.0, ph=700.0)
        # Slicing returns a standard list of tuples
        s = u[1:3]
        self.assertIsInstance(s, list)
        self.assertEqual(len(s), 2)
        self.assertEqual(s[0], (0.0, 10.0 + 1 * 710.0, 500.0, 700.0))
        self.assertEqual(s[1], (0.0, 10.0 + 2 * 710.0, 500.0, 700.0))

        # Iteration
        items = list(u)
        self.assertEqual(len(items), 5)
        for i, item in enumerate(items):
            self.assertEqual(item, u[i])

    def test_equality_and_containment(self):
        u = UniformPageOffsets(count=3, gap=16.0, pw=600.0, ph=800.0)
        expected = [
            (0.0, 16.0, 600.0, 800.0),
            (0.0, 832.0, 600.0, 800.0),
            (0.0, 1648.0, 600.0, 800.0)
        ]
        self.assertEqual(u, expected)
        self.assertEqual(expected, u)

        self.assertIn((0.0, 832.0, 600.0, 800.0), u)
        self.assertNotIn((0.0, 999.0, 600.0, 800.0), u)
        self.assertNotIn("invalid", u)

        u_copy = u.copy()
        self.assertIsInstance(u_copy, list)
        self.assertEqual(u_copy, expected)

    def test_empty_uniform_offsets(self):
        u_empty = UniformPageOffsets(count=0, gap=16.0, pw=595.0, ph=842.0)
        self.assertEqual(len(u_empty), 0)
        self.assertFalse(bool(u_empty))
        with self.assertRaises(IndexError):
            _ = u_empty[0]


class TestContinuousScrollVirtualization(unittest.TestCase):
    """Verify O(1) continuous scroll layout recomputation, fast metadata index, and culling."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.uniform_pdf = os.path.join(self.temp_dir.name, "uniform.pdf")
        doc_u = fitz.open()
        for i in range(10):
            p = doc_u.new_page(width=600, height=800)
            p.insert_text((50, 50), f"Uniform Page {i}")
        doc_u.save(self.uniform_pdf)
        doc_u.close()

        self.mixed_pdf = os.path.join(self.temp_dir.name, "mixed.pdf")
        doc_m = fitz.open()
        p0 = doc_m.new_page(width=600, height=800)
        p0.insert_text((50, 50), "Page 0 portrait")
        p1 = doc_m.new_page(width=800, height=600)
        p1.insert_text((50, 50), "Page 1 landscape")
        p2 = doc_m.new_page(width=500, height=700)
        p2.insert_text((50, 50), "Page 2 custom")
        doc_m.save(self.mixed_pdf)
        doc_m.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fast_get_page_dimension_unrotated_and_rotated(self):
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p1 = doc.new_page(width=595, height=842)
        p1.set_rotation(90)
        p2 = doc.new_page(width=595, height=842)
        p2.set_rotation(180)
        p3 = doc.new_page(width=595, height=842)
        p3.set_rotation(270)

        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.current_pdf_page_width = 595
        win.current_pdf_page_height = 842

        # Verify dimensions match visible orientation without calling load_page
        d0 = PdfEditorWindow._fast_get_page_dimension(win, 0)
        self.assertEqual(d0, (595.0, 842.0))

        d1 = PdfEditorWindow._fast_get_page_dimension(win, 1)
        self.assertEqual(d1, (842.0, 595.0))

        d2 = PdfEditorWindow._fast_get_page_dimension(win, 2)
        self.assertEqual(d2, (595.0, 842.0))

        d3 = PdfEditorWindow._fast_get_page_dimension(win, 3)
        self.assertEqual(d3, (842.0, 595.0))
        doc.close()

    def test_uniform_document_fast_path(self):
        doc = fitz.open(self.uniform_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)

        PdfEditorWindow._recompute_continuous_layout(win)

        self.assertTrue(win._is_geometry_uniform)
        self.assertEqual(win._uniform_page_size, (600.0, 800.0))
        self.assertIsInstance(win.continuous_page_offsets, UniformPageOffsets)
        self.assertEqual(len(win.continuous_page_offsets), 10)
        # Expected stride = 800 + 16 = 816, total height = 16 + 10 * 816 = 8176
        self.assertEqual(win.continuous_total_height, 8176.0)
        self.assertEqual(win.continuous_max_width, 600.0)

        # Zoom change scales algebraically without re-reading PDF
        win.zoom_level = 2.0
        PdfEditorWindow._recompute_continuous_layout(win)
        self.assertEqual(win.continuous_max_width, 1200.0)
        # Stride = 1600 + 16 = 1616, total = 16 + 10 * 1616 = 16176
        self.assertEqual(win.continuous_total_height, 16176.0)
        doc.close()

    def test_mixed_document_fallback(self):
        doc = fitz.open(self.mixed_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)

        PdfEditorWindow._recompute_continuous_layout(win)

        self.assertFalse(win._is_geometry_uniform)
        self.assertIsInstance(win.continuous_page_offsets, list)
        self.assertEqual(len(win.continuous_page_offsets), 3)

        # Page 0: y=16, w=600, h=800
        self.assertEqual(win.continuous_page_offsets[0], (0.0, 16.0, 600.0, 800.0))
        # Page 1: y=16 + 800 + 16 = 832, w=800, h=600
        self.assertEqual(win.continuous_page_offsets[1], (0.0, 832.0, 800.0, 600.0))
        # Page 2: y=832 + 600 + 16 = 1448, w=500, h=700
        self.assertEqual(win.continuous_page_offsets[2], (0.0, 1448.0, 500.0, 700.0))

        self.assertEqual(win.continuous_max_width, 800.0)
        self.assertEqual(win.continuous_total_height, 1448.0 + 700.0 + 16.0)
        doc.close()

    def test_canvas_to_page_coords_algebraic_acceleration(self):
        doc = fitz.open(self.uniform_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.continuous_scroll = True
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win.pdf_view = MagicMock()
        win.pdf_view.get_allocated_width.return_value = 800
        win.pdf_view.get_allocated_height.return_value = 600
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)
        win.get_page_canvas_rect = lambda idx: PdfEditorWindow.get_page_canvas_rect(win, idx)
        win._recompute_continuous_layout = lambda: PdfEditorWindow._recompute_continuous_layout(win)

        PdfEditorWindow._recompute_continuous_layout(win)

        # Page 0: y in [16, 816], center x = (800 - 600) / 2 = 100
        p_idx, px, py = PdfEditorWindow.canvas_to_page_coords(win, 150.0, 100.0)
        self.assertEqual(p_idx, 0)
        self.assertEqual(px, 50.0)
        self.assertEqual(py, 84.0)

        # Page 3: y offset = 16 + 3 * 816 = 2464. Test y = 2500
        p_idx3, px3, py3 = PdfEditorWindow.canvas_to_page_coords(win, 200.0, 2500.0)
        self.assertEqual(p_idx3, 3)
        self.assertEqual(px3, 100.0)
        self.assertEqual(py3, 2500.0 - 2464.0)
        doc.close()

    def test_layout_invalidation_cleanliness(self):
        win = MagicMock(spec=PdfEditorWindow)
        win._doc_page_sizes_cache = {0: (600, 800)}
        win._is_geometry_uniform = True
        win._uniform_page_size = (600, 800)
        win.continuous_page_offsets = [1, 2, 3]
        win.continuous_scroll = False

        PdfEditorWindow._invalidate_continuous_layout(win)
        self.assertIsNone(win._doc_page_sizes_cache)
        self.assertIsNone(win._is_geometry_uniform)
        self.assertIsNone(win._uniform_page_size)
        self.assertEqual(win.continuous_page_offsets, [])

    def test_large_synthetic_document_layout_performance(self):
        """Verify 1,000-page document layout recomputation completes in under 5ms."""
        doc = fitz.open()
        for _ in range(1000):
            doc.new_page(width=595, height=842)

        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 595
        win.current_pdf_page_height = 842
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)

        # First run populates metadata index
        t0 = time.time()
        PdfEditorWindow._recompute_continuous_layout(win)
        t_first = time.time() - t0

        self.assertTrue(win._is_geometry_uniform)
        self.assertEqual(len(win.continuous_page_offsets), 1000)

        # Subsequent recomputation (e.g. on zoom/resize) is O(1) algebraic and under 1ms
        t1 = time.time()
        win.zoom_level = 1.5
        PdfEditorWindow._recompute_continuous_layout(win)
        t_recompute = time.time() - t1

        self.assertLess(t_recompute, 0.005, f"Recomputation took {t_recompute*1000:.2f}ms, expected < 5ms")
        doc.close()


if __name__ == '__main__':
    unittest.main()
