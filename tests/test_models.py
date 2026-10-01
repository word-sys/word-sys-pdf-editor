import unittest
from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, EditableStroke,
    DocumentSession, FLAG_BOLD, FLAG_ITALIC
)


class TestModels(unittest.TestCase):
    def test_editable_text_creation_and_bounds(self):
        text = EditableText(
            100.0,
            150.0,
            "Hello World",
            font_size=16.0,
            color=(0.1, 0.2, 0.3)
        )
        self.assertEqual(text.text, "Hello World")
        self.assertEqual(text.x, 100.0)
        self.assertEqual(text.y, 150.0)
        self.assertFalse(text.is_bold)
        self.assertFalse(text.is_italic)

        text.is_bold = True
        self.assertTrue(text.is_bold)

    def test_editable_shape_properties(self):
        shape = EditableShape(
            shape_type="rectangle",
            bbox=(10.0, 20.0, 110.0, 120.0),
            stroke_color=(0, 0, 0),
            fill_color=(1, 1, 1),
            stroke_width=2.0
        )
        self.assertEqual(shape.shape_type, "rectangle")
        self.assertEqual(shape.stroke_width, 2.0)
        self.assertEqual(shape.bbox, (10.0, 20.0, 110.0, 120.0))

    def test_document_session_lifecycle(self):
        session = DocumentSession(session_id="test-session-1")
        self.assertEqual(session.session_id, "test-session-1")
        self.assertIsNone(session.doc)
        self.assertIsNone(session.pdf_path)
        self.assertFalse(session.is_modified)
        self.assertEqual(session.current_page_index, 0)
        self.assertEqual(session.display_title, "Untitled Document")

        session.is_modified = True
        self.assertTrue(session.is_modified)
        session.is_modified = False
        self.assertFalse(session.is_modified)


if __name__ == '__main__':
    unittest.main()
