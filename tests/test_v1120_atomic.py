import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath("."))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Adw, GObject

from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.ui_components import PageThumbnailFactory

class TestViewModePageLock(unittest.TestCase):
    def test_window_edit_mode_property(self):
        """Test edit_mode property tracks inverse of view_mode."""
        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.view_mode = True
        self.assertFalse(PdfEditorWindow.edit_mode.fget(mock_win))

        mock_win.view_mode = False
        self.assertTrue(PdfEditorWindow.edit_mode.fget(mock_win))

    def test_on_page_reorder_blocked_in_view_mode(self):
        """Test on_page_reorder returns early without moving pages when view_mode is True."""
        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.view_mode = True
        mock_win.edit_mode = False
        mock_win.doc = MagicMock()

        PdfEditorWindow.on_page_reorder(mock_win, 0, 1)

        mock_win.doc.move_page.assert_not_called()

    @unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
    def test_factory_handlers_guard_view_mode(self):
        """Test PageThumbnailFactory drag and drop closures reject operations in view mode."""
        app = Adw.Application(application_id="org.test.viewmode")
        
        def run_tests(app):
            mock_window = MagicMock()
            mock_window.view_mode = True
            mock_window.edit_mode = False

            factory = PageThumbnailFactory(editor_window=mock_window)
            list_item = MagicMock()
            
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            image = Gtk.Picture()
            label = Gtk.Label()
            box.append(image)
            box.append(label)
            list_item.get_child.return_value = box

            mock_page = MagicMock()
            mock_page.index = 0
            mock_page.thumbnail = None
            list_item.get_item.return_value = mock_page

            # Call internal _on_bind
            factory._on_bind(factory, list_item)

            box = list_item.get_child()
            controllers = list(box.observe_controllers())
            
            drag_source = None
            drop_target = None
            for ctrl in controllers:
                if isinstance(ctrl, Gtk.DragSource):
                    drag_source = ctrl
                elif isinstance(ctrl, Gtk.DropTarget):
                    drop_target = ctrl

            self.assertIsNotNone(drag_source, "DragSource should be attached")
            self.assertIsNotNone(drop_target, "DropTarget should be attached")

            # Emit prepare when in view mode -> should return None
            res = drag_source.emit("prepare", 0.0, 0.0)
            self.assertIsNone(res, "Drag prepare must return None in View Mode")

            # Emit drop when in view mode -> should return False
            val = GObject.Value(GObject.TYPE_INT, 1)
            drop_res = drop_target.emit("drop", val, 0.0, 0.0)
            self.assertFalse(drop_res, "Drop must return False in View Mode")

            # Switch to edit mode
            mock_window.view_mode = False
            mock_window.edit_mode = True

            res_edit = drag_source.emit("prepare", 0.0, 0.0)
            self.assertIsNotNone(res_edit, "Drag prepare must return ContentProvider in Edit Mode")

            drop_res_edit = drop_target.emit("drop", val, 0.0, 0.0)
            self.assertTrue(drop_res_edit, "Drop must return True in Edit Mode")
            mock_window.on_page_reorder.assert_called_once_with(1, 0)

            print("SUCCESS: View Mode Page Reordering Lock fully verified!")
            app.quit()

        app.connect("activate", run_tests)
        app.run([])

class TestDeleteConfirmationSuppression(unittest.TestCase):
    def test_settings_get_and_set(self):
        """Test get_setting and set_setting persist values properly."""
        from word_sys_pdf_editor.i18n import get_setting, set_setting
        original = get_setting("confirm_delete_objects", True)
        
        try:
            set_setting("confirm_delete_objects", False)
            self.assertFalse(get_setting("confirm_delete_objects", True))

            set_setting("confirm_delete_objects", True)
            self.assertTrue(get_setting("confirm_delete_objects", False))
        finally:
            set_setting("confirm_delete_objects", original)

    def test_handle_delete_bypasses_dialog_when_suppressed(self):
        """Test _handle_delete_with_confirmation skips dialog when confirm_delete_objects is False."""
        from word_sys_pdf_editor.i18n import set_setting, get_setting
        from word_sys_pdf_editor.models import EditableText
        from unittest.mock import patch

        original = get_setting("confirm_delete_objects", True)
        set_setting("confirm_delete_objects", False)

        try:
            mock_win = MagicMock(spec=PdfEditorWindow)
            mock_win.undo_manager = MagicMock()
            mock_win.pdf_view = MagicMock()
            mock_win.status_label = MagicMock()
            mock_win._update_ui_state = MagicMock()

            dummy_text = EditableText(x=10, y=20, text="Sample Text", is_new=True)

            with patch("word_sys_pdf_editor.ui_components.show_confirm_dialog") as mock_dialog:
                with patch("word_sys_pdf_editor.window.DeleteObjectCommand") as mock_cmd_cls:
                    mock_cmd = MagicMock()
                    mock_cmd_cls.return_value = mock_cmd

                    PdfEditorWindow._handle_delete_with_confirmation(mock_win, dummy_text, "delete_confirm_title")

                    # Dialog must NOT be called
                    mock_dialog.assert_not_called()
                    # Command must be executed and added to undo manager
                    mock_cmd.execute.assert_called_once()
                    mock_win.undo_manager.add_command.assert_called_once_with(mock_cmd)
        finally:
            set_setting("confirm_delete_objects", original)

    def test_handle_delete_prompts_and_updates_setting_on_do_not_ask(self):
        """Test dialog is prompted when confirm_delete_objects is True and updates setting when do_not_ask is checked."""
        from word_sys_pdf_editor.i18n import set_setting, get_setting
        from word_sys_pdf_editor.models import EditableShape
        from unittest.mock import patch

        original = get_setting("confirm_delete_objects", True)
        set_setting("confirm_delete_objects", True)

        try:
            mock_win = MagicMock(spec=PdfEditorWindow)
            mock_win.undo_manager = MagicMock()
            mock_win.pdf_view = MagicMock()
            mock_win.status_label = MagicMock()
            mock_win._update_ui_state = MagicMock()
            mock_win._update_confirm_delete_menu_state = MagicMock()

            dummy_shape = EditableShape(shape_type="rectangle", bbox=(10, 10, 50, 50))

            with patch("word_sys_pdf_editor.ui_components.show_confirm_dialog") as mock_dialog:
                # User accepts AND checks "Do not ask again"
                mock_dialog.return_value = (True, True)
                with patch("word_sys_pdf_editor.window.DeleteObjectCommand") as mock_cmd_cls:
                    mock_cmd = MagicMock()
                    mock_cmd_cls.return_value = mock_cmd

                    PdfEditorWindow._handle_delete_with_confirmation(mock_win, dummy_shape, "delete_confirm_title")

                    mock_dialog.assert_called_once()
                    mock_cmd.execute.assert_called_once()
                    self.assertFalse(get_setting("confirm_delete_objects", True))
                    mock_win._update_confirm_delete_menu_state.assert_called_once_with(False)
        finally:
            set_setting("confirm_delete_objects", original)
class TestLanguageSupport(unittest.TestCase):
    def test_supported_languages_list(self):
        """Test that get_supported_languages returns 7 defined languages."""
        from word_sys_pdf_editor.i18n import get_supported_languages
        langs = get_supported_languages()
        codes = [code for code, _ in langs]
        self.assertEqual(codes, ["en", "tr", "fr", "de", "es", "it", "ru"])

    def test_all_locales_present_and_complete(self):
        """Test that all 7 locales have complete dictionary translations matching en keys."""
        from word_sys_pdf_editor.i18n import _STRINGS, _
        import word_sys_pdf_editor.i18n as i18n_mod
        
        en_keys = set(_STRINGS["en"].keys())
        orig_lang = i18n_mod._active_lang

        try:
            for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
                self.assertIn(lang, _STRINGS)
                table = _STRINGS[lang]
                missing = en_keys - set(table.keys())
                self.assertEqual(len(missing), 0, f"Locale '{lang}' is missing keys: {missing}")
                
                # Test active translation lookup
                i18n_mod._active_lang = lang
                self.assertTrue(len(_("app_title")) > 0)
                self.assertTrue(len(_("btn_open")) > 0)
                self.assertTrue(len(_("confirm_delete_objects_title")) > 0)
        finally:
            i18n_mod._active_lang = orig_lang

    @unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
    def test_welcome_view_dropdown_initialization(self):
        """Test WelcomeView creates Gtk.DropDown for language selection."""
        from word_sys_pdf_editor.welcome_view import WelcomeView
        mock_win = MagicMock()
        mock_win.doc = None
        mock_win.document_modified = False

        app = Adw.Application(application_id="org.test.welcome")
        def run_view_test(app):
            view = WelcomeView(parent_window=mock_win)
            self.assertIsNotNone(view._lang_dropdown)
            self.assertEqual(len(view._languages), 7)
            app.quit()
        app.connect("activate", run_view_test)
        app.run([])

