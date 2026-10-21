import io
from unittest.mock import MagicMock

import fitz
from PIL import Image

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableShape, EditableText, PatchObject
from word_sys_pdf_editor.undo_manager import AddObjectCommand, EditObjectCommand, ReorderObjectCommand


def _png(color, size=(60, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_doc():
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(0, 0, 400, 400), stream=_png((255, 0, 0), (200, 200)))
    return doc


class _Win:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self.measurements = []
        self.sticky_notes = []
        self._active_session = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()

    def _update_undo_redo_buttons(self):
        pass

    def _refresh_thumbnail(self, page):
        pass

    def _update_ui_state(self):
        pass


def _pixel(doc, x, y):
    pix = doc[0].get_pixmap(dpi=72)
    return pix.pixel(x, y)


def test_moving_patch_keeps_background_image():
    doc = _make_doc()
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    win = _Win(doc)
    patch = PatchObject(bbox=(100, 100, 160, 140), page_number=0,
                        image_bytes=_png((0, 0, 255)), is_new=True)
    AddObjectCommand(win, patch).execute()
    EditObjectCommand(win, patch, {"bbox": (100, 100, 160, 140), "rotation": 0.0},
                      {"bbox": (250, 250, 310, 290), "rotation": 0.0}).execute()
    # background must still be red away from the patch; patch blue at new place
    assert _pixel(doc, 10, 10)[:3] == (255, 0, 0)
    assert _pixel(doc, 280, 270)[:3] == (0, 0, 255)
    assert _pixel(doc, 130, 120)[:3] == (255, 0, 0)


def test_restore_rebinds_renamed_xobject():
    doc = _make_doc()
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    page = doc[0]
    page.add_redact_annot(fitz.Rect(300, 300, 350, 350))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)
    pdf_handler.restore_page_from_snapshot(doc, 0)
    page = doc[0]
    page.insert_image(fitz.Rect(100, 100, 160, 140), stream=_png((0, 0, 255)))
    assert _pixel(doc, 10, 10)[:3] == (255, 0, 0)


def test_cross_type_reorder_changes_bake_order():
    doc = _make_doc()
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    win = _Win(doc)
    # Two overlapping images (patches) stand in for any two layered objects
    low = PatchObject(bbox=(100, 100, 200, 200), page_number=0,
                      image_bytes=_png((0, 255, 0), (50, 50)), is_new=True)
    high = PatchObject(bbox=(150, 150, 250, 250), page_number=0,
                       image_bytes=_png((0, 0, 255), (50, 50)), is_new=True)
    win.editable_images = [low, high]
    pdf_handler.rebuild_page(doc, 0, [], [], win.editable_images)
    assert _pixel(doc, 175, 175)[:3] == (0, 0, 255)

    order = pdf_handler.sort_by_layer([low, high])
    changes = [(o, None, i) for i, o in enumerate([high, low])]
    cmd = ReorderObjectCommand(win, low, 0, 1, z_changes=changes)
    cmd.execute()
    assert _pixel(doc, 175, 175)[:3] == (0, 255, 0)
    assert order == [low, high]
    cmd.undo()
    assert _pixel(doc, 175, 175)[:3] == (0, 0, 255)


def test_sort_by_layer_defaults_and_explicit():
    text = EditableText(10, 10, "hi")
    text.page_number = 0
    patch = PatchObject(bbox=(0, 0, 10, 10), page_number=0, image_bytes=b"x")
    assert pdf_handler.sort_by_layer([text, patch]) == [patch, text]
    text.z_index = 0
    patch.z_index = 1
    assert pdf_handler.sort_by_layer([patch, text]) == [text, patch]


def test_original_text_can_be_brought_above_new_shape():
    from word_sys_pdf_editor.models import EditableShape
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 100), "HELLO", fontsize=40, color=(0, 0, 0))
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    texts, _ = pdf_handler.extract_editable_text(doc, 0)
    if not texts:
        import pytest
        pytest.skip("text extraction helper unavailable")
    win = _Win(doc)
    win.editable_texts = list(texts)
    cover = PatchObject(bbox=(0, 0, 300, 300), page_number=0,
                        image_bytes=_png((255, 0, 0), (10, 10)), is_new=True)
    win.editable_images = [cover]
    AddObjectCommand(win, cover).execute()
    assert _pixel(doc, 70, 90)[:3] == (255, 0, 0)
    txt = win.editable_texts[0]
    ordered = pdf_handler.sort_by_layer([cover, txt])
    changes = [(cover, None, 0), (txt, None, 1)]
    ReorderObjectCommand(win, txt, 0, 1, z_changes=changes).execute()
    dark = [_pixel(doc, x, y)[:3] for x in range(50, 140, 2) for y in range(70, 100, 2)]
    assert any(p != (255, 0, 0) for p in dark)
