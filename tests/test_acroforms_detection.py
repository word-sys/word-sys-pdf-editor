import pytest
import fitz
import cairo
from word_sys_pdf_editor.models import AcroFormField, DocumentSession
from word_sys_pdf_editor import pdf_handler


def test_acroform_field_model_instantiation_and_properties():
    field = AcroFormField(
        field_id="field_1",
        xref=10,
        page_number=0,
        rect=(50.0, 100.0, 200.0, 130.0),
        field_name="user_email",
        field_label="Email Address",
        field_type="text",
        field_type_id=fitz.PDF_WIDGET_TYPE_TEXT,
        value="user@example.com",
        is_required=True,
        is_read_only=False,
        is_multiline=False,
    )
    assert field.x == 50.0
    assert field.y == 100.0
    assert field.width == 150.0
    assert field.height == 30.0
    assert field.bbox == (50.0, 100.0, 200.0, 130.0)
    assert field.is_required is True
    assert field.is_read_only is False
    assert field.is_checked is False

    field.set_value("new@example.com")
    assert field.value == "new@example.com"
    assert field.is_modified is True

    d = field.to_dict()
    assert d["field_name"] == "user_email"
    assert d["value"] == "new@example.com"
    assert d["xref"] == 10
    assert d["is_modified"] is True


def test_acroform_field_is_checked_logic():
    chk_true = AcroFormField(
        field_id="c1",
        xref=1,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c1",
        field_type="checkbox",
        value="Yes",
    )
    assert chk_true.is_checked is True

    chk_bool = AcroFormField(
        field_id="c2",
        xref=2,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c2",
        field_type="checkbox",
        value=True,
    )
    assert chk_bool.is_checked is True

    chk_false = AcroFormField(
        field_id="c3",
        xref=3,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c3",
        field_type="checkbox",
        value="Off",
    )
    assert chk_false.is_checked is False

    chk_none = AcroFormField(
        field_id="c4",
        xref=4,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c4",
        field_type="checkbox",
        value="None",
    )
    assert chk_none.is_checked is False


def test_document_session_form_fields():
    session = DocumentSession()
    assert session.form_fields == []
    assert session.acroform_fields == []
    assert session.selected_form_field is None

    field = AcroFormField(
        field_id="f1",
        xref=5,
        page_number=0,
        rect=(10, 10, 50, 30),
        field_name="test",
    )
    session.form_fields.append(field)
    assert len(session.form_fields) == 1
    assert session.acroform_fields[0].field_name == "test"

    session.selected_form_field = field
    assert session.selected_form_field == field

    session.close()
    assert session.form_fields == []
    assert session.selected_form_field is None


def test_has_acroforms_detection():
    doc_empty = fitz.open()
    doc_empty.new_page()
    assert pdf_handler.has_acroforms(doc_empty) is False

    doc_form = fitz.open()
    page = doc_form.new_page()
    w = fitz.Widget()
    w.rect = fitz.Rect(50, 50, 150, 80)
    w.field_name = "sample_field"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    page.add_widget(w)
    assert pdf_handler.has_acroforms(doc_form) is True


