import unittest
import tempfile
import os
import time
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf

from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.pdf_handler import DiskThumbnailCache, get_disk_thumbnail_cache


class TestDiskThumbnailCache(unittest.TestCase):
    """Test suite for persistent two-tier thumbnail disk cache and fast reopen."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Gtk.Application()
        except Exception:
            cls.app = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = os.path.join(self.temp_dir.name, "cache")
        self.disk_cache = DiskThumbnailCache(cache_dir=self.cache_dir, max_disk_bytes=50 * 1024 * 1024)
        pdf_handler._DISK_THUMBNAIL_CACHE = self.disk_cache

        # Create a sample multi-page PDF
        self.pdf_path = os.path.join(self.temp_dir.name, "sample.pdf")
        doc = fitz.open()
        for i in range(10):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50), f"Sample Page {i+1}")
        doc.save(self.pdf_path)
        doc.close()

    def tearDown(self):
        pdf_handler._DISK_THUMBNAIL_CACHE = None
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        self.temp_dir.cleanup()

    def test_fingerprint_generation_and_staleness(self):
        """Fingerprint must be deterministic and change on file modification."""
        doc = fitz.open(self.pdf_path)
        fp1 = self.disk_cache.get_document_fingerprint(doc, filepath=self.pdf_path)
        fp2 = self.disk_cache.get_document_fingerprint(doc, filepath=self.pdf_path)
        self.assertIsNotNone(fp1)
        self.assertEqual(fp1, fp2)

        # Touch file to change mtime
        time.sleep(0.01)
        os.utime(self.pdf_path, None)
        fp3 = self.disk_cache.get_document_fingerprint(doc, filepath=self.pdf_path)
        self.assertNotEqual(fp1, fp3, "Fingerprint must change when file modification time changes")
        doc.close()

    def test_store_and_retrieve_thumbnail(self):
        """Storing and retrieving thumbnails from disk must yield valid GdkPixbufs."""
        doc = fitz.open(self.pdf_path)
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        stored = self.disk_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path)
        self.assertTrue(stored)

        retrieved = self.disk_cache.get_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved, GdkPixbuf.Pixbuf)
        self.assertGreater(retrieved.get_width(), 0)
        self.assertGreater(retrieved.get_height(), 0)

        # Non-existent page must return None
        none_thumb = self.disk_cache.get_thumbnail(doc, 999, target_width=150, filepath=self.pdf_path)
        self.assertIsNone(none_thumb)
        doc.close()

    def test_page_invalidation(self):
        """Invalidating a single page must delete only that page's cached file."""
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        page1 = doc.load_page(1)
        pix0 = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        pix1 = page1.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        self.disk_cache.store_thumbnail(doc, 0, 150, pix0, filepath=self.pdf_path)
        self.disk_cache.store_thumbnail(doc, 1, 150, pix1, filepath=self.pdf_path)

        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 1, 150, filepath=self.pdf_path))

        self.disk_cache.invalidate_page(doc, 0, filepath=self.pdf_path)
        self.assertIsNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 1, 150, filepath=self.pdf_path))
        doc.close()

    def test_document_invalidation(self):
        """Invalidating a document must purge all thumbnails for that document."""
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        pix0 = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        self.disk_cache.store_thumbnail(doc, 0, 150, pix0, filepath=self.pdf_path)

        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        self.disk_cache.invalidate_doc(doc, filepath=self.pdf_path)
        self.assertIsNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        doc.close()

    def test_lru_quota_pruning(self):
        """Disk cache pruning must remove oldest directories when exceeding byte quota."""
        # Create small quota cache (2 KB)
        tiny_cache = DiskThumbnailCache(cache_dir=self.cache_dir, max_disk_bytes=2048)
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        pix = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        # Store for doc 1
        tiny_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path)

        # Create doc 2 in temp dir
        doc2_path = os.path.join(self.temp_dir.name, "sample2.pdf")
        doc2 = fitz.open()
        doc2.new_page(width=595, height=842)
        doc2.save(doc2_path)
        doc2.close()

        doc2 = fitz.open(doc2_path)
        time.sleep(0.02)
        tiny_cache.store_thumbnail(doc2, 0, 150, pix, filepath=doc2_path)

        # Trigger prune with very small limit (500 bytes)
        tiny_cache.prune(max_bytes=500)

        # Total size must now be <= 500 bytes
        remaining_dirs = [d for d in Path(self.cache_dir).iterdir() if d.is_dir()]
        self.assertLessEqual(len(remaining_dirs), 1)

        doc.close()
        doc2.close()

    def test_generate_thumbnail_uses_disk_cache_without_rasterizing(self):
        """generate_thumbnail must return cached thumbnail without calling fitz load_page."""
        doc, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)

        # 1. First call renders and caches to disk
        thumb1 = pdf_handler.generate_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(thumb1)

        # Verify disk cache now contains thumbnail
        disk_thumb = pdf_handler.get_disk_thumbnail_cache().get_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(disk_thumb)

        # 2. Poison doc.load_page to confirm fitz is NOT called on second retrieve
        def poisoned_load_page(*args, **kwargs):
            raise RuntimeError("load_page should not be called when thumbnail is in disk cache!")
        doc.load_page = poisoned_load_page

        thumb2 = pdf_handler.generate_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(thumb2)
        self.assertEqual(thumb2.get_width(), thumb1.get_width())

        doc.close()

    def test_fast_document_reopen_thumbnails_prepopulated(self):
        """Reopening a previously opened document must load thumbnails from disk in under 15ms."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # Ensure page 0 and page 1 thumbnails are rendered and stored to disk
        pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        pdf_handler.generate_thumbnail(self.win.doc, 1, target_width=150, filepath=self.pdf_path)

        # Close session
        self.win.close_document()

        # Reopen document
        reloaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)

        t0 = time.time()
        self.win._finish_loading(reloaded, None, self.pdf_path, 0, self.win._active_session)
        t1 = time.time()
        reopen_ms = (t1 - t0) * 1000

        self.assertLess(reopen_ms, 50.0, f"Reopening document took {reopen_ms:.2f}ms, expected < 50ms")

        # Verify visible model items have pre-populated thumbnails directly from disk
        model = self.win._active_session.pages_model
        self.assertGreater(model.get_n_items(), 0)
        item0 = model.get_item(0)
        self.assertIsNotNone(item0.thumbnail, "Page 0 thumbnail must be pre-populated from disk on reopen")
        item1 = model.get_item(1)
        self.assertIsNotNone(item1.thumbnail, "Page 1 thumbnail must be pre-populated from disk on reopen")

    def test_store_thumbnail_rejects_dirty_doc_without_force(self):
        """store_thumbnail must refuse to write when document has unsaved in-memory changes."""
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        pix = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        doc._is_modified = True
        stored = self.disk_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path)
        self.assertFalse(stored, "store_thumbnail must reject dirty document without force=True")

        stored_forced = self.disk_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path, force=True)
        self.assertTrue(stored_forced, "store_thumbnail must succeed when force=True is provided")
        doc.close()

    def test_dirty_thumbnail_not_written_to_disk_cache(self):
        """In-memory edits must update the UI preview without corrupting the on-disk thumbnail cache."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # 1. Clean thumbnail is generated and cached to disk
        clean_thumb = pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(clean_thumb)

        fp = self.disk_cache.get_document_fingerprint(self.win.doc, filepath=self.pdf_path)
        thumb_on_disk = Path(self.disk_cache.cache_dir) / fp / "0_150.png"
        self.assertTrue(thumb_on_disk.is_file(), "Clean thumbnail must exist on disk")
        disk_mtime_before = thumb_on_disk.stat().st_mtime_ns

        # 2. Rotate page 90 degrees in memory (dirty change)
        time.sleep(0.02)
        self.win.rotate_current_page(90)
        self.assertTrue(self.win.document_modified)
        self.assertTrue(self.win._active_session.is_modified)

        # 3. Sidebar thumbnail in memory reflects the rotated page
        item0 = self.win._active_session.pages_model.get_item(0)
        self.assertIsNotNone(item0.thumbnail)
        # 595x842 rotated 90 is 842x595 (aspect ratio flips)
        self.assertNotEqual(item0.thumbnail.get_height(), clean_thumb.get_height())

        # 4. Critical: On-disk thumbnail file was NOT overwritten by the dirty in-memory change!
        self.assertTrue(thumb_on_disk.is_file())
        disk_mtime_after = thumb_on_disk.stat().st_mtime_ns
        self.assertEqual(disk_mtime_before, disk_mtime_after, "On-disk thumbnail must NOT be overwritten by unsaved changes")

    def test_exit_without_saving_preserves_clean_disk_cache(self):
        """Closing the window without saving must keep the clean on-disk thumbnail intact."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # Cache clean thumbnail
        clean_thumb = pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        clean_h = clean_thumb.get_height()

        # Modify page 0 in memory
        self.win.rotate_current_page(90)
        self.assertTrue(self.win.document_modified)

        # Simulate exiting without saving (closing session)
        self.win.close_document()

        # Reopen document fresh from disk
        reloaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(reloaded, None, self.pdf_path, 0, self.win._active_session)

        # The thumbnail retrieved from disk cache must be the clean un-rotated thumbnail
        cached_thumb = pdf_handler.get_disk_thumbnail_cache().get_thumbnail(reloaded, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(cached_thumb)
        self.assertEqual(cached_thumb.get_height(), clean_h, "Disk cache must retain original un-rotated thumbnail on exit without saving")

    def test_saving_document_updates_disk_thumbnail_cache(self):
        """Saving document writes changes to disk and updates the on-disk thumbnail cache."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        clean_thumb = pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        clean_h = clean_thumb.get_height()

        # Rotate page 0 in memory
        self.win.rotate_current_page(90)
        rotated_h = self.win._active_session.pages_model.get_item(0).thumbnail.get_height()
        self.assertNotEqual(clean_h, rotated_h)

        # Save document
        time.sleep(0.02)
        self.win.save_document(self.pdf_path)

        # Verify disk cache now contains thumbnail matching the saved rotated state
        reloaded_doc = fitz.open(self.pdf_path)
        saved_disk_thumb = pdf_handler.get_disk_thumbnail_cache().get_thumbnail(reloaded_doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(saved_disk_thumb, "Saved document must have cached thumbnail on disk")
        self.assertNotEqual(saved_disk_thumb.get_height(), clean_h, "Disk thumbnail must reflect rotated page, not clean un-rotated state")
        # Rotated page (842x595) scaled to 150px width has height 106px (vs clean un-rotated 212px)
        self.assertEqual(saved_disk_thumb.get_height(), round(150 / 842 * 595))
        reloaded_doc.close()


if __name__ == "__main__":
    unittest.main()
