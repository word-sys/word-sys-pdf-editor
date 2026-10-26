import unittest
import collections
import zlib
import gc
from unittest.mock import MagicMock, patch
import cairo

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.pdf_handler import (
    BoundedLRUCache,
    CompressedSnapshotStore,
    release_page_snapshots,
    close_pdf_document,
)
from word_sys_pdf_editor.undo_manager import UndoManager, Command


class DummyCommand(Command):
    """Minimal test command for UndoManager testing."""
    def __init__(self, idx: int):
        self.idx = idx
        self.executed = False
        self.undone = False

    def execute(self):
        self.executed = True
        self.undone = False

    def undo(self):
        self.undone = True
        self.executed = False


class TestBoundedLRUCache(unittest.TestCase):
    """Test suite for BoundedLRUCache count and memory byte ceiling behavior."""

    def test_bounded_lru_cache_item_count_eviction(self):
        cache = BoundedLRUCache(max_items=3, max_bytes=100_000)
        cache["p1"] = b"data1"
        cache["p2"] = b"data2"
        cache["p3"] = b"data3"
        self.assertEqual(len(cache), 3)
        self.assertIn("p1", cache)

        # Adding 4th item must evict the oldest "p1"
        cache["p4"] = b"data4"
        self.assertEqual(len(cache), 3)
        self.assertNotIn("p1", cache)
        self.assertIn("p2", cache)
        self.assertIn("p3", cache)
        self.assertIn("p4", cache)

    def test_bounded_lru_cache_byte_ceiling_eviction(self):
        # 100 bytes budget: each item is 40 bytes
        cache = BoundedLRUCache(max_items=10, max_bytes=100)
        cache["k1"] = b"a" * 40
        cache["k2"] = b"b" * 40
        self.assertEqual(cache.current_bytes, 80)
        self.assertEqual(len(cache), 2)

        # Adding 3rd item brings total to 120 > 100 max_bytes; must evict k1
        cache["k3"] = b"c" * 40
        self.assertEqual(len(cache), 2)
        self.assertNotIn("k1", cache)
        self.assertIn("k2", cache)
        self.assertIn("k3", cache)
        self.assertEqual(cache.current_bytes, 80)

    def test_bounded_lru_cache_mru_order_on_access(self):
        cache = BoundedLRUCache(max_items=3, max_bytes=100_000)
        cache["a"] = b"1"
        cache["b"] = b"2"
        cache["c"] = b"3"

        # Access "a" to promote it to most recently used
        val = cache["a"]
        self.assertEqual(val, b"1")

        # Now add "d" -> oldest was "b" (since "a" was refreshed), so "b" must be evicted
        cache["d"] = b"4"
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)
        self.assertIn("c", cache)
        self.assertIn("d", cache)

    def test_bounded_lru_cache_dynamic_budget(self):
        cache = BoundedLRUCache(max_items=5, max_bytes=100_000)
        for i in range(5):
            cache[f"item_{i}"] = b"val"
        self.assertEqual(len(cache), 5)

        # Shrink count budget to 2
        cache.set_budget(max_items=2)
        self.assertEqual(len(cache), 2)
        self.assertEqual(list(cache.keys()), ["item_3", "item_4"])

    def test_bounded_lru_cairo_surface_sizing(self):
        cache = BoundedLRUCache(max_items=5, max_bytes=10_000_000)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
        expected_size = surf.get_stride() * surf.get_height()
        cache["surf1"] = surf
        self.assertEqual(cache.current_bytes, expected_size)
        self.assertGreater(cache.current_bytes, 0)

        # Popping surface must decrement current_bytes back to 0
        popped = cache.pop("surf1")
        self.assertIs(popped, surf)
        self.assertEqual(cache.current_bytes, 0)