def test_extract_acroform_fields_all_types():
    doc = fitz.open()
    page = doc.new_page()

    # 1. Text field with label and required flag
    w_text = fitz.Widget()
    w_text.rect = fitz.Rect(20, 20, 180, 50)
    w_text.field_name = "first_name"
    w_text.field_label = "First Name"
    w_text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_text.field_value = "John"
    w_text.field_flags = fitz.PDF_FIELD_IS_REQUIRED
    w_text.text_fontsize = 12.0
    w_text.text_color = (0.1, 0.1, 0.1)
    page.add_widget(w_text)

    # 2. Multiline text field
    w_multi = fitz.Widget()
    w_multi.rect = fitz.Rect(20, 60, 180, 120)
    w_multi.field_name = "notes"
    w_multi.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_multi.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
    w_multi.field_value = "Line 1\nLine 2"
    page.add_widget(w_multi)

    # 3. Password field
    w_pwd = fitz.Widget()
    w_pwd.rect = fitz.Rect(20, 130, 180, 160)
    w_pwd.field_name = "pwd"
    w_pwd.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_pwd.field_flags = fitz.PDF_TX_FIELD_IS_PASSWORD
    w_pwd.field_value = "secret123"
    page.add_widget(w_pwd)

    # 4. Checkbox
    w_chk = fitz.Widget()
    w_chk.rect = fitz.Rect(20, 170, 40, 190)
    w_chk.field_name = "terms"
    w_chk.field_label = "Accept Terms"
    w_chk.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    w_chk.field_value = "Yes"
    page.add_widget(w_chk)

    # 5. ComboBox
    w_combo = fitz.Widget()
    w_combo.rect = fitz.Rect(20, 200, 180, 230)
    w_combo.field_name = "country"
    w_combo.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    w_combo.choice_values = ["France", "Germany", "Turkey"]
    w_combo.field_value = "Turkey"
    page.add_widget(w_combo)

    # 6. ListBox
    w_list = fitz.Widget()
    w_list.rect = fitz.Rect(20, 240, 180, 290)
    w_list.field_name = "priority"
    w_list.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
    w_list.choice_values = ["Low", "Medium", "High"]
    w_list.field_value = "High"
    page.add_widget(w_list)

    # 7. Button with Radio flag
    w_radio = fitz.Widget()
    w_radio.rect = fitz.Rect(20, 300, 40, 320)
    w_radio.field_name = "radio_option"
    w_radio.field_type = fitz.PDF_WIDGET_TYPE_BUTTON
    w_radio.field_flags = fitz.PDF_BTN_FIELD_IS_RADIO
    page.add_widget(w_radio)

    # 8. Read-only text field
    w_ro = fitz.Widget()
    w_ro.rect = fitz.Rect(20, 330, 180, 360)
    w_ro.field_name = "readonly_field"
    w_ro.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_ro.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
    w_ro.field_value = "Locked"
    page.add_widget(w_ro)

    fields, err = pdf_handler.extract_acroform_fields(doc)
    assert err is None
    assert len(fields) == 8

    by_name = {f.field_name: f for f in fields}

    # Verify first_name
    fn = by_name["first_name"]
    assert fn.field_type == "text"
    assert fn.value == "John"
    assert fn.field_label == "First Name"
    assert fn.is_required is True
    assert fn.is_read_only is False

    # Verify multiline notes
    notes = by_name["notes"]
    assert notes.field_type == "text"
    assert notes.is_multiline is True
    assert "Line 1" in notes.value

    # Verify password
    pwd = by_name["pwd"]
    assert pwd.field_type == "text"
    assert pwd.is_password is True

    # Verify checkbox
    terms = by_name["terms"]
    assert terms.field_type == "checkbox"
    assert terms.is_checked is True
    assert terms.value == "Yes"

    # Verify combobox
    combo = by_name["country"]
    assert combo.field_type == "combobox"
    assert combo.choice_values == ["France", "Germany", "Turkey"]
    assert combo.value == "Turkey"

    # Verify listbox
    lst = by_name["priority"]
    assert lst.field_type == "listbox"
    assert lst.choice_values == ["Low", "Medium", "High"]
    assert lst.value == "High"

    # Verify radio
    rad = by_name["radio_option"]
    assert rad.field_type == "radio"

    # Verify readonly
    ro = by_name["readonly_field"]
    assert ro.is_read_only is True
    assert ro.value == "Locked"


def test_extract_acroform_fields_multi_page_and_indexing():
    doc = fitz.open()
    p0 = doc.new_page()

    w0a = fitz.Widget()
    w0a.rect = fitz.Rect(10, 10, 50, 30)
    w0a.field_name = "p0_a"
    w0a.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    p0.add_widget(w0a)

    w0b = fitz.Widget()
    w0b.rect = fitz.Rect(10, 40, 50, 60)
    w0b.field_name = "p0_b"
    w0b.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    p0.add_widget(w0b)

    p1 = doc.new_page()

    w1a = fitz.Widget()
    w1a.rect = fitz.Rect(10, 10, 50, 30)
    w1a.field_name = "p1_a"
    w1a.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    p1.add_widget(w1a)

    # Scoped to page 0
    fields_p0, err0 = pdf_handler.extract_acroform_fields(doc, page_index=0)
    assert err0 is None
    assert len(fields_p0) == 2
    assert {f.field_name for f in fields_p0} == {"p0_a", "p0_b"}
    assert all(f.page_number == 0 for f in fields_p0)

    # Scoped to page 1
    fields_p1, err1 = pdf_handler.extract_acroform_fields(doc, page_index=1)
    assert err1 is None
    assert len(fields_p1) == 1
    assert fields_p1[0].field_name == "p1_a"
    assert fields_p1[0].page_number == 1

    # Entire document
    fields_all, err_all = pdf_handler.extract_acroform_fields(doc, page_index=None)
    assert err_all is None
    assert len(fields_all) == 3

    # Invalid page index
    fields_bad, err_bad = pdf_handler.extract_acroform_fields(doc, page_index=99)
    assert len(fields_bad) == 0
    assert err_bad is not None