class TestPageRotationBackend(unittest.TestCase):
    def test_rotate_page_clockwise_and_counterclockwise(self):
        """Test rotating page by 90 degrees CW and CCW."""
        import fitz
        from word_sys_pdf_editor import pdf_handler

        doc = fitz.open()
        doc.new_page(width=300, height=400)
        self.assertEqual(pdf_handler.get_page_rotation(doc, 0), 0)

        # Rotate +90 CW
        success, rot = pdf_handler.rotate_page(doc, 0, 90)
        self.assertTrue(success)
        self.assertEqual(rot, 90)
        self.assertEqual(pdf_handler.get_page_rotation(doc, 0), 90)
        self.assertEqual(doc[0].rect.width, 400.0)
        self.assertEqual(doc[0].rect.height, 300.0)

        # Rotate +90 CW -> 180
        success, rot = pdf_handler.rotate_page(doc, 0, 90)
        self.assertTrue(success)
        self.assertEqual(rot, 180)

        # Rotate +90 CW -> 270
        success, rot = pdf_handler.rotate_page(doc, 0, 90)
        self.assertTrue(success)
        self.assertEqual(rot, 270)

        # Rotate +90 CW -> 0 (360 mod 360)
        success, rot = pdf_handler.rotate_page(doc, 0, 90)
        self.assertTrue(success)
        self.assertEqual(rot, 0)

        # Rotate -90 CCW -> 270
        success, rot = pdf_handler.rotate_page(doc, 0, -90)
        self.assertTrue(success)
        self.assertEqual(rot, 270)

    def test_rotate_page_invalid_index(self):
        """Test rotate_page handles out of bounds index cleanly."""
        import fitz
        from word_sys_pdf_editor import pdf_handler

        doc = fitz.open()
        doc.new_page(width=300, height=400)

        success, _ = pdf_handler.rotate_page(doc, 5, 90)
        self.assertFalse(success)

        success, _ = pdf_handler.rotate_page(doc, -1, 90)
        self.assertFalse(success)

    def test_rotate_page_command_execute_and_undo(self):
        """Test RotatePageCommand properly rotates and undoes rotation with UI notifications."""
        import fitz
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.undo_manager import RotatePageCommand

        doc = fitz.open()
        doc.new_page(width=300, height=400)

        mock_win = MagicMock()
        mock_win.doc = doc
        mock_win.current_page_index = 0
        mock_win.zoom_level = 1.0
        mock_win.document_modified = False

        cmd = RotatePageCommand(mock_win, 0, 90)
        cmd.execute()

        self.assertEqual(pdf_handler.get_page_rotation(doc, 0), 90)
        self.assertTrue(mock_win.document_modified)
        mock_win._refresh_thumbnail.assert_called_with(0)
        mock_win.pdf_view.queue_draw.assert_called()

        # Test Undo
        cmd.undo()
        self.assertEqual(pdf_handler.get_page_rotation(doc, 0), 0)
        mock_win._refresh_thumbnail.assert_called_with(0)
        mock_win.pdf_view.queue_draw.assert_called()

@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestPageRotationUI(unittest.TestCase):
    def test_rotate_current_page_and_undo_registration(self):
        """Test rotate_current_page executes RotatePageCommand and adds to undo_manager."""
        import fitz
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor import pdf_handler

        doc = fitz.open()
        doc.new_page(width=300, height=400)

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.doc = doc
        mock_win.current_page_index = 0
        mock_win.zoom_level = 1.0
        mock_win.document_modified = False
        mock_win.undo_manager = MagicMock()
        mock_win.status_label = MagicMock()

        PdfEditorWindow.rotate_current_page(mock_win, 90)

        self.assertEqual(pdf_handler.get_page_rotation(doc, 0), 90)
        self.assertTrue(mock_win.document_modified)
        mock_win.undo_manager.add_command.assert_called_once()
        mock_win.status_label.set_text.assert_called()

    def test_actions_and_accelerators(self):
        """Test that rotate actions are installed and accelerators are defined."""
        app = Adw.Application(application_id="org.test.rot_accels")
        def run_accel_test(app):
            win = PdfEditorWindow(application=app)
            self.assertIsNotNone(win.lookup_action("rotate_page_cw"))
            self.assertIsNotNone(win.lookup_action("rotate_page_ccw"))
            
            cw_accels = app.get_accels_for_action("win.rotate_page_cw")
            ccw_accels = app.get_accels_for_action("win.rotate_page_ccw")
            self.assertTrue(any("r" in a.lower() and "control" in a.lower() and "shift" in a.lower() for a in cw_accels))
            self.assertTrue(any("l" in a.lower() and "control" in a.lower() and "shift" in a.lower() for a in ccw_accels))

            self.assertIsNotNone(win.rotate_page_cw_button)
            self.assertIsNotNone(win.rotate_page_ccw_button)
            win.close()
            app.quit()
        app.connect("activate", run_accel_test)
        app.run([])

    def test_thumbnail_context_menu_controller(self):
        """Test PageThumbnailFactory attaches right click gesture for context menu."""
        app = Adw.Application(application_id="org.test.rot_menu")
        def run_menu_test(app):
            mock_win = MagicMock()
            factory = PageThumbnailFactory(editor_window=mock_win)
            list_item = MagicMock()

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            image = Gtk.Picture()
            label = Gtk.Label()
            box.append(image)
            box.append(label)
            list_item.get_child.return_value = box

            mock_page = MagicMock()
            mock_page.index = 0
            mock_page.thumbnail = None
            list_item.get_item.return_value = mock_page

            factory._on_bind(factory, list_item)

            controllers = list(box.observe_controllers())
            gesture_found = False
            for ctrl in controllers:
                if isinstance(ctrl, Gtk.GestureClick) and ctrl.get_button() == 3:
                    gesture_found = True
                    break
            self.assertTrue(gesture_found, "Right click GestureClick controller must be attached to thumbnail")
            app.quit()
        app.connect("activate", run_menu_test)
        app.run([])

