import os
import io
import unittest
from unittest.mock import MagicMock

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.models import EditableText
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.undo_manager import EditObjectCommand, UndoManager


class MockWindow:
    def __init__(self, doc, editable_texts=None):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = editable_texts if editable_texts is not None else []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self.document_modified = False
        self.selected_text = self.editable_texts[0] if self.editable_texts else None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.status_label = MagicMock()
        self.pdf_view = self
        self.undo_manager = UndoManager(self)

    def _update_undo_redo_buttons(self): pass
    def _update_text_format_controls(self, obj): pass
    def _update_ui_state(self): pass
    def _refresh_thumbnail(self, p): pass
    def queue_draw(self): pass


class TestHyperlinkEngine(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=500, height=500)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_editable_text_link_properties(self):
        """Test EditableText link_url, is_link, and get_link_url properties."""
        # Unlinked plain text
        t1 = EditableText(50, 50, "Plain Text")
        self.assertFalse(t1.is_link)
        self.assertIsNone(t1.get_link_url())

        # Explicit link_url on arbitrary text
        t2 = EditableText(50, 70, "Click Here", link_url="https://example.com")
        self.assertTrue(t2.is_link)
        self.assertEqual(t2.get_link_url(), "https://example.com")

        # Text containing explicit URL
        t3 = EditableText(50, 90, "Visit https://google.com for search")
        self.assertTrue(t3.is_link)
        self.assertEqual(t3.get_link_url(), "https://google.com")

        # Explicit link_url takes precedence over regex in text
        t4 = EditableText(50, 110, "Visit https://google.com", link_url="https://bing.com")
        self.assertTrue(t4.is_link)
        self.assertEqual(t4.get_link_url(), "https://bing.com")

    def test_extract_editable_texts_attaches_pdf_link_annotations(self):
        """extract_editable_texts must attach existing LINK_URI annotations from page to EditableText."""
        # Insert text and matching LINK_URI annotation
        text_rect = fitz.Rect(100, 100, 250, 120)
        self.page.insert_text(fitz.Point(100, 115), "Open Portal")
        link_dict = {"kind": fitz.LINK_URI, "from": text_rect, "uri": "https://portal.example.org"}
        self.page.insert_link(link_dict)

        # Save and reload document so PyMuPDF builds link xrefs
        doc_bytes = self.doc.tobytes()
        reloaded_doc = fitz.open(stream=doc_bytes, filetype="pdf")
        
        texts, err = pdf_handler.extract_editable_text(reloaded_doc, 0)
        self.assertIsNone(err)
        self.assertTrue(len(texts) >= 1)
        
        portal_text = None
        for t in texts:
            if "Open Portal" in t.text:
                portal_text = t
                break
                
        self.assertIsNotNone(portal_text, "Failed to find 'Open Portal' in extracted texts")
        self.assertTrue(portal_text.is_link)
        self.assertEqual(portal_text.link_url, "https://portal.example.org")
        reloaded_doc.close()

    def test_apply_single_object_embeds_link_annotation_for_link_url(self):
        """_apply_single_object_to_page must embed LINK_URI over bounding box when link_url is set."""
        text_obj = EditableText(
            x=100, y=200,
            text="Documentation Link",
            font_size=12,
            is_new=True,
            link_url="https://docs.python.org",
            page_number=0
        )
        text_obj.bbox = (100.0, 190.0, 220.0, 210.0)

        success, err = pdf_handler._apply_single_object_to_page(self.doc, self.page, text_obj)
        self.assertTrue(success)
        self.assertIsNone(err)

        # Save and verify link annotation exists on page
        b = self.doc.tobytes()
        check_doc = fitz.open(stream=b, filetype="pdf")
        p = check_doc[0]
        links = p.get_links()
        
        matching_links = [l for l in links if l.get("uri") == "https://docs.python.org"]
        self.assertEqual(len(matching_links), 1)
        self.assertEqual(matching_links[0]["kind"], fitz.LINK_URI)
        check_doc.close()

    def test_apply_and_remove_text_link_with_undo(self):
        """Applying link sets blue color and underline; undo restores original properties."""
        text_obj = EditableText(
            x=50, y=100,
            text="Sample Link Target",
            font_size=11,
            color=(0.0, 0.0, 0.0),
            is_new=False,
            page_number=0
        )
        text_obj.bbox = (50.0, 90.0, 160.0, 105.0)
        self.page.insert_text(fitz.Point(50, 102), "Sample Link Target")
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)

        win = MockWindow(self.doc, [text_obj])

        # 1. Apply Link
        old_props = {
            'link_url': None,
            'color': (0.0, 0.0, 0.0),
            'is_underline': False,
            'bbox': text_obj.bbox
        }
        new_props = {
            'link_url': "https://custom-target.com",
            'color': (0.0, 0.0, 238.0 / 255.0),
            'is_underline': True,
            'bbox': text_obj.bbox
        }
        cmd = EditObjectCommand(win, text_obj, old_props, new_props)
        cmd.execute()
        win.undo_manager.add_command(cmd)

        self.assertEqual(text_obj.link_url, "https://custom-target.com")
        self.assertTrue(text_obj.is_link)
        self.assertTrue(text_obj.is_underline)
        self.assertAlmostEqual(text_obj.color[2], 238.0 / 255.0, places=2)

        # 2. Undo
        win.undo_manager.undo()
        self.assertIsNone(text_obj.link_url)
        self.assertFalse(text_obj.is_link)
        self.assertFalse(text_obj.is_underline)
        self.assertEqual(text_obj.color, (0.0, 0.0, 0.0))

        # 3. Redo
        win.undo_manager.redo()
        self.assertEqual(text_obj.link_url, "https://custom-target.com")
        self.assertTrue(text_obj.is_link)
        self.assertTrue(text_obj.is_underline)

    def test_ghost_erasure_cleans_up_old_link_annotations(self):
        """_perform_ghost_erasure must delete old link annotations when redacting text."""
        # Insert a link on the page
        rect = fitz.Rect(50, 50, 150, 70)
        self.page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://old-link.com"})
        
        b = self.doc.tobytes()
        test_doc = fitz.open(stream=b, filetype="pdf")
        p = test_doc[0]
        self.assertEqual(len(p.get_links()), 1)

        t_obj = EditableText(50, 65, "Link Text", page_number=0)
        t_obj.bbox = (50.0, 50.0, 150.0, 70.0)

        # Execute EditObjectCommand to update text and link
        win = MockWindow(test_doc, [t_obj])
        old_props = {'link_url': "https://old-link.com", 'bbox': t_obj.bbox}
        new_props = {'link_url': "https://new-link.com", 'bbox': t_obj.bbox}
        cmd = EditObjectCommand(win, t_obj, old_props, new_props)
        cmd.execute()

        # Check links on page
        b2 = test_doc.tobytes()
        doc_check = fitz.open(stream=b2, filetype="pdf")
        active_links = doc_check[0].get_links()
        uris = [l.get("uri") for l in active_links]
        self.assertIn("https://new-link.com", uris)
        self.assertNotIn("https://old-link.com", uris)
        test_doc.close()
        doc_check.close()

    def test_window_get_link_url_at_pos(self):
        """_get_link_url_at_pos must detect URLs from both EditableText and raw PDF annotations."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        
        t_linked = EditableText(100, 100, "Visit site", page_number=0, link_url="https://site.org")
        t_linked.bbox = (100.0, 90.0, 180.0, 110.0)
        
        win = MockWindow(self.doc, [t_linked])
        # Bind the actual method from PdfEditorWindow
        win._get_link_url_at_pos = PdfEditorWindow._get_link_url_at_pos.__get__(win)
        
        # 1. Point inside EditableText
        self.assertEqual(win._get_link_url_at_pos(120.0, 100.0), "https://site.org")
        
        # 2. Point outside
        self.assertIsNone(win._get_link_url_at_pos(300.0, 300.0))
        
        # 3. Raw PDF link annotation on page (reloaded)
        self.page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(300, 300, 400, 320), "uri": "https://raw-pdf-link.com"})
        reloaded = fitz.open(stream=self.doc.tobytes(), filetype="pdf")
        win.doc = reloaded
        self.assertEqual(win._get_link_url_at_pos(350.0, 310.0), "https://raw-pdf-link.com")
        reloaded.close()

    def test_window_apply_and_remove_text_link_methods(self):
        """PdfEditorWindow._apply_text_link and _remove_text_link methods update properties correctly."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        
        t_obj = EditableText(50, 50, "Custom Text", page_number=0, color=(0.1, 0.1, 0.1))
        t_obj.bbox = (50.0, 40.0, 150.0, 60.0)
        self.page.insert_text(fitz.Point(50, 55), "Custom Text")
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        
        win = MockWindow(self.doc, [t_obj])
        win._apply_text_link = PdfEditorWindow._apply_text_link.__get__(win)
        win._remove_text_link = PdfEditorWindow._remove_text_link.__get__(win)
        
        # Apply link without scheme prefix -> should auto-prepend https://
        win._apply_text_link(t_obj, "example.org/docs")
        self.assertEqual(t_obj.link_url, "https://example.org/docs")
        self.assertTrue(t_obj.is_link)
        self.assertTrue(t_obj.is_underline)
        self.assertAlmostEqual(t_obj.color[2], 238.0 / 255.0, places=2)
        
        # Remove link
        win._remove_text_link(t_obj)
        self.assertIsNone(t_obj.link_url)
        self.assertFalse(t_obj.is_link)
        self.assertFalse(t_obj.is_underline)
        self.assertEqual(t_obj.color, (0.1, 0.1, 0.1))