def test_update_acroform_field_value_and_get():
    doc = fitz.open()
    page = doc.new_page()

    w = fitz.Widget()
    w.rect = fitz.Rect(50, 50, 200, 80)
    w.field_name = "city_name"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_value = "London"
    page.add_widget(w)

    field = pdf_handler.get_acroform_field(doc, page_index=0, field_identifier="city_name")
    assert field is not None
    assert field.value == "London"

    # Update by name
    res = pdf_handler.update_acroform_field_value(doc, 0, "city_name", "Tokyo")
    assert res is True

    updated_field = pdf_handler.get_acroform_field(doc, page_index=0, field_identifier="city_name")
    assert updated_field is not None
    assert updated_field.value == "Tokyo"

    # Update by xref
    res_xref = pdf_handler.update_acroform_field_value(doc, 0, field.xref, "Kyoto")
    assert res_xref is True

    updated_by_xref = pdf_handler.get_acroform_field(doc, page_index=0, field_identifier=field.xref)
    assert updated_by_xref is not None
    assert updated_by_xref.value == "Kyoto"

    # Non-existent
    assert pdf_handler.update_acroform_field_value(doc, 0, "missing_field", "val") is False
    assert pdf_handler.get_acroform_field(doc, 0, "missing_field") is None


def test_export_and_import_form_data():
    doc = fitz.open()
    page = doc.new_page()

    w1 = fitz.Widget()
    w1.rect = fitz.Rect(10, 10, 100, 30)
    w1.field_name = "f1"
    w1.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w1.field_value = "Val1"
    page.add_widget(w1)

    w2 = fitz.Widget()
    w2.rect = fitz.Rect(10, 40, 100, 60)
    w2.field_name = "f2"
    w2.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w2.field_value = "Val2"
    page.add_widget(w2)

    data = pdf_handler.export_form_data(doc)
    assert data == {"f1": "Val1", "f2": "Val2"}

    # Import modifications
    count = pdf_handler.import_form_data(doc, {"f1": "Updated1", "f2": "Updated2", "f3": "Ignored"})
    assert count == 2

    new_data = pdf_handler.export_form_data(doc)
    assert new_data == {"f1": "Updated1", "f2": "Updated2"}


def test_draw_acroform_overlay():
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 400)
    cr = cairo.Context(surf)

    field1 = AcroFormField(
        field_id="f1",
        xref=1,
        page_number=0,
        rect=(20, 20, 120, 50),
        field_name="f1",
        field_type="text",
        is_required=True,
    )
    field2 = AcroFormField(
        field_id="f2",
        xref=2,
        page_number=0,
        rect=(20, 60, 120, 90),
        field_name="f2",
        field_type="checkbox",
    )
    field3 = AcroFormField(
        field_id="f3",
        xref=3,
        page_number=0,
        rect=(20, 100, 120, 130),
        field_name="f3",
        field_type="text",
        is_read_only=True,
    )

    # Test drawing overlay for regular fields
    pdf_handler.draw_acroform_overlay(cr, [field1, field2, field3], zoom_level=1.0)

    # Test drawing overlay with active field focused
    pdf_handler.draw_acroform_overlay(cr, [field1, field2, field3], zoom_level=1.2, active_field=field1)

    # Test with empty fields
    pdf_handler.draw_acroform_overlay(cr, [], zoom_level=1.0)


def test_window_session_delegation_and_hit_testing():
    from word_sys_pdf_editor.window import PdfEditorWindow

    # Test that PdfEditorWindow creates form_fields accessors
    session = DocumentSession()
    field = AcroFormField(
        field_id="f1",
        xref=1,
        page_number=0,
        rect=(50.0, 50.0, 150.0, 80.0),
        field_name="box",
        field_type="text",
    )
    session.form_fields = [field]

    # Verify hit testing logic via a minimal duck-typed mock of window
    class MockWindow:
        def __init__(self, s):
            self._active_session = s
            self.current_page_index = 0

        @property
        def form_fields(self):
            return self._active_session.form_fields if self._active_session else []

        def _visual_to_unrotated_page_coords(self, x, y):
            return x, y

        _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos

    win = MockWindow(session)
    assert len(win.form_fields) == 1

    # Inside bounding box
    hit = win._find_form_field_at_pos(100.0, 65.0)
    assert hit is not None
    assert hit.field_name == "box"

    # Outside bounding box
    miss = win._find_form_field_at_pos(200.0, 200.0)
    assert miss is None
