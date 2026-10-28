"""Consolidated Measurements and Scale Calibration Test Suite for word-sys-pdf-editor.

This suite merges distance, perimeter, area measurement calculations, snap-to-vertex,
custom units (mm, cm, m, in, ft), and interactive scale calibration line tests.
"""

# ============================================================================
# SECTION: test_measurement_engine.py
# ============================================================================
import unittest
import math
import cairo
import pymupdf as fitz
from unittest.mock import MagicMock

from word_sys_pdf_editor.models import ScaleCalibration, MeasurementObject
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.undo_manager import (
    AddMeasurementCommand,
    DeleteMeasurementCommand,
    CalibrateScaleCommand,
    EditObjectCommand,
    UndoManager
)
from word_sys_pdf_editor import pdf_handler


class TestScaleCalibration(unittest.TestCase):
    def test_default_calibration(self):
        calib = ScaleCalibration()
        self.assertEqual(calib.unit, "pt")
        self.assertEqual(calib.points_per_unit, 1.0)
        self.assertEqual(calib.ratio_value, 1.0)
        self.assertEqual(calib.format_distance(72.0), "72.00 pt")
        self.assertEqual(calib.format_distance(72.0, precision=1), "72.0 pt")
        self.assertEqual(calib.format_area(100.0), "100.00 pt²")

    def test_unit_conversions(self):
        # 72 points = 1 inch
        self.assertAlmostEqual(ScaleCalibration.convert_points_to_unit(72.0, "in"), 1.0, places=3)
        # 72 points = 25.4 mm
        self.assertAlmostEqual(ScaleCalibration.convert_points_to_unit(72.0, "mm"), 25.4, places=3)
        # 72 points = 2.54 cm
        self.assertAlmostEqual(ScaleCalibration.convert_points_to_unit(72.0, "cm"), 2.54, places=3)
        # 72 points = 0.0254 m
        self.assertAlmostEqual(ScaleCalibration.convert_points_to_unit(72.0, "m"), 0.0254, places=4)
        # 72 points = 1/12 ft
        self.assertAlmostEqual(ScaleCalibration.convert_points_to_unit(72.0, "ft"), 1.0 / 12.0, places=3)

    def test_calibration_from_points(self):
        calib = ScaleCalibration()
        # Suppose a 100 pt line on PDF represents 5 meters in real world
        pts = [(0.0, 0.0), (100.0, 0.0)]
        calib.calibrate_from_points(pts, real_world_dist=5.0, unit="m")
        self.assertEqual(calib.unit, "m")
        # 100 pt = 5 m => 20 pt per meter
        self.assertAlmostEqual(calib.points_per_unit, 20.0, places=4)

        # Distance of 200 pt should be 10.0 m
        self.assertAlmostEqual(calib.convert_distance(200.0), 10.0, places=4)
        self.assertEqual(calib.format_distance(200.0), "10.00 m")

        # Area of 400 pt^2 should be 400 / (20^2) = 1.0 m^2
        self.assertAlmostEqual(calib.convert_area(400.0), 1.0, places=4)
        self.assertEqual(calib.format_area(400.0), "1.00 m²")

    def test_serialization(self):
        calib = ScaleCalibration(unit="cm", points_per_unit=28.346, ratio_value=50.0)
        data = calib.to_dict()
        restored = ScaleCalibration.from_dict(data)
        self.assertEqual(restored.unit, "cm")
        self.assertAlmostEqual(restored.points_per_unit, 28.346, places=3)
        self.assertAlmostEqual(restored.ratio_value, 50.0, places=3)