class TestObjectRotationDataModel(unittest.TestCase):
    def test_models_rotation_attributes_and_setters(self):
        """Test rotation attribute and set_rotation method across all model classes."""
        from word_sys_pdf_editor.models import EditableText, EditableImage, EditableShape, EditableStroke

        # 1. EditableText
        t = EditableText(10, 10, "Hello", rotation=45.0)
        self.assertEqual(t.rotation, 45.0)
        t.set_rotation(405.0) # 405 % 360 = 45.0
        self.assertEqual(t.rotation, 45.0)
        t.set_rotation(-90.0) # -90 % 360 = 270.0
        self.assertEqual(t.rotation, 270.0)

        # 2. EditableImage
        img = EditableImage((0, 0, 100, 100), 0, None, b"fake", rotation=30.0)
        self.assertEqual(img.rotation, 30.0)
        img.set_rotation(90.0)
        self.assertEqual(img.rotation, 90.0)

        # 3. EditableShape
        s = EditableShape("rectangle", (10, 10, 50, 50), rotation=180.0)
        self.assertEqual(s.rotation, 180.0)
        s.set_rotation(0.0)
        self.assertEqual(s.rotation, 0.0)

        # 4. EditableStroke
        st = EditableStroke([(0, 0), (10, 10)], rotation=270.0)
        self.assertEqual(st.rotation, 270.0)
        st.set_rotation(360.0)
        self.assertEqual(st.rotation, 0.0)

    def test_pdf_handler_rotate_point_and_matrix(self):
        """Test rotate_point and get_rotation_matrix coordinate calculations."""
        from word_sys_pdf_editor import pdf_handler
        import math

        # Rotate point (100, 100) around center (100, 100) by 90 deg -> stays (100, 100)
        nx, ny = pdf_handler.rotate_point(100, 100, 100, 100, 90)
        self.assertAlmostEqual(nx, 100.0)
        self.assertAlmostEqual(ny, 100.0)

        # Rotate point (100, 50) around center (100, 100) by 90 deg CW -> (150, 100)
        nx, ny = pdf_handler.rotate_point(100, 50, 100, 100, 90)
        self.assertAlmostEqual(nx, 150.0)
        self.assertAlmostEqual(ny, 100.0)

        # Matrix rotation
        mat = pdf_handler.get_rotation_matrix(100, 100, 90)
        import fitz
        p = fitz.Point(100, 50) * mat
        self.assertAlmostEqual(p.x, 150.0, places=4)
        self.assertAlmostEqual(p.y, 100.0, places=4)

    def test_pdf_handler_apply_rotated_objects_to_pdf(self):
        """Test _apply_single_object_to_page successfully renders rotated objects to PDF."""
        import fitz
        from PIL import Image
        import io
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.models import EditableText, EditableShape, EditableStroke, EditableImage

        doc = fitz.open()
        page = doc.new_page(width=500, height=500)

        # 1. Rotated text
        t = EditableText(100, 100, "Rotated Text", font_size=14, rotation=45.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, t)
        self.assertTrue(success, f"Text failed: {err}")

        # 2. Rotated rectangle
        s_rect = EditableShape("rectangle", (120, 120, 220, 180), rotation=30.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, s_rect)
        self.assertTrue(success, f"Rectangle failed: {err}")

        # 3. Rotated ellipse
        s_ell = EditableShape("ellipse", (200, 200, 300, 250), rotation=60.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, s_ell)
        self.assertTrue(success, f"Ellipse failed: {err}")

        # 4. Rotated checkmark and cross
        s_chk = EditableShape("checkmark", (50, 50, 90, 90), rotation=90.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, s_chk)
        self.assertTrue(success, f"Checkmark failed: {err}")

        s_crs = EditableShape("cross", (150, 50, 190, 90), rotation=45.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, s_crs)
        self.assertTrue(success, f"Cross failed: {err}")

        # 5. Rotated stroke
        st = EditableStroke([(100, 300), (150, 350), (200, 320)], rotation=15.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, st)
        self.assertTrue(success, f"Stroke failed: {err}")

        # 6. Rotated image
        img = Image.new("RGBA", (40, 40), (0, 128, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        im_obj = EditableImage((300, 300, 340, 340), 0, None, buf.getvalue(), rotation=45.0)
        success, err = pdf_handler._apply_single_object_to_page(doc, page, im_obj)
        self.assertTrue(success, f"Image failed: {err}")

    def test_rotated_hit_testing(self):
        """Test that hit-testing accounts for object rotation around center."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.zoom_level = 1.0
        mock_win.current_page_index = 0

        # Create a tall rectangle at (100, 100, 120, 200) centered at (110, 150).
        # Width=20, Height=100.
        # Rotated 90 degrees CW around (110, 150), it becomes wide: Width=100, Height=20.
        # Unrotated box: x in [100, 120], y in [100, 200]
        # Rotated box on canvas: x in [60, 160], y in [140, 160]
        shape = EditableShape("rectangle", (100, 100, 120, 200), page_number=0, rotation=90.0)
        mock_win.editable_shapes = [shape]

        # Test point at (150, 150): on canvas it is inside the rotated shape, but x=150 is outside unrotated [100, 120]
        found = PdfEditorWindow._find_shape_at_pos(mock_win, 150, 150)
        self.assertIsNotNone(found, "Point (150, 150) must hit rotated shape")

        # Test point at (110, 190): on canvas it is outside the rotated shape, even though it was inside unrotated box
        found_outside = PdfEditorWindow._find_shape_at_pos(mock_win, 110, 190)
        self.assertIsNone(found_outside, "Point (110, 190) must NOT hit rotated shape")


class TestCanvasStalkRotationHandle(unittest.TestCase):
    def test_rotation_stalk_handle_detection_unrotated_and_rotated(self):
        """Test _find_resize_handle_at_pos detects 'rotate' at stalk tip for both unrotated and rotated objects."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape, EditableText

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.zoom_level = 1.0
        mock_win.current_pdf_page_width = 500
        mock_win.current_pdf_page_height = 500
        mock_win.pdf_view = MagicMock()
        mock_win.pdf_view.get_allocated_width.return_value = 500
        mock_win.pdf_view.get_allocated_height.return_value = 500

        # Object bbox (100, 100, 200, 200) -> center (150, 150).
        # rect_x = 97, rect_y = 97, rect_w = 106, rect_h = 106.
        # Stalk tip = (150.0, 97.0 - 22.0) = (150.0, 75.0).
        shape = EditableShape("rectangle", (100, 100, 200, 200), rotation=0.0)

        handle = PdfEditorWindow._find_resize_handle_at_pos(mock_win, 150.0, 75.0, shape)
        self.assertEqual(handle, "rotate", "Stalk handle must be detected at unrotated tip (150, 75)")

        # EditableText also supports stalk rotation handle
        text_obj = EditableText(100, 100, "Sample", rotation=0.0)
        text_obj.bbox = (100, 100, 200, 200)
        t_handle = PdfEditorWindow._find_resize_handle_at_pos(mock_win, 150.0, 75.0, text_obj)
        self.assertEqual(t_handle, "rotate", "Stalk handle must be detected for EditableText")

        # Now rotate shape by 90 degrees CW around center (150, 150).
        # The stalk tip rotates from (150, 75) by 90 deg CW to (150 + 75, 150) = (225, 150).
        shape.rotation = 90.0
        rot_handle = PdfEditorWindow._find_resize_handle_at_pos(mock_win, 225.0, 150.0, shape)
        self.assertEqual(rot_handle, "rotate", "Stalk handle must follow rotation to (225, 150)")

        # Old position (150, 75) should no longer hit the rotation handle
        old_pos_handle = PdfEditorWindow._find_resize_handle_at_pos(mock_win, 150.0, 75.0, shape)
        self.assertNotEqual(old_pos_handle, "rotate", "Old handle position must not hit rotate after 90 deg rotation")

    def test_handle_rotate_update_calculation_and_shift_snap(self):
        """Test _handle_rotate_update calculates dynamic angles and supports Shift 15-degree snapping."""
        import math
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.pdf_view = MagicMock()
        mock_win.status_label = MagicMock()

        shape = EditableShape("rectangle", (100, 100, 200, 200), rotation=0.0)
        mock_win.dragged_object = shape
        mock_win.drag_start_pos = (150.0, 75.0)  # Top handle position
        mock_win.rotate_center = (150.0, 150.0)
        mock_win.rotate_start_angle = 0.0
        # Start angle from center (150, 150) to (150, 75): dx=0, dy=-75 -> -90 deg
        mock_win.rotate_pointer_start_angle = -90.0

        mock_gesture = MagicMock()
        mock_gesture.get_current_event_state.return_value = 0  # No Shift

        # Drag pointer 90 deg CW to (225.0, 150.0) -> offset_x = +75.0, offset_y = +75.0
        PdfEditorWindow._handle_rotate_update(mock_win, mock_gesture, 75.0, 75.0)
        self.assertAlmostEqual(shape.rotation, 90.0, places=1)
        mock_win.pdf_view.queue_draw.assert_called()

        # Drag pointer to an arbitrary angle (e.g. 41.2 degrees) WITHOUT Shift
        # Center is (150, 150). We want pointer at angle (-90 + 41.2) = -48.8 deg.
        target_rad = math.radians(-48.8)
        cur_x = 150.0 + 75.0 * math.cos(target_rad)
        cur_y = 150.0 + 75.0 * math.sin(target_rad)
        off_x = cur_x - 150.0
        off_y = cur_y - 75.0
        PdfEditorWindow._handle_rotate_update(mock_win, mock_gesture, off_x, off_y)
        self.assertAlmostEqual(shape.rotation, 41.2, places=1)

        # Now test WITH Shift key pressed -> snaps 41.2 deg to nearest 15 deg (45.0 deg)
        mock_gesture.get_current_event_state.return_value = Gdk.ModifierType.SHIFT_MASK
        PdfEditorWindow._handle_rotate_update(mock_win, mock_gesture, off_x, off_y)
        self.assertAlmostEqual(shape.rotation, 45.0, places=1)

        # Test Shift snapping near 0 deg (e.g. 6.0 deg snaps to 0.0 deg)
        target_rad_small = math.radians(-90.0 + 6.0)
        cur_x_small = 150.0 + 75.0 * math.cos(target_rad_small)
        cur_y_small = 150.0 + 75.0 * math.sin(target_rad_small)
        PdfEditorWindow._handle_rotate_update(mock_win, mock_gesture, cur_x_small - 150.0, cur_y_small - 75.0)
        self.assertAlmostEqual(shape.rotation, 0.0, places=1)

    def test_on_drag_end_commits_rotation_command(self):
        """Test on_drag_end commits EditObjectCommand when rotation changed even if drag offset is zero."""
        import copy
        import fitz
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape
        from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand, RotateObjectCommand

        mock_win = MagicMock(spec=PdfEditorWindow)
        doc = fitz.open()
        doc.new_page(width=500, height=500)
        mock_win.doc = doc
        mock_win.current_page_index = 0
        mock_win.editable_shapes = []
        mock_win.editable_texts = []
        mock_win.editable_images = []
        mock_win.editable_strokes = []
        mock_win.view_mode = False
        mock_win.inline_editor_widget = None
        mock_win.dragging_to_create = False
        mock_win.temp_stroke = None
        mock_win.temp_shape = None
        mock_win.temp_image_bbox = None
        mock_win.undo_manager = MagicMock(spec=UndoManager)
        mock_win.pdf_view = MagicMock()
        mock_win.status_label = MagicMock()
        mock_win.commit_pending_format_change = MagicMock()
        mock_win._update_ui_state = MagicMock()
        mock_win._refresh_thumbnail = MagicMock()

        shape = EditableShape("rectangle", (100, 100, 200, 200), page_number=0, rotation=0.0)
        mock_win.editable_shapes.append(shape)
        mock_win.dragged_object = shape
        mock_win.drag_begin_state = copy.deepcopy(shape.__dict__)
        mock_win.rotate_center = (150.0, 150.0)
        mock_win.rotate_start_angle = 0.0
        mock_win.rotate_pointer_start_angle = -90.0

        # Change rotation during drag
        shape.rotation = 45.0

        # End drag with 0 offset (pointer ended near origin or completed loop)
        mock_gesture = MagicMock()
        PdfEditorWindow.on_drag_end(mock_win, mock_gesture, 0.0, 0.0)

        # Check rotation attributes cleaned up
        self.assertFalse(hasattr(mock_win, 'rotate_center'))
        self.assertFalse(hasattr(mock_win, 'rotate_start_angle'))
        self.assertFalse(hasattr(mock_win, 'rotate_pointer_start_angle'))
        self.assertIsNone(mock_win.dragged_object)

        # Command must be added to undo manager because rot_changed is True
        mock_win.undo_manager.add_command.assert_called_once()
        cmd = mock_win.undo_manager.add_command.call_args[0][0]
        self.assertIsInstance(cmd, RotateObjectCommand)
        self.assertEqual(cmd.old_rotation, 0.0)
        self.assertEqual(cmd.new_rotation, 45.0)


class TestObjectRotationToolbarAndUndo(unittest.TestCase):
    def test_rotate_object_command_execute_and_undo(self):
        """Test RotateObjectCommand execution, PDF baking, and undo reversion."""
        import fitz
        from word_sys_pdf_editor.models import EditableShape
        from word_sys_pdf_editor.undo_manager import RotateObjectCommand

        mock_win = MagicMock()
        doc = fitz.open()
        doc.new_page(width=400, height=400)
        mock_win.doc = doc
        mock_win.editable_shapes = []
        mock_win.editable_texts = []
        mock_win.editable_images = []
        mock_win.editable_strokes = []

        shape = EditableShape("rectangle", (50, 50, 150, 150), page_number=0, rotation=0.0)
        mock_win.editable_shapes.append(shape)

        cmd = RotateObjectCommand(mock_win, shape, old_rotation=0.0, new_rotation=90.0)
        cmd.execute()

        self.assertEqual(shape.rotation, 90.0)
        self.assertTrue(mock_win.document_modified)
        mock_win.status_label.set_text.assert_called()

        # Undo command
        cmd.undo()
        self.assertEqual(shape.rotation, 0.0)

    def test_quick_rotate_buttons(self):
        """Test CW and CCW 90-degree quick rotate buttons and 0-degree reset."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape
        from word_sys_pdf_editor.undo_manager import RotateObjectCommand

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.undo_manager = MagicMock()
        mock_win.selected_text = None
        mock_win.selected_image = None
        mock_win.selected_stroke = None

        shape = EditableShape("rectangle", (50, 50, 150, 150), rotation=0.0)
        mock_win.selected_shape = shape

        # 1. Rotate CW by 90
        PdfEditorWindow.on_rotate_object_cw_clicked(mock_win)
        self.assertEqual(mock_win.undo_manager.add_command.call_count, 1)
        cmd1 = mock_win.undo_manager.add_command.call_args[0][0]
        self.assertIsInstance(cmd1, RotateObjectCommand)
        self.assertEqual(cmd1.old_rotation, 0.0)
        self.assertEqual(cmd1.new_rotation, 90.0)

        # Update shape rotation to 90 as command would
        shape.rotation = 90.0

        # 2. Rotate CCW by 90 (90 -> 0)
        PdfEditorWindow.on_rotate_object_ccw_clicked(mock_win)
        self.assertEqual(mock_win.undo_manager.add_command.call_count, 2)
        cmd2 = mock_win.undo_manager.add_command.call_args[0][0]
        self.assertEqual(cmd2.old_rotation, 90.0)
        self.assertEqual(cmd2.new_rotation, 0.0)

        # 3. Rotate CCW again (0 -> 270)
        shape.rotation = 0.0
        PdfEditorWindow.on_rotate_object_ccw_clicked(mock_win)
        self.assertEqual(mock_win.undo_manager.add_command.call_count, 3)
        cmd3 = mock_win.undo_manager.add_command.call_args[0][0]
        self.assertEqual(cmd3.old_rotation, 0.0)
        self.assertEqual(cmd3.new_rotation, 270.0)

        # 4. Reset button (270 -> 0)
        shape.rotation = 270.0
        PdfEditorWindow.on_rotate_object_reset_clicked(mock_win)
        self.assertEqual(mock_win.undo_manager.add_command.call_count, 4)
        cmd4 = mock_win.undo_manager.add_command.call_args[0][0]
        self.assertEqual(cmd4.old_rotation, 270.0)
        self.assertEqual(cmd4.new_rotation, 0.0)

    def test_spin_button_value_changed(self):
        """Test numeric angle spin button changes commit RotateObjectCommand."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape
        from word_sys_pdf_editor.undo_manager import RotateObjectCommand

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.undo_manager = MagicMock()
        mock_win.selected_text = None
        mock_win.selected_image = None
        mock_win.selected_stroke = None

        shape = EditableShape("rectangle", (50, 50, 150, 150), rotation=15.0)
        mock_win.selected_shape = shape

        mock_spin = MagicMock()
        mock_spin.get_value.return_value = 45.0

        PdfEditorWindow.on_object_rotation_spin_changed(mock_win, mock_spin)
        mock_win.undo_manager.add_command.assert_called_once()
        cmd = mock_win.undo_manager.add_command.call_args[0][0]
        self.assertIsInstance(cmd, RotateObjectCommand)
        self.assertEqual(cmd.old_rotation, 15.0)
        self.assertEqual(cmd.new_rotation, 45.0)

    def test_update_rotation_controls_sync(self):
        """Test _update_rotation_controls sets spin value and reset button sensitivity."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableShape

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.rotation_spin = MagicMock()
        mock_win.rotate_obj_reset_button = MagicMock()
        mock_win.rotate_obj_cw_button = MagicMock()
        mock_win.rotate_obj_ccw_button = MagicMock()

        # 1. Non-zero rotation: reset button sensitive
        shape = EditableShape("rectangle", (50, 50, 150, 150), rotation=45.0)
        PdfEditorWindow._update_rotation_controls(mock_win, shape)
        mock_win.rotation_spin.set_value.assert_called_with(45)
        mock_win.rotate_obj_reset_button.set_sensitive.assert_called_with(True)

        # 2. Zero rotation: reset button not sensitive
        shape_zero = EditableShape("rectangle", (50, 50, 150, 150), rotation=0.0)
        PdfEditorWindow._update_rotation_controls(mock_win, shape_zero)
        mock_win.rotation_spin.set_value.assert_called_with(0)
        mock_win.rotate_obj_reset_button.set_sensitive.assert_called_with(False)

        # 3. No object selected: reset button and rotate buttons disabled
        PdfEditorWindow._update_rotation_controls(mock_win, None)
        mock_win.rotation_spin.set_value.assert_called_with(0)
        mock_win.rotate_obj_reset_button.set_sensitive.assert_called_with(False)
        mock_win.rotate_obj_cw_button.set_sensitive.assert_called_with(False)
        mock_win.rotate_obj_ccw_button.set_sensitive.assert_called_with(False)


class TestRecentlyOpenedFilesHub(unittest.TestCase):
    def setUp(self):
        import tempfile
        from word_sys_pdf_editor.i18n import get_setting, set_setting
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_recents = get_setting("recent_opened_files", [])
        set_setting("recent_opened_files", [])

    def tearDown(self):
        from word_sys_pdf_editor.i18n import set_setting
        set_setting("recent_opened_files", self.orig_recents)
        self.tmp_dir.cleanup()

    def test_record_recent_file_prepends_deduplicates_and_limits(self):
        """Test _record_recent_file prepends, deduplicates, and caps at 15 files."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.i18n import get_setting

        mock_win = MagicMock(spec=PdfEditorWindow)

        # Create 20 mock files
        files = []
        for i in range(20):
            p = os.path.join(self.tmp_dir.name, f"doc_{i}.pdf")
            with open(p, "w") as f:
                f.write("content")
            files.append(p)

        # Record first 5 files
        for p in files[:5]:
            PdfEditorWindow._record_recent_file(mock_win, p)

        recents = get_setting("recent_opened_files", [])
        self.assertEqual(len(recents), 5)
        # Most recent should be at index 0
        self.assertEqual(recents[0], os.path.abspath(files[4]))

        # Re-recording files[1] should move it to index 0 without duplicating
        PdfEditorWindow._record_recent_file(mock_win, files[1])
        recents = get_setting("recent_opened_files", [])
        self.assertEqual(len(recents), 5)
        self.assertEqual(recents[0], os.path.abspath(files[1]))
        self.assertEqual(recents.count(os.path.abspath(files[1])), 1)

        # Record all 20 files - must cap at 15
        for p in files:
            PdfEditorWindow._record_recent_file(mock_win, p)

        recents = get_setting("recent_opened_files", [])
        self.assertEqual(len(recents), 15)
        self.assertEqual(recents[0], os.path.abspath(files[-1]))

    @unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
    def test_welcome_view_populates_valid_files_and_prunes_missing(self):
        """Test WelcomeView populates valid files and prunes non-existent ones."""
        from word_sys_pdf_editor.welcome_view import WelcomeView
        from word_sys_pdf_editor.i18n import get_setting, set_setting

        # Create 2 valid files and 1 non-existent path
        valid1 = os.path.join(self.tmp_dir.name, "valid1.pdf")
        valid2 = os.path.join(self.tmp_dir.name, "valid2.pdf")
        missing = os.path.join(self.tmp_dir.name, "missing.pdf")
        with open(valid1, "w") as f: f.write("1")
        with open(valid2, "w") as f: f.write("2")

        set_setting("recent_opened_files", [valid1, missing, valid2])

        mock_win = MagicMock()
        welcome = WelcomeView(parent_window=mock_win)

        # Missing file should have been pruned from settings
        recents_after = get_setting("recent_opened_files", [])
        self.assertIn(valid1, recents_after)
        self.assertIn(valid2, recents_after)
        self.assertNotIn(missing, recents_after)

        # 2 rows should be present
        rows = []
        child = welcome.recent_list_box.get_first_child()
        while child:
            rows.append(child)
            child = child.get_next_sibling()
        self.assertEqual(len(rows), 2)
        self.assertTrue(welcome.recent_box.get_visible())

    @unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
    def test_welcome_view_row_structure_and_universal_icon(self):
        """Test WelcomeView row has universal icon with accent class and 28px size."""
        from word_sys_pdf_editor.welcome_view import WelcomeView

        valid_pdf = os.path.join(self.tmp_dir.name, "test_doc.pdf")
        with open(valid_pdf, "w") as f: f.write("pdf")

        mock_win = MagicMock()
        welcome = WelcomeView(parent_window=mock_win)
        row = welcome._create_recent_file_row(valid_pdf)

        self.assertEqual(row._file_path, valid_pdf)
        self.assertTrue(row._uri.startswith("file://"))

        # Check box child and icon
        box = row.get_child()
        self.assertIsInstance(box, Gtk.Box)

        first_child = box.get_first_child()
        self.assertIsInstance(first_child, Gtk.Image)
        self.assertEqual(first_child.get_pixel_size(), 28)
        self.assertTrue(first_child.has_css_class("accent"))

    @unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
    def test_welcome_view_row_activation_calls_load_document(self):
        """Test activating recent row calls parent_window.load_document."""
        from word_sys_pdf_editor.welcome_view import WelcomeView

        valid_pdf = os.path.join(self.tmp_dir.name, "active.pdf")
        with open(valid_pdf, "w") as f: f.write("pdf")

        mock_win = MagicMock()
        welcome = WelcomeView(parent_window=mock_win)
        row = welcome._create_recent_file_row(valid_pdf)

        welcome._on_recent_row_activated(welcome.recent_list_box, row)
        mock_win.load_document.assert_called_once_with(valid_pdf)

    def test_window_finish_loading_records_recent_file(self):
        """Test window._finish_loading automatically records recent file."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.i18n import get_setting

        valid_pdf = os.path.join(self.tmp_dir.name, "opened.pdf")
        with open(valid_pdf, "w") as f: f.write("pdf")

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.doc = None
        mock_win.status_label = MagicMock()
        mock_win.open_button = MagicMock()
        mock_win.select_tool_button = MagicMock()
        mock_win.add_text_tool_button = MagicMock()
        mock_win._record_recent_file.side_effect = lambda p: PdfEditorWindow._record_recent_file(mock_win, p)

        mock_doc = MagicMock()
        mock_doc.is_repaired = False

        PdfEditorWindow._finish_loading(mock_win, mock_doc, None, valid_pdf, 0)

        mock_win._record_recent_file.assert_called_once_with(valid_pdf)
        recents = get_setting("recent_opened_files", [])
        self.assertIn(os.path.abspath(valid_pdf), recents)


class TestTextRotationDirectionAndPageRotationHitboxes(unittest.TestCase):
    def test_text_rotation_direction_clockwise(self):
        """Test text rotation rotates clockwise in PDF, matching underline and hitbox."""
        import fitz
        import json
        from word_sys_pdf_editor.models import EditableText
        from word_sys_pdf_editor import pdf_handler

        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        t = EditableText(100, 100, "Clockwise Text", font_size=20, rotation=45.0)
        t.is_underline = True

        success, err = pdf_handler._apply_single_object_to_page(doc, page, t)
        self.assertTrue(success, f"Failed applying text: {err}")

        # Check line direction in rawjson
        raw = json.loads(page.get_text("rawjson"))
        line_dir = raw["blocks"][0]["lines"][0]["dir"]
        # Clockwise rotation in screen space (y increases downwards) must have positive dy
        self.assertAlmostEqual(line_dir[0], 0.7071, places=3)
        self.assertAlmostEqual(line_dir[1], 0.7071, places=3)

    def test_rotate_page_command_transforms_object_hitboxes(self):
        """Test RotatePageCommand preserves object coordinates in unrotated cropbox space without displacement."""
        import fitz
        from word_sys_pdf_editor.models import EditableShape, EditableText, EditableStroke, EditableImage
        from word_sys_pdf_editor.undo_manager import RotatePageCommand

        doc = fitz.open()
        page = doc.new_page(width=500, height=800)

        mock_win = MagicMock()
        mock_win.doc = doc
        mock_win.current_page_index = 0
        mock_win.zoom_level = 1.0

        shape = EditableShape("rectangle", (100, 100, 300, 200), page_number=0, rotation=0.0)
        text = EditableText(100, 100, "Hello", page_number=0, rotation=0.0)
        text.bbox = (100, 100, 200, 150)
        stroke = EditableStroke([(100, 200), (300, 400)], page_number=0, rotation=0.0)
        img = EditableImage((50, 50, 150, 150), page_number=0, xref=1, image_bytes=b"fake", rotation=0.0)

        mock_win.editable_shapes = [shape]
        mock_win.editable_texts = [text]
        mock_win.editable_strokes = [stroke]
        mock_win.editable_images = [img]

        # Rotate 90 CW: in unrotated cropbox space, objects retain exact natural coordinates
        cmd = RotatePageCommand(mock_win, 0, 90)
        cmd.execute()

        self.assertEqual(shape.bbox, (100, 100, 300, 200))
        self.assertEqual(shape.rotation, 0.0)
        self.assertEqual(text.bbox, (100, 100, 200, 150))
        self.assertEqual(text.rotation, 0.0)
        self.assertEqual(img.bbox, (50, 50, 150, 150))
        self.assertEqual(img.rotation, 0.0)
        self.assertEqual(stroke.points, [(100, 200), (300, 400)])
        self.assertEqual(stroke.rotation, 0.0)

        # Undo: reverts page rotation, objects stay preserved
        cmd.undo()
        self.assertEqual(shape.bbox, (100, 100, 300, 200))
        self.assertEqual(shape.rotation, 0.0)
        self.assertEqual(text.bbox, (100, 100, 200, 150))
        self.assertEqual(text.rotation, 0.0)
        self.assertEqual(img.bbox, (50, 50, 150, 150))
        self.assertEqual(img.rotation, 0.0)
        self.assertEqual(stroke.points, [(100, 200), (300, 400)])
        self.assertEqual(stroke.rotation, 0.0)

    def test_extract_objects_from_rotated_page(self):
        """Test extracting objects from a rotated page extracts in unrotated cropbox coordinates."""
        import fitz
        from word_sys_pdf_editor import pdf_handler

        doc = fitz.open()
        page = doc.new_page(width=500, height=800)
        page.draw_rect(fitz.Rect(100, 100, 300, 200), color=(1, 0, 0), fill=(1, 0, 0))
        page.insert_text(fitz.Point(100, 200), "Rotated Page Text")
        page.set_rotation(90)

        # In cropbox space, shape bbox is (100, 100, 300, 200)
        shapes, _err = pdf_handler.extract_editable_shapes(doc, 0)
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0].bbox, (100.0, 100.0, 300.0, 200.0))
        self.assertEqual(shapes[0].rotation, 0.0)

        texts, _err = pdf_handler.extract_editable_text(doc, 0)
        self.assertTrue(len(texts) >= 1)
        self.assertEqual(texts[0].rotation, 0.0)
        # Text bbox in cropbox space is near origin (100, 200)
        self.assertTrue(90 <= texts[0].bbox[0] <= 110)
        self.assertTrue(180 <= texts[0].bbox[1] <= 210)

    def test_link_insertion_on_rotated_page_no_fz_format_double(self):
        """Verify link insertion on rotated page does not trigger fz_format_double type error."""
        import fitz
        from word_sys_pdf_editor.models import EditableText
        from word_sys_pdf_editor.pdf_handler import _apply_single_object_to_page

        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.set_rotation(180)

        text_with_link = EditableText(
            x=100, y=100,
            text="Visit https://github.com/word-sys for info",
            page_number=0,
            rotation=0.0
        )
        text_with_link.bbox = (100, 90, 400, 110)
        text_with_link.baseline = 105.0

        success, err = _apply_single_object_to_page(doc, page, text_with_link)
        self.assertTrue(success, f"_apply_single_object_to_page failed: {err}")
        self.assertIsNone(err)

    def test_erase_ghost_on_180_degree_rotated_page(self):
        """Verify _erase_ghost_if_needed cleanly redacts text using cropbox coordinates on rotated pages."""
        import fitz
        from word_sys_pdf_editor.models import EditableText
        from word_sys_pdf_editor.undo_manager import EditObjectCommand

        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text(fitz.Point(100, 100), "Hello Original")
        page.set_rotation(180)

        # In unrotated cropbox space:
        cropbox_bbox = (95.0, 80.0, 180.0, 115.0)
        text_obj = EditableText(100.0, 88.0, "Hello Original", page_number=0, rotation=0.0)
        text_obj.bbox = cropbox_bbox
        text_obj.original_bbox = cropbox_bbox
        text_obj.baseline = 100.0
        text_obj.is_new = False
        text_obj._ghost_redacted = False

        mock_win = MagicMock()
        mock_win.doc = doc
        mock_win.editable_texts = [text_obj]
        mock_win.editable_shapes = []
        mock_win.editable_images = []
        mock_win.editable_strokes = []

        cmd = EditObjectCommand(mock_win, text_obj, {'text': 'Hello Original', 'bbox': cropbox_bbox}, {'text': 'Hello Edited', 'bbox': cropbox_bbox})
        cmd._erase_ghost_if_needed(0, {'text': 'Hello Original', 'bbox': cropbox_bbox})

        # Redaction should have cleanly removed the text from the page in doc
        reloaded = doc.load_page(0)
        raw_text = reloaded.get_text()
        self.assertNotIn("Hello Original", raw_text)

    def test_text_formatting_available_after_rotation(self):
        """Verify that rotating an object keeps pending_format_change_obj updated so formatting can be changed immediately."""
        from word_sys_pdf_editor.models import EditableText
        from word_sys_pdf_editor.undo_manager import RotateObjectCommand

        text_obj = EditableText(100, 100, "Sample Text", page_number=0, rotation=0.0)
        mock_win = MagicMock()
        mock_win.doc = None
        mock_win.selected_text = text_obj
        mock_win.pending_format_change_obj = None
        mock_win.before_format_change_state = None

        cmd = RotateObjectCommand(mock_win, text_obj, 0.0, 90.0)
        cmd.execute()

        self.assertEqual(text_obj.rotation, 90.0)
        self.assertIs(mock_win.pending_format_change_obj, text_obj)
        self.assertIsNotNone(mock_win.before_format_change_state)

    def test_existing_image_move_on_rotated_page_leaves_zero_ghost_texture(self):
        """Verify moving an existing image on a rotated page does not leave a ghost texture at the old position."""
        import fitz
        from PIL import Image
        import io
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.undo_manager import EditObjectCommand

        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        img = Image.new('RGB', (50, 50), color='blue')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        orig_rect = fitz.Rect(50, 50, 100, 100)
        page.insert_image(orig_rect, stream=buf.getvalue())

        doc = fitz.open('pdf', doc.tobytes())
        page = doc[0]
        page.set_rotation(270)

        pdf_handler.save_page_snapshot(doc, 0)
        extracted, _ = pdf_handler.extract_editable_images(doc, 0)
        img_obj = extracted[0]

        mock_win = MagicMock()
        mock_win.doc = doc
        mock_win.current_page_index = 0
        mock_win.editable_texts = []
        mock_win.editable_shapes = []
        mock_win.editable_images = [img_obj]
        mock_win.editable_strokes = []

        old_props = dict(img_obj.__dict__)
        new_props = dict(old_props)
        new_props['bbox'] = (200, 200, 250, 250)
        new_props['x'] = 200
        new_props['y'] = 200

        cmd = EditObjectCommand(mock_win, img_obj, old_props, new_props)
        cmd.execute()

        pix = page.get_pixmap()
        # In rotation 270, unrot (50, 50, 100, 100) is visual (50, 300, 100, 350)
        # and unrot (200, 200, 250, 250) is visual (200, 150, 250, 200)
        old_blue = sum(1 for y in range(300, 350) for x in range(50, 100) if pix.pixel(x, y)[2] > 100 and pix.pixel(x, y)[0] < 50)
        new_blue = sum(1 for y in range(150, 200) for x in range(200, 250) if pix.pixel(x, y)[2] > 100 and pix.pixel(x, y)[0] < 50)

        self.assertEqual(old_blue, 0, "Old image position should have 0 blue pixels (ghost erased completely)")
        self.assertEqual(new_blue, 2500, "New image position should have 2500 blue pixels")

    def test_text_repeated_rotation_and_edit_no_duplicates(self):
        """Verify that rotating an existing text multiple times and editing it creates no duplicate text."""
        import fitz
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.models import EditableText
        from word_sys_pdf_editor.undo_manager import RotateObjectCommand, EditObjectCommand

        doc = fitz.open()
        page = doc.new_page(width=500, height=500)
        page.insert_text(fitz.Point(50, 100), "AlphaBeta", fontsize=16)
        doc = fitz.open('pdf', doc.tobytes())
        page = doc[0]

        pdf_handler.save_page_snapshot(doc, 0)
        texts, _ = pdf_handler.extract_editable_text(doc, 0)
        t_obj = texts[0]

        mock_win = MagicMock()
        mock_win.doc = doc
        mock_win.current_page_index = 0
        mock_win.editable_texts = [t_obj]
        mock_win.editable_shapes = []
        mock_win.editable_images = []
        mock_win.editable_strokes = []

        # Rotate 45 deg
        cmd_rot1 = RotateObjectCommand(mock_win, t_obj, 0.0, 45.0)
        cmd_rot1.execute()
        self.assertEqual(page.get_text().count("AlphaBeta"), 1)

        # Rotate 90 deg
        cmd_rot2 = RotateObjectCommand(mock_win, t_obj, 45.0, 90.0)
        cmd_rot2.execute()
        self.assertEqual(page.get_text().count("AlphaBeta"), 1)

        # Move text
        old_t = dict(t_obj.__dict__)
        new_t = dict(old_t)
        new_t['bbox'] = (200, 200, 300, 230)
        new_t['x'] = 200
        new_t['y'] = 200
        new_t['baseline'] = 220
        cmd_move = EditObjectCommand(mock_win, t_obj, old_t, new_t)
        cmd_move.execute()
        self.assertEqual(page.get_text().count("AlphaBeta"), 1)

        # Edit text
        old_t2 = dict(t_obj.__dict__)
        new_t2 = dict(old_t2)
        new_t2['text'] = "GammaDelta"
        cmd_edit = EditObjectCommand(mock_win, t_obj, old_t2, new_t2)
        cmd_edit.execute()
        self.assertEqual(page.get_text().count("AlphaBeta"), 0)
        self.assertEqual(page.get_text().count("GammaDelta"), 1)

    def test_underlined_text_move_no_duplicate_underline(self):
        """Test moving an underlined text after save erases the old underline and does not duplicate it."""
        import copy
        import fitz
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableText

        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        text_obj = EditableText(
            50, 100, "TEST UNDERLINE TEXT", font_size=14.0, is_new=True
        )
        text_obj.is_underline = True
        text_obj.page_number = 0
        text_obj.bbox = (50, 85, 250, 105)
        text_obj.baseline = 100.0

        pdf_handler._apply_single_object_to_page(doc, page, text_obj)
        tmp_path = "/tmp/test_underline_move.pdf"
        success, _ = pdf_handler.save_document(doc, tmp_path, incremental=False)
        self.assertTrue(success)

        saved_doc = fitz.open(tmp_path)
        saved_page = saved_doc[0]
        drawings_initial = saved_page.get_drawings()
        self.assertGreaterEqual(len(drawings_initial), 1)

        editables, _ = pdf_handler.extract_editable_text(saved_doc, 0)
        self.assertEqual(len(editables), 1)
        extracted_text = editables[0]
        self.assertTrue(extracted_text.is_underline)
        self.assertEqual(extracted_text.original_baseline, extracted_text.baseline)

        old_baseline = extracted_text.baseline
        old_bbox = extracted_text.bbox

        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.doc = saved_doc
        mock_win.current_page_index = 0
        mock_win.editable_texts = [extracted_text]
        mock_win.editable_shapes = []
        mock_win.editable_images = []
        mock_win.editable_strokes = []
        mock_win.view_mode = False
        mock_win.inline_editor_widget = None
        mock_win.undo_manager = MagicMock(spec=UndoManager)
        mock_win.pdf_view = MagicMock()
        mock_win.status_label = MagicMock()
        mock_win._refresh_thumbnail = MagicMock()
        mock_win._update_ui_state = MagicMock()

        pdf_handler.save_page_snapshot(saved_doc, 0)

        old_props = copy.deepcopy(extracted_text.__dict__)

        # Simulate drag update: mutate object position and baseline to a new position
        new_y = 200.0
        extracted_text.y = new_y
        extracted_text.baseline = new_y + 14.0
        extracted_text.bbox = (50, new_y - 15.0, 250, new_y + 15.0)

        new_props = copy.deepcopy(extracted_text.__dict__)

        cmd = EditObjectCommand(mock_win, extracted_text, old_props, new_props)
        cmd.execute()

        # Check drawings in snapshot/page around the old baseline:
        saved_page = saved_doc[0]
        drawings_after = saved_page.get_drawings()
        for d in drawings_after:
            d_rect = d.get('rect')
            if d_rect:
                # Assert no drawing remains at the old baseline
                self.assertFalse(
                    abs(d_rect.y0 - (old_baseline + 1.5)) < 2.0 and d_rect.x0 < old_bbox[2] and d_rect.x1 > old_bbox[0],
                    f"Duplicate underline found at old baseline {old_baseline}"
                )

    def test_highlight_function_on_rotated_page(self):
        """Test highlight annotations on rotated pages in both Edit mode and View mode."""
        import fitz
        from word_sys_pdf_editor import pdf_handler

        for rot in (90, 180, 270):
            doc = fitz.open()
            page = doc.new_page(width=300, height=400)
            page.insert_text(fitz.Point(50, 100), "ROTATED TEST", fontsize=16)
            page.set_rotation(rot)

            unrot_bbox = (50.0, 82.0, 180.0, 105.0)

            # 1. Edit mode: is_visual=False (bbox is already in unrotated coordinates)
            success, err = pdf_handler.add_highlight_annotation(
                doc, 0, unrot_bbox, color=(1, 1, 0), is_visual=False
            )
            self.assertTrue(success, f"Failed in edit mode rotation {rot}: {err}")

            annots = list(page.annots())
            self.assertEqual(len(annots), 1)
            # The annotation quad vertices must be in unrotated page coordinates
            verts = annots[0].vertices
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            self.assertAlmostEqual(min(xs), 50.0, delta=2.0)
            self.assertAlmostEqual(max(xs), 180.0, delta=2.0)
            self.assertAlmostEqual(min(ys), 82.0, delta=2.0)
            self.assertAlmostEqual(max(ys), 105.0, delta=2.0)

            # Remove highlight in edit mode
            rem_success, count = pdf_handler.remove_highlight_annotations(
                doc, 0, unrot_bbox, is_visual=False
            )
            self.assertTrue(rem_success)
            self.assertEqual(count, 1)
            self.assertEqual(len(list(page.annots())), 0)

            # 2. View mode: is_visual=True (bbox is in visual canvas coordinates)
            vis_rect = (fitz.Rect(unrot_bbox) * page.rotation_matrix).normalize()
            vis_bbox = (vis_rect.x0, vis_rect.y0, vis_rect.x1, vis_rect.y1)

            success_vm, err_vm = pdf_handler.add_highlight_annotation(
                doc, 0, vis_bbox, color=(1, 1, 0), is_visual=True
            )
            self.assertTrue(success_vm, f"Failed in view mode rotation {rot}: {err_vm}")

            annots_vm = list(page.annots())
            self.assertEqual(len(annots_vm), 1)
            verts_vm = annots_vm[0].vertices
            xs_vm = [v[0] for v in verts_vm]
            ys_vm = [v[1] for v in verts_vm]
            self.assertAlmostEqual(min(xs_vm), 50.0, delta=2.0)
            self.assertAlmostEqual(max(xs_vm), 180.0, delta=2.0)

            # Remove highlight in view mode
            rem_vm_success, count_vm = pdf_handler.remove_highlight_annotations(
                doc, 0, vis_bbox, is_visual=True
            )
            self.assertTrue(rem_vm_success)
            self.assertEqual(count_vm, 1)
            self.assertEqual(len(list(page.annots())), 0)

    def test_highlight_function_with_rotated_text_object(self):
        """Test highlight annotation on text object that has its own rotation angle."""
        import fitz
        from word_sys_pdf_editor import pdf_handler

        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        unrot_bbox = (100.0, 100.0, 250.0, 130.0)

        success, err = pdf_handler.add_highlight_annotation(
            doc, 0, unrot_bbox, color=(1, 1, 0), is_visual=False, rotation=45.0
        )
        self.assertTrue(success, f"Failed on rotated text highlight: {err}")

        annots = list(page.annots())
        self.assertEqual(len(annots), 1)
        annot = annots[0]
        # Quad vertices must be rotated
        verts = annot.vertices
        self.assertEqual(len(verts), 4)
        # Verify rendered pixmap contains highlight pixels
        pix = page.get_pixmap()
        yellow_count = sum(1 for y in range(pix.height) for x in range(pix.width) if pix.pixel(x, y)[0] > 200 and pix.pixel(x, y)[1] > 200 and pix.pixel(x, y)[2] < 100)
        self.assertGreater(yellow_count, 100)



class TestTextStrikethrough(unittest.TestCase):
    """Atomic unit tests for Text Strikethrough."""

    def test_editable_text_is_strikethrough_default_and_mutation(self):
        """EditableText must default to is_strikethrough=False and allow mutation."""
        import copy
        from word_sys_pdf_editor.models import EditableText
        t = EditableText(10, 20, "Strike Test")
        self.assertFalse(t.is_strikethrough)
        t.is_strikethrough = True
        self.assertTrue(t.is_strikethrough)
        c = copy.deepcopy(t)
        self.assertTrue(c.is_strikethrough)

    def test_strikethrough_vector_baking(self):
        """PyMuPDF backend must bake strikethrough vector line at baseline - (0.3 * font_size)."""
        import fitz
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.models import EditableText

        doc, _ = pdf_handler.create_new_pdf(width=400, height=400, num_pages=1)
        page = doc.load_page(0)
        t = EditableText(50, 100, "Bake Strikethrough", font_size=15.0, is_new=True, baseline=112.0)
        t.bbox = (50, 100, 180, 120)
        t.page_number = 0
        t.is_strikethrough = True

        success, err = pdf_handler.apply_object_edit(doc, t)
        self.assertTrue(success, f"Failed to bake: {err}")

        drawings = page.get_drawings()
        expected_y = 112.0 - (15.0 * 0.3)
        found = any(abs(d['rect'].y0 - expected_y) < 2.5 for d in drawings if 'rect' in d)
        self.assertTrue(found, f"Strikethrough drawing line not found near y={expected_y}")
        doc.close()

    def test_strikethrough_detection_and_drawing_isolation(self):
        """extract_editable_text must detect strikethrough and shapes/strokes must ignore it."""
        import fitz
        from word_sys_pdf_editor import pdf_handler

        doc, _ = pdf_handler.create_new_pdf(width=400, height=400, num_pages=1)
        page = doc.load_page(0)
        baseline = 150.0
        font_sz = 16.0
        page.insert_text(fitz.Point(50, baseline), "Strikethrough Item", fontsize=font_sz)
        strike_y = baseline - (font_sz * 0.3)
        page.draw_line(fitz.Point(50, strike_y), fitz.Point(180, strike_y), color=(0, 0, 0), width=0.8)

        texts, _ = pdf_handler.extract_editable_text(doc, 0)
        self.assertGreater(len(texts), 0)
        self.assertTrue(any(t.is_strikethrough for t in texts))

        shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)
        strokes, _ = pdf_handler.extract_editable_strokes(doc, 0)
        self.assertEqual(len(shapes), 0)
        self.assertEqual(len(strokes), 0)
        doc.close()

    def test_toggle_strikethrough_action_and_undo(self):
        """Window._toggle_text_strikethrough must create EditObjectCommand with working undo/redo."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.models import EditableText
        from word_sys_pdf_editor import undo_manager, pdf_handler

        class MockWin:
            def __init__(self):
                self.doc, _ = pdf_handler.create_new_pdf(width=400, height=400, num_pages=1)
                self.editable_texts = []
                self.editable_shapes = []
                self.editable_images = []
                self.editable_strokes = []
                self.selected_text = None
                self.document_modified = False
                self.status_label = MagicMock()
                self.undo_manager = undo_manager.UndoManager(self)
                self.pdf_view = self
            def _update_undo_redo_buttons(self): pass
            def queue_draw(self): pass
            def close(self):
                if self.doc: self.doc.close()

        win = MockWin()
        try:
            t = EditableText(60, 60, "Toggle Strikethrough", font_size=12.0, is_new=True)
            t.bbox = (60, 60, 160, 80)
            t.page_number = 0
            t.is_strikethrough = False
            win.editable_texts.append(t)

            PdfEditorWindow._toggle_text_strikethrough(win, t)
            self.assertTrue(t.is_strikethrough)
            self.assertEqual(len(win.undo_manager.undo_stack), 1)

            win.undo_manager.undo()
            self.assertFalse(t.is_strikethrough)

            win.undo_manager.redo()
            self.assertTrue(t.is_strikethrough)
        finally:
            win.close()

    def test_strikethrough_localization(self):
        """All 7 supported locales must have strikethrough_tip."""
        from word_sys_pdf_editor import i18n, locales
        self.assertEqual(i18n._STRINGS["en"]["strikethrough_tip"], "Strikethrough")
        self.assertEqual(i18n._STRINGS["tr"]["strikethrough_tip"], "Üstü Çizili")
        self.assertEqual(locales.STRINGS_FR["strikethrough_tip"], "Barré")
        self.assertEqual(locales.STRINGS_DE["strikethrough_tip"], "Durchgestrichen")
        self.assertEqual(locales.STRINGS_ES["strikethrough_tip"], "Tachado")
        self.assertEqual(locales.STRINGS_IT["strikethrough_tip"], "Barrato")
        self.assertEqual(locales.STRINGS_RU["strikethrough_tip"], "Зачёркнутый")



class TestTextAlignment(unittest.TestCase):
    """Atomic unit tests for 4-Way Text Alignment."""

    def test_editable_text_alignment_default_and_mutation(self):
        """EditableText must default to alignment='left' and allow mutation."""
        from word_sys_pdf_editor.models import EditableText
        import copy
        t = EditableText(10, 20, "Align Test")
        self.assertEqual(t.alignment, "left")
        t.alignment = "center"
        self.assertEqual(t.alignment, "center")
        c = copy.deepcopy(t)
        self.assertEqual(c.alignment, "center")

    def test_pdf_backend_aligned_text_baking(self):
        """PyMuPDF backend must position center and right aligned text correctly."""
        from word_sys_pdf_editor import pdf_handler
        from word_sys_pdf_editor.models import EditableText

        doc, _ = pdf_handler.create_new_pdf(width=400, height=400, num_pages=1)
        t = EditableText(50, 100, "Centered", font_size=14.0, is_new=True, baseline=114.0, alignment="center")
        t.bbox = (50, 100, 350, 130)
        t.page_number = 0
        t.is_underline = True

        success, err = pdf_handler.apply_object_edit(doc, t)
        self.assertTrue(success, f"Failed to bake: {err}")
        page = doc.load_page(0)
        drawings = page.get_drawings()
        self.assertGreater(len(drawings), 0)
        # Centered line should start well past left margin (50)
        self.assertGreater(drawings[0]['rect'].x0, 80.0)
        doc.close()

    def test_alignment_undo_redo(self):
        """Alignment change must be recorded and undoable via EditObjectCommand."""
        from word_sys_pdf_editor import undo_manager, pdf_handler
        from word_sys_pdf_editor.models import EditableText

        class MockWin:
            def __init__(self):
                self.doc, _ = pdf_handler.create_new_pdf(width=400, height=400, num_pages=1)
                self.editable_texts = []
                self.editable_shapes = []
                self.editable_images = []
                self.editable_strokes = []
                self.selected_text = None
                self.document_modified = False
                self.status_label = MagicMock()
                self.undo_manager = undo_manager.UndoManager(self)
                self.pdf_view = self
            def _update_undo_redo_buttons(self): pass
            def queue_draw(self): pass
            def close(self):
                if self.doc: self.doc.close()

        win = MockWin()
        try:
            t = EditableText(50, 50, "Align Command", font_size=12.0, is_new=True, alignment="left")
            t.bbox = (50, 50, 250, 70)
            t.page_number = 0
            win.editable_texts.append(t)

            old_prop = {'alignment': 'left', 'bbox': t.bbox}
            new_prop = {'alignment': 'right', 'bbox': t.bbox}
            cmd = undo_manager.EditObjectCommand(win, t, old_prop, new_prop)
            cmd.execute()
            win.undo_manager.add_command(cmd)

            self.assertEqual(t.alignment, "right")
            win.undo_manager.undo()
            self.assertEqual(t.alignment, "left")
            win.undo_manager.redo()
            self.assertEqual(t.alignment, "right")
        finally:
            win.close()

    def test_alignment_localization(self):
        """All 7 supported locales must have all 4 alignment tooltips."""
        from word_sys_pdf_editor import i18n, locales
        keys = ["align_left_tip", "align_center_tip", "align_right_tip", "align_justify_tip"]
        for k in keys:
            self.assertIn(k, i18n._STRINGS["en"])
            self.assertIn(k, i18n._STRINGS["tr"])
            self.assertIn(k, locales.STRINGS_FR)
            self.assertIn(k, locales.STRINGS_DE)
            self.assertIn(k, locales.STRINGS_ES)
            self.assertIn(k, locales.STRINGS_IT)
            self.assertIn(k, locales.STRINGS_RU)


if __name__ == "__main__":
    unittest.main()







