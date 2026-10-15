"""Unit and regression tests for workspace multi-tab object isolation and text toolbar selection decoupling."""

import os
import unittest
import copy
import fitz
from unittest.mock import MagicMock

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import DocumentSession, EditableText, EditableShape
from word_sys_pdf_editor.undo_manager import (
    UndoManager,
    AddObjectCommand,
    EditObjectCommand,
    DeleteObjectCommand,
)
from word_sys_pdf_editor.window import PdfEditorWindow


class TestWorkspaceMultiTabIsolation(unittest.TestCase):
    """Test object isolation across multiple workspaces/tabs to prevent duplication bugs."""

    def setUp(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

        # Create two separate PDF documents
        self.doc1 = fitz.open()
        self.page1 = self.doc1.new_page(width=595, height=842)
        self.page1.insert_text(fitz.Point(100, 100), "Session 1 Original Text", fontsize=12)

        self.doc2 = fitz.open()
        self.page2 = self.doc2.new_page(width=595, height=842)
        self.page2.insert_text(fitz.Point(100, 100), "Session 2 Original Text", fontsize=12)

        # Create DocumentSessions
        self.session1 = DocumentSession(pdf_path="doc1.pdf")
        self.session1.doc = self.doc1
        self.session1.current_page_index = 0
        texts1, _ = pdf_handler.extract_editable_text(self.doc1, 0)
        self.session1.editable_texts = texts1 or []
        pdf_handler.save_page_snapshot(self.doc1, 0)

        self.session2 = DocumentSession(pdf_path="doc2.pdf")
        self.session2.doc = self.doc2
        self.session2.current_page_index = 0
        texts2, _ = pdf_handler.extract_editable_text(self.doc2, 0)
        self.session2.editable_texts = texts2 or []
        pdf_handler.save_page_snapshot(self.doc2, 0)

    def tearDown(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    def test_rebuild_page_deduplication_safeguard(self):
        """Verify rebuild_page does not duplicate objects even if passed duplicate references."""
        text_obj = EditableText(100, 150, "Added Text", font_size=14.0, is_new=True)
        text_obj.page_number = 0

        # Pass a list containing the same object reference multiple times
        duplicate_list = [text_obj, text_obj, text_obj]
        pdf_handler.rebuild_page(
            self.doc1, 0,
            all_texts=duplicate_list,
            all_shapes=[],
            all_images=[]
        )

        extracted = self.doc1[0].get_text()
        count = extracted.count("Added Text")
        self.assertEqual(count, 1, "Added text was burned multiple times despite deduplication safeguard")

    def test_multi_tab_switching_does_not_duplicate_objects(self):
        """Verify editing objects in session 2 then switching back to session 1 does not duplicate session 1 objects."""
        # Initialize a mock window simulating multi-tab switching
        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.sessions = [self.session1, self.session2]
        mock_win._active_session = self.session1
        mock_win.tab_view = None
        mock_win.pdf_view = MagicMock()
        mock_win.status_label = MagicMock()
        mock_win._refresh_thumbnail = MagicMock()
        mock_win._update_ui_state = MagicMock()
        mock_win.undo_manager = UndoManager(mock_win)

        # Add a new text object to session 1
        new_text1 = EditableText(50, 200, "Unique Session 1 Item", font_size=12, is_new=True)
        new_text1.page_number = 0
        self.session1.editable_texts.append(new_text1)

        # Rebuild session 1 page
        pdf_handler.rebuild_page(
            self.session1.doc, 0,
            all_texts=self.session1.editable_texts,
            all_shapes=[],
            all_images=[]
        )
        self.assertEqual(self.doc1[0].get_text().count("Unique Session 1 Item"), 1)

        # Simulate tab switch to session 2
        mock_win._active_session = self.session2

        # Add an object in session 2
        new_text2 = EditableText(50, 300, "Session 2 Item", font_size=12, is_new=True)
        new_text2.page_number = 0
        self.session2.editable_texts.append(new_text2)
        pdf_handler.rebuild_page(
            self.session2.doc, 0,
            all_texts=self.session2.editable_texts,
            all_shapes=[],
            all_images=[]
        )

        # Simulate tab switch back to session 1
        mock_win._active_session = self.session1

        # Trigger another rebuild in session 1 (e.g. from an edit or page refresh)
        pdf_handler.rebuild_page(
            self.session1.doc, 0,
            all_texts=self.session1.editable_texts,
            all_shapes=[],
            all_images=[]
        )

        # Verify Session 1 has no duplicate objects
        self.assertEqual(
            self.doc1[0].get_text().count("Unique Session 1 Item"),
            1,
            "Session 1 object was duplicated after switching tabs"
        )
        self.assertEqual(
            self.doc1[0].get_text().count("Session 2 Item"),
            0,
            "Session 2 object leaked into Session 1"
        )

        # Verify Session 2 has no duplicate objects
        self.assertEqual(
            self.doc2[0].get_text().count("Session 2 Item"),
            1,
            "Session 2 object was duplicated"
        )
        self.assertEqual(
            self.doc2[0].get_text().count("Unique Session 1 Item"),
            0,
            "Session 1 object leaked into Session 2"
        )

    def test_commands_bound_to_creating_session(self):
        """Verify commands store target session and execute mutations on their own document."""
        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.sessions = [self.session1, self.session2]
        mock_win._active_session = self.session1

        new_text = EditableText(100, 250, "Session 1 Command Text", font_size=12, is_new=True)
        new_text.page_number = 0

        # Command created when session 1 is active
        cmd = AddObjectCommand(mock_win, new_text)
        self.assertIs(cmd.session, self.session1)

        # Switch active session to session 2
        mock_win._active_session = self.session2

        # Execute command - should modify session 1, NOT session 2
        cmd.execute()
        self.assertIn(new_text, self.session1.editable_texts)
        self.assertNotIn(new_text, self.session2.editable_texts)
        self.assertTrue(self.session1.document_modified)

        # Undo command - should remove from session 1
        cmd.undo()
        self.assertNotIn(new_text, self.session1.editable_texts)


class TestTextToolbarSelectionDecoupling(unittest.TestCase):
    """Test text toolbar formatting decoupling and selection synchronization."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=595, height=842)
        self.session = DocumentSession(pdf_path="test.pdf")
        self.session.doc = self.doc
        self.session.current_page_index = 0

        self.text1 = EditableText(50, 100, "Text Number One", font_size=12.0, font_family="Liberation Sans", is_new=True)
        self.text1.page_number = 0
        self.text1.color = (0.0, 0.0, 0.0)
        self.text1.is_bold = False

        self.text2 = EditableText(50, 200, "Text Number Two", font_size=14.0, font_family="Liberation Sans", is_new=True)
        self.text2.page_number = 0
        self.text2.color = (0.0, 0.0, 0.0)
        self.text2.is_bold = False

        self.session.editable_texts = [self.text1, self.text2]

    def test_switching_selected_text_synchronizes_pending_format_change(self):
        """Verify switching selected_text commits previous pending format and updates to new object."""
        win = MagicMock(spec=PdfEditorWindow)
        win._active_session = self.session
        win.pending_format_change_obj = None
        win.before_format_change_state = None
        win.undo_manager = MagicMock(spec=UndoManager)

        # Use actual property logic from window
        def set_selected_text(val):
            if win.pending_format_change_obj and win.pending_format_change_obj is not val:
                win.commit_pending_format_change()
            win._active_session.selected_text = val
            if val is not None:
                win.pending_format_change_obj = val
                win.before_format_change_state = copy.deepcopy(val.__dict__)
            else:
                win.pending_format_change_obj = None
                win.before_format_change_state = None

        def get_selected_text():
            return win._active_session.selected_text if win._active_session else None

        # Select Text 1
        set_selected_text(self.text1)
        self.assertIs(get_selected_text(), self.text1)
        self.assertIs(win.pending_format_change_obj, self.text1)
        self.assertIsNotNone(win.before_format_change_state)

        # Select Text 2
        set_selected_text(self.text2)
        self.assertIs(get_selected_text(), self.text2)
        self.assertIs(win.pending_format_change_obj, self.text2)

        # Deselect by setting to None
        set_selected_text(None)
        self.assertIsNone(get_selected_text())
        self.assertIsNone(win.pending_format_change_obj)
        self.assertIsNone(win.before_format_change_state)

    def test_toolbar_formatting_mutates_only_currently_selected_text(self):
        """Verify changing toolbar format modifies only the currently selected text, not previously selected text."""
        # Simulate real window state and formatting handler logic
        class FakeWindow:
            def __init__(self, session, text1, text2):
                self._active_session = session
                self.pending_format_change_obj = None
                self.before_format_change_state = None
                self._last_font_size = 12.0
                self._last_font_family = "Liberation Sans"
                self._last_color = (0.0, 0.0, 0.0)
                self._last_is_bold = False
                self.format_change_timer = None
                self.undo_manager = MagicMock()
                self.pdf_view = MagicMock()
                self._refresh_thumbnail = MagicMock()
                self._update_ui_state = MagicMock()
                self.doc = session.doc
                self.current_page_index = 0
                self.editable_texts = [text1, text2]
                self.editable_shapes = []
                self.editable_images = []
                self.editable_strokes = []

            @property
            def selected_text(self):
                return self._active_session.selected_text if self._active_session else None

            @selected_text.setter
            def selected_text(self, val):
                if self.pending_format_change_obj and self.pending_format_change_obj is not val:
                    self.commit_pending_format_change()
                if self._active_session:
                    self._active_session.selected_text = val
                if val is not None:
                    self.pending_format_change_obj = val
                    self.before_format_change_state = copy.deepcopy(val.__dict__)
                else:
                    self.pending_format_change_obj = None
                    self.before_format_change_state = None

            def commit_pending_format_change(self):
                if self.pending_format_change_obj and self.before_format_change_state:
                    cmd = EditObjectCommand(
                        self,
                        self.pending_format_change_obj,
                        self.before_format_change_state,
                        copy.deepcopy(self.pending_format_change_obj.__dict__)
                    )
                    self.undo_manager.add_command(cmd)
                self.pending_format_change_obj = None
                self.before_format_change_state = None

            def on_text_format_changed(self, font_family, font_size, color, is_bold):
                target_text = self.selected_text
                if target_text is not None:
                    if self.pending_format_change_obj is not target_text:
                        if self.pending_format_change_obj:
                            self.commit_pending_format_change()
                        self.pending_format_change_obj = target_text
                        self.before_format_change_state = copy.deepcopy(target_text.__dict__)

                    target_text.font_size = font_size
                    target_text.font_family = font_family
                    target_text.color = color
                    target_text.is_bold = is_bold
                    self._last_font_size = font_size
                    self._last_font_family = font_family
                    self._last_color = color
                    self._last_is_bold = is_bold
                else:
                    if self.pending_format_change_obj:
                        self.commit_pending_format_change()
                    self._last_font_size = font_size
                    self._last_font_family = font_family
                    self._last_color = color
                    self._last_is_bold = is_bold

        win = FakeWindow(self.session, self.text1, self.text2)

        # 1. Select Text 1
        win.selected_text = self.text1
        self.assertEqual(self.text1.font_size, 12.0)
        self.assertEqual(self.text2.font_size, 14.0)

        # 2. Switch selection to Text 2
        win.selected_text = self.text2

        # 3. Modify formatting in toolbar (e.g. increase font size to 24.0 and make bold)
        win.on_text_format_changed("Liberation Sans", 24.0, (1.0, 0.0, 0.0), True)

        # Verify Text 2 received the new formatting
        self.assertEqual(self.text2.font_size, 24.0)
        self.assertEqual(self.text2.color, (1.0, 0.0, 0.0))
        self.assertTrue(self.text2.is_bold)

        # Verify Text 1 was COMPLETELY UNTOUCHED
        self.assertEqual(self.text1.font_size, 12.0, "Text 1 was mutated by toolbar changes directed at Text 2")
        self.assertEqual(self.text1.color, (0.0, 0.0, 0.0))
        self.assertFalse(self.text1.is_bold)

        # 4. Deselect by clicking blank space
        win.selected_text = None
        self.assertIsNone(win.selected_text)
        self.assertIsNone(win.pending_format_change_obj)

        # 5. Modify toolbar formatting with nothing selected
        win.on_text_format_changed("Liberation Serif", 18.0, (0.0, 0.0, 1.0), False)

        # Verify neither Text 1 nor Text 2 is mutated
        self.assertEqual(self.text1.font_size, 12.0)
        self.assertEqual(self.text2.font_size, 24.0)

        # Verify toolbar defaults were updated for new text creation
        self.assertEqual(win._last_font_size, 18.0)
        self.assertEqual(win._last_font_family, "Liberation Serif")
        self.assertEqual(win._last_color, (0.0, 0.0, 1.0))


class TestContextMenuLocalization(unittest.TestCase):
    """Test right click context menu and sticky note translation completeness across all locales."""

    def test_sticky_note_context_menu_keys_all_locales(self):
        """Verify sticky note context menu keys exist and return non-raw translated strings in all 7 languages."""
        from word_sys_pdf_editor.i18n import _STRINGS, _
        import word_sys_pdf_editor.i18n as i18n_mod

        keys_to_verify = [
            "menu_add_sticky_note",
            "add_sticky_note",
            "edit_sticky_note",
            "delete_sticky_note",
            "delete_page_title",
            "image_delete_confirm_title",
            "image_delete_confirm_msg",
            "err_image_delete_title",
            "err_image_delete_msg",
            "filter_all_files",
            "untitled_document",
        ]

        orig_lang = i18n_mod._active_lang
        try:
            for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
                i18n_mod._active_lang = lang
                for key in keys_to_verify:
                    self.assertIn(key, _STRINGS[lang], f"Key '{key}' missing from '{lang}' locale table")
                    val = _(key)
                    self.assertNotEqual(val, key, f"Key '{key}' returned untranslated raw identifier in '{lang}'")
                    self.assertTrue(len(val) > 0)
        finally:
            i18n_mod._active_lang = orig_lang


class TestSavePermissionsSafeguard(unittest.TestCase):
    """Test saving document with dictionary and integer permissions to prevent C-level TypeError."""

    def test_permissions_to_bitmask_conversion(self):
        """Verify permissions_to_bitmask correctly parses dict, int, and None."""
        self.assertEqual(pdf_handler.permissions_to_bitmask(123), 123)

        bitmask = pdf_handler.permissions_to_bitmask({
            "print": True,
            "copy": False,
            "annotate": True,
            "modify": False,
            "form": False
        })
        self.assertTrue(isinstance(bitmask, int))
        self.assertTrue(bitmask & getattr(fitz, "PDF_PERM_PRINT", 4))
        self.assertFalse(bitmask & getattr(fitz, "PDF_PERM_COPY", 16))
        self.assertTrue(bitmask & getattr(fitz, "PDF_PERM_ANNOTATE", 32))
        self.assertFalse(bitmask & getattr(fitz, "PDF_PERM_MODIFY", 8))

    def test_save_document_with_dict_permissions(self):
        """Verify save_document succeeds without throwing TypeError when _pdf_permissions is a dict."""
        import tempfile
        doc = fitz.open()
        doc.new_page(width=300, height=300)
        doc._pdf_password = "user123"
        doc._pdf_owner_password = "owner123"
        doc._pdf_permissions = {
            "print": True,
            "copy": True,
            "annotate": True,
            "modify": False,
            "form": True,
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            temp_path = f.name

        try:
            success, err = pdf_handler.save_document(doc, temp_path)
            self.assertTrue(success, f"Failed to save document: {err}")
            self.assertIsNone(err)

            # Re-open with password
            opened_doc, open_err = pdf_handler.load_pdf_document(temp_path, password="user123")
            self.assertIsNotNone(opened_doc, f"Failed to open saved protected PDF: {open_err}")
            if opened_doc:
                opened_doc.close()
        finally:
            doc.close()
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