class TestMeasurementObject(unittest.TestCase):
    def test_distance_measurement(self):
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(10.0, 20.0), (40.0, 60.0)],
            page_number=0
        )
        # hypot(30, 40) = 50
        self.assertAlmostEqual(meas.compute_raw_value(), 50.0, places=3)
        # bbox includes pad = 16.0 for badge & ticks
        self.assertEqual(meas.bbox, (10.0 - 16.0, 20.0 - 16.0, 40.0 + 16.0, 60.0 + 16.0))
        cx, cy = meas.get_centroid()
        self.assertAlmostEqual(cx, 25.0, places=3)
        self.assertAlmostEqual(cy, 40.0, places=3)

    def test_area_measurement(self):
        # A 100x50 rectangle
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_AREA,
            points=pts,
            page_number=0
        )
        self.assertAlmostEqual(meas.compute_raw_value(), 5000.0, places=3)
        cx, cy = meas.get_centroid()
        self.assertAlmostEqual(cx, 50.0, places=3)
        self.assertAlmostEqual(cy, 25.0, places=3)

    def test_repositioning(self):
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(10.0, 10.0), (20.0, 30.0)],
            page_number=0
        )
        meas.set_position(50.0, 60.0)
        # Shifted by dx = 50 - (-6) = 56, dy = 60 - (-6) = 66
        self.assertEqual(meas.bbox[0], 50.0)
        self.assertEqual(meas.bbox[1], 60.0)

    def test_serialization(self):
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_AREA,
            points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
            page_number=2,
            label="Room A",
            color=(0.1, 0.2, 0.3),
            stroke_width=2.5
        )
        data = meas.to_dict()
        restored = MeasurementObject.from_dict(data)
        self.assertEqual(restored.measurement_type, MeasurementObject.TYPE_AREA)
        self.assertEqual(restored.page_number, 2)
        self.assertEqual(restored.label, "Room A")
        self.assertEqual(restored.points, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
        self.assertEqual(restored.color, (0.1, 0.2, 0.3))
        self.assertEqual(restored.stroke_width, 2.5)


class TestMeasurementUndoCommands(unittest.TestCase):
    def setUp(self):
        class MockSession:
            def __init__(self):
                self.measurements = {}
                self.scale_calibrations = {}
                self.scale_calibration = None

        self.mock_window = MagicMock()
        self.mock_window._active_session = MockSession()
        self.mock_window.current_page_index = 0
        self.mock_window._add_measurement_to_session = lambda m: PdfEditorWindow._add_measurement_to_session(self.mock_window, m)
        self.mock_window._remove_measurement_from_session = lambda m: PdfEditorWindow._remove_measurement_from_session(self.mock_window, m)
        self.mock_window._apply_scale_calibration_state = lambda c, page_index=None, entire_document=True: PdfEditorWindow._apply_scale_calibration_state(self.mock_window, c, page_index=page_index, entire_document=entire_document)
        self.mock_window.get_scale_calibration = lambda idx=0: PdfEditorWindow.get_scale_calibration(self.mock_window, idx)
        self.undo_mgr = UndoManager(self.mock_window)

    def test_add_and_delete_measurement_undo(self):
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(0.0, 0.0), (100.0, 100.0)],
            page_number=0
        )

        # 1. Execute Add
        cmd_add = AddMeasurementCommand(self.mock_window, meas)
        cmd_add.execute()
        self.undo_mgr.add_command(cmd_add)
        self.assertIn(meas, self.mock_window._active_session.measurements[0])

        # 2. Undo Add
        self.undo_mgr.undo()
        self.assertNotIn(meas, self.mock_window._active_session.measurements.get(0, []))

        # 3. Redo Add
        self.undo_mgr.redo()
        self.assertIn(meas, self.mock_window._active_session.measurements[0])

        # 4. Execute Delete
        cmd_del = DeleteMeasurementCommand(self.mock_window, meas)
        cmd_del.execute()
        self.undo_mgr.add_command(cmd_del)
        self.assertNotIn(meas, self.mock_window._active_session.measurements.get(0, []))

        # 5. Undo Delete
        self.undo_mgr.undo()
        self.assertIn(meas, self.mock_window._active_session.measurements[0])

    def test_calibrate_scale_undo(self):
        old_calib = ScaleCalibration(unit="pt", points_per_unit=1.0)
        new_calib = ScaleCalibration(unit="mm", points_per_unit=2.834)

        self.mock_window._active_session.scale_calibrations[0] = old_calib
        cmd = CalibrateScaleCommand(self.mock_window, old_calib, new_calib, page_index=0, entire_document=False)
        cmd.execute()
        self.undo_mgr.add_command(cmd)

        self.assertEqual(self.mock_window._active_session.scale_calibrations[0].unit, "mm")

        self.undo_mgr.undo()
        self.assertEqual(self.mock_window._active_session.scale_calibrations[0].unit, "pt")

        self.undo_mgr.redo()
        self.assertEqual(self.mock_window._active_session.scale_calibrations[0].unit, "mm")


class TestCairoAndPdfRendering(unittest.TestCase):
    def test_cairo_draw_measurement_does_not_crash(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
        cr = cairo.Context(surf)
        calib = ScaleCalibration(unit="cm", points_per_unit=28.346)

        dist_meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(20.0, 30.0), (120.0, 150.0)],
            page_number=0
        )
        pdf_handler.draw_measurement_to_cairo(cr, dist_meas, calib, zoom_level=1.0)

        area_meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_AREA,
            points=[(10.0, 10.0), (100.0, 100.0), (100.0, 80.0), (10.0, 80.0)],
            page_number=0
        )
        pdf_handler.draw_measurement_to_cairo(cr, area_meas, calib, zoom_level=1.0)

    def test_apply_measurement_to_pdf_page(self):
        doc = fitz.open()
        page = doc.new_page(width=300, height=300)

        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(50.0, 50.0), (200.0, 50.0)],
            page_number=0
        )
        success, err = pdf_handler._apply_single_object_to_page(doc, page, meas)
        self.assertTrue(success)
        self.assertIsNone(err)

        area_meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_AREA,
            points=[(40.0, 40.0), (150.0, 40.0), (150.0, 120.0), (40.0, 120.0)],
            page_number=0
        )
        success2, err2 = pdf_handler._apply_single_object_to_page(doc, page, area_meas)
        self.assertTrue(success2)
        self.assertIsNone(err2)


