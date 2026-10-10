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