class TestCompressedSnapshotStore(unittest.TestCase):
    """Test suite for in-memory zlib snapshot compression and transparent retrieval."""

    def test_compressed_snapshot_store_compression_ratio(self):
        store = CompressedSnapshotStore()
        raw_stream = b"q 1 0 0 1 50 100 cm /F1 12 Tf (Compressible Text) Tj Q\n" * 100
        key = ("doc_test", 0)
        store[key] = raw_stream

        # Raw internal storage must be compressed
        raw_internal = dict.__getitem__(store, key)
        self.assertTrue(raw_internal.startswith(b"ZL\x01"))
        self.assertLess(len(raw_internal), len(raw_stream) / 4)

    def test_compressed_snapshot_store_transparent_access(self):
        store = CompressedSnapshotStore()
        raw_stream = b"BT /F1 12 Tf (Hello World) Tj ET"
        key = ("doc_test", 1)
        store[key] = raw_stream

        # __getitem__ returns original bytes
        self.assertEqual(store[key], raw_stream)
        # get() returns original bytes
        self.assertEqual(store.get(key), raw_stream)
        # items() yields original bytes
        items_dict = dict(store.items())
        self.assertEqual(items_dict[key], raw_stream)
        # values() yields original bytes
        self.assertIn(raw_stream, list(store.values()))

        # pop() returns original bytes and removes entry
        popped = store.pop(key)
        self.assertEqual(popped, raw_stream)
        self.assertEqual(len(store), 0)

    def test_compressed_snapshot_store_rekeying_and_raw_items(self):
        store = CompressedSnapshotStore()
        content = b"BT (Page 0 Stream) ET"
        store[("doc1", 0)] = content

        # Re-keying using raw_items() must preserve compression without re-compression
        new_items = {}
        for (did, pno), raw_val in store.raw_items():
            new_items[(did, pno + 1)] = raw_val

        store.clear()
        store.update(new_items)

        self.assertNotIn(("doc1", 0), store)
        self.assertIn(("doc1", 1), store)
        self.assertEqual(store[("doc1", 1)], content)


class TestUndoManagerBoundedStack(unittest.TestCase):
    """Test suite for bounded UndoManager deque memory ceiling."""

    def test_undo_manager_bounded_capacity(self):
        mock_win = MagicMock()
        manager = UndoManager(mock_win, max_depth=5)
        self.assertIsInstance(manager.undo_stack, collections.deque)
        self.assertEqual(manager.undo_stack.maxlen, 5)

        # Add 8 commands
        for i in range(8):
            manager.add_command(DummyCommand(i))

        # Size must be capped at 5
        self.assertEqual(len(manager.undo_stack), 5)
        # Oldest commands (0, 1, 2) must have been evicted from left
        self.assertEqual(manager.undo_stack[0].idx, 3)
        self.assertEqual(manager.undo_stack[-1].idx, 7)

    def test_undo_manager_undo_redo_bounded(self):
        mock_win = MagicMock()
        mock_win.doc = None
        manager = UndoManager(mock_win, max_depth=3)
        c1, c2, c3 = DummyCommand(1), DummyCommand(2), DummyCommand(3)
        manager.add_command(c1)
        manager.add_command(c2)
        manager.add_command(c3)

        self.assertEqual(len(manager.undo_stack), 3)
        manager.undo()
        self.assertTrue(c3.undone)
        self.assertEqual(len(manager.undo_stack), 2)
        self.assertEqual(len(manager.redo_stack), 1)

        manager.redo()
        self.assertTrue(c3.executed)
        self.assertEqual(len(manager.undo_stack), 3)


class TestGenerationalGarbageCollection(unittest.TestCase):
    """Test suite for generational garbage collection triggers."""

    @patch("word_sys_pdf_editor.pdf_handler.gc.collect")
    def test_release_page_snapshots_invokes_gc(self, mock_gc):
        doc = fitz.open()
        release_page_snapshots(doc)
        mock_gc.assert_called_with(1)
        doc.close()

    @patch("word_sys_pdf_editor.pdf_handler.gc.collect")
    def test_close_pdf_document_invokes_gc(self, mock_gc):
        doc = fitz.open()
        close_pdf_document(doc)
        mock_gc.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()