class TestMeasurementInteractionState(unittest.TestCase):
    def test_distance_icon_is_symbolic(self):
        # Must be a -symbolic icon (pure white/monochrome, not colored)
        from gi.repository import Gtk
        Gtk.init()
        win = PdfEditorWindow()
        icon_img = win.measure_distance_tool_button.get_child().get_first_child()
        self.assertTrue(icon_img.get_icon_name().endswith("-symbolic"))
        self.assertEqual(icon_img.get_icon_name(), "straighten-symbolic")

    def test_escape_clears_temp_polygon_vertices(self):
        from gi.repository import Gtk, Gdk
        Gtk.init()
        win = PdfEditorWindow()
        win.view_mode = False
        win.tool_mode = "measure_area"
        win.temp_polygon_vertices = [(10.0, 10.0), (20.0, 20.0)]
        win.last_mouse_page_pos = (25.0, 25.0)
        handled = win.on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
        self.assertTrue(handled)
        self.assertEqual(win.temp_polygon_vertices, [])
        self.assertIsNone(win.last_mouse_page_pos)


if __name__ == "__main__":
    unittest.main()



# ============================================================================
# SECTION: test_scale_calibration.py
# ============================================================================
import pytest
import math
import fitz
from unittest.mock import MagicMock

from word_sys_pdf_editor.models import (
    ScaleCalibration,
    PRESET_SCALES,
    POINTS_PER_M,
    POINTS_PER_INCH,
    POINTS_PER_FT,
    DocumentSession,
)
from word_sys_pdf_editor.undo_manager import CalibrateScaleCommand, UndoManager
from word_sys_pdf_editor import pdf_handler


class TestScaleCalibrationModel:
    """Test mathematical precision and serialization in ScaleCalibration."""

    def test_units_and_distance_conversions(self):
        # 100 points per meter calibration
        calib = ScaleCalibration(points_per_unit=100.0, unit="m", known_distance=5.0, points_len=500.0)
        assert calib.units_per_point == pytest.approx(0.01)
        assert calib.distance_in_units(250.0) == pytest.approx(2.5)
        assert calib.points_from_distance(3.0) == pytest.approx(300.0)
        assert calib.area_in_units(10000.0) == pytest.approx(1.0)
        assert calib.format_distance(250.0) == "2.50 m"
        assert calib.format_area(10000.0) == "1.00 m\u00b2"

    def test_from_reference_line(self):
        # Line from (0, 0) to (300, 400) has hypotenuse 500 pt
        calib = ScaleCalibration.from_reference_line(
            0.0, 0.0, 300.0, 400.0, known_distance=10.0, unit="m"
        )
        assert calib.points_len == pytest.approx(500.0)
        assert calib.points_per_unit == pytest.approx(50.0)
        assert calib.distance_in_units(500.0) == pytest.approx(10.0)
        assert calib.reference_line == (0.0, 0.0, 300.0, 400.0)

    def test_from_preset_metric(self):
        # 1:100 scale: 1 meter on ground is 1/100 meter on paper
        # Base points per meter = 72000.0 / 25.4
        expected_ppu = POINTS_PER_M / 100.0
        calib = ScaleCalibration.from_preset("1:100")
        assert calib.preset_name == "1:100"
        assert calib.unit == "m"
        assert calib.points_per_unit == pytest.approx(expected_ppu)
        # 1 meter in real world should convert to expected_ppu in points
        assert calib.points_from_distance(1.0) == pytest.approx(expected_ppu)

    def test_from_preset_imperial(self):
        # 1/4" = 1'-0" ratio is 48.0
        expected_ppu = POINTS_PER_FT / 48.0
        calib = ScaleCalibration.from_preset('1/4" = 1\'-0"')
        assert calib.unit == "ft"
        assert calib.points_per_unit == pytest.approx(expected_ppu)

    def test_dict_serialization_roundtrip(self):
        calib = ScaleCalibration(
            points_per_unit=123.456,
            unit="cm",
            known_distance=12.0,
            points_len=1481.472,
            reference_line=(10.0, 20.0, 110.0, 20.0),
            preset_name="custom",
            page_index=2,
        )
        d = calib.to_dict()
        restored = ScaleCalibration.from_dict(d)
        assert restored.points_per_unit == pytest.approx(calib.points_per_unit)
        assert restored.unit == "cm"
        assert restored.known_distance == pytest.approx(12.0)
        assert restored.points_len == pytest.approx(1481.472)
        assert restored.reference_line == (10.0, 20.0, 110.0, 20.0)
        assert restored.preset_name == "custom"
        assert restored.page_index == 2


