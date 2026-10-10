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
