from pathlib import Path

import pytest

from word_sys_pdf_editor import utils


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, (0.0, 0.0, 0.0)),
        (0xFF8000, (1.0, 128 / 255, 0.0)),
        (128.0, (128 / 255,) * 3),
        ((255, 64, 0), (1.0, 64 / 255, 0.0)),
        ((-1, 0.5, 999), (0.0, 0.5, 1.0)),
        ("not-a-colour", (0.0, 0.0, 0.0)),
    ],
)
def test_normalize_color(value, expected):
    assert utils.normalize_color(value) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("filename", "family", "style"),
    [
        ("LiberationSans-Regular.ttf", "Liberation Sans", "Regular"),
        ("Noto_Serif-BoldItalic.otf", "Noto Serif", "BoldItalic"),
        ("FiraCode-Bold.ttf", "Fira Code", "Bold"),
        ("ExampleOblique.ttf", "Example", "Italic"),
    ],
)
def test_parse_font_name(filename, family, style):
    assert utils.parse_font_name(Path(filename)) == (family, style)