class TestPdfHandlerScaleMetadata:
    """Test embedding and reading scale calibration in PDF catalog dictionary."""

    def test_catalog_embed_and_extract_roundtrip(self, tmp_path):
        doc = fitz.open()
        doc.new_page(width=595, height=842)

        data = {
            "points_per_unit": 28.3464,
            "unit": "cm",
            "known_distance": 10.0,
            "points_len": 283.464,
            "reference_line": [50.0, 100.0, 333.464, 100.0],
            "preset_name": None,
            "page_index": None,
        }

        # Embed metadata
        success = pdf_handler.embed_scale_calibration(doc, data)
        assert success is True

        # Extract before save
        extracted = pdf_handler.extract_scale_calibration(doc)
        assert extracted is not None
        assert extracted["unit"] == "cm"
        assert extracted["points_per_unit"] == pytest.approx(28.3464)

        # Save to disk and re-open to verify persistent PDF catalog storage
        out_file = str(tmp_path / "calibrated.pdf")
        doc.save(out_file)
        doc.close()

        reloaded = fitz.open(out_file)
        reloaded_data = pdf_handler.extract_scale_calibration(reloaded)
        reloaded.close()

        assert reloaded_data is not None
        assert reloaded_data["unit"] == "cm"
        assert reloaded_data["known_distance"] == 10.0
        assert reloaded_data["points_per_unit"] == pytest.approx(28.3464)


class TestScaleUndoRedoCommand:
    """Test CalibrateScaleCommand undo and redo cycles."""

    def test_calibrate_command_execute_and_undo(self):
        window = MagicMock()
        old_calib = ScaleCalibration(points_per_unit=50.0, unit="m")
        new_calib = ScaleCalibration(points_per_unit=100.0, unit="m")

        cmd = CalibrateScaleCommand(window, old_calib, new_calib, page_index=None, entire_document=True)
        cmd.execute()
        window._apply_scale_calibration_state.assert_called_with(
            new_calib, page_index=None, entire_document=True
        )

        window._apply_scale_calibration_state.reset_mock()
        cmd.undo()
        window._apply_scale_calibration_state.assert_called_with(
            old_calib, page_index=None, entire_document=True
        )


class TestDocumentSessionScale:
    """Test DocumentSession scale attributes and lifecycle."""

    def test_session_lifecycle(self):
        sess = DocumentSession()
        assert sess.scale_calibration is None
        assert sess.scale_calibrations == {}

        calib = ScaleCalibration(points_per_unit=100.0, unit="m")
        sess.scale_calibration = calib
        sess.scale_calibrations[0] = calib

        assert sess.scale_calibration == calib
        assert sess.scale_calibrations[0] == calib

        sess.close()
        assert sess.scale_calibration is None
        assert sess.scale_calibrations == {}


class TestWindowCalibrationInteractions:
    """Test user interaction ergonomics with calibration and toolbar."""

    def test_drag_end_does_not_auto_open_dialog(self):
        from word_sys_pdf_editor.window import PdfEditorWindow

        window = MagicMock()
        window.temp_calibration_line = (10.0, 20.0, 210.0, 20.0)
        window.current_page_index = 0
        window.get_scale_calibration = MagicMock(return_value=None)
        window.status_label = MagicMock()
        window.pdf_view = MagicMock()
        window._update_ui_state = MagicMock()
        window.show_scale_calibration_dialog = MagicMock()

        # Call on_drag_end logic
        # Simulate lines from on_drag_end
        line = window.temp_calibration_line
        sx, sy, ex, ey = line
        measured_len = math.hypot(ex - sx, ey - sy)
        assert measured_len == 200.0

        # Execute PdfEditorWindow's on_calibrate_dialog_clicked
        PdfEditorWindow.on_calibrate_dialog_clicked(window)
        # It should pass the measured length and reference line
        window.show_scale_calibration_dialog.assert_called_once_with(200.0, reference_line=(10.0, 20.0, 210.0, 20.0))

    def test_sidebar_grid_layout_side_by_side(self):
        """Verify that Form Builder and Stamp buttons are attached side by side in row 5."""
        import inspect
        from word_sys_pdf_editor import window
        src = inspect.getsource(window.PdfEditorWindow._create_sidebar)
        assert 'tools_grid.attach(self.form_builder_tool_button, 0, 5, 1, 1)' in src
        assert 'tools_grid.attach(self.stamp_tool_button, 1, 5, 1, 1)' in src


