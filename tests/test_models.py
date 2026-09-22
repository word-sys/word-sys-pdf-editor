import pytest

from word_sys_pdf_editor.models import EditableShape, EditableStroke, EditableText


def test_editable_text_detects_style_link_and_font_alias():
    text = EditableText(
        10,
        20,
        "See https://example.com",
        span_data={"font": "ABCDEF+Arial-BoldItalic", "flags": 0, "bbox": (10, 20, 110, 32)},
    )

    assert text.font_family_base == "Liberation Sans"
    assert text.pdf_fontname_base14 == "helv"
    assert text.is_bold is True
    assert text.is_italic is True
    assert text.is_link is True


def test_editable_text_split_preserves_proportional_bounds():
    text = EditableText(0, 0, "abcdefghij", span_data={"bbox": (0, 0, 100, 20)})

    before, selected, after = text.split_at_range(2, 7)

    assert [part.text for part in (before, selected, after)] == ["ab", "cdefg", "hij"]
    assert before.bbox == pytest.approx((0, 0, 20, 20))
    assert selected.bbox == pytest.approx((20, 0, 70, 20))
    assert after.bbox == pytest.approx((70, 0, 100, 20))
    assert text.split_at_range(4, 4) == [text]


def test_editable_shape_geometry_and_vector_points():
    shape = EditableShape(EditableShape.SHAPE_CHECKMARK, (10, 20, 110, 70))

    assert shape.get_width() == 100
    assert shape.get_height() == 50
    assert shape.get_checkmark_points() == [(25, 45), (48, 62.5), (95, 29)]

    shape.set_size(40, 30)
    shape.set_position(5, 6)

    assert shape.bbox == (5, 6, 45, 36)


def test_editable_stroke_recalculates_scales_and_moves():
    stroke = EditableStroke(points=[(10, 10), (20, 30)], stroke_width=4)

    assert stroke.bbox == (8, 8, 22, 32)
    assert stroke.get_width() == 14
    assert stroke.get_height() == 24

    stroke.scale_to_bbox((0, 0, 28, 48), stroke.bbox, list(stroke.points))
    assert stroke.bbox == (0, 0, 28, 48)

    stroke.set_position(10, 20)
    assert stroke.x == pytest.approx(10)
    assert stroke.y == pytest.approx(20)
