import io
from unittest.mock import MagicMock, patch
import fitz
import pytest

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import RedactionMark
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.sanitize_dialog import SanitizeDialog


def test_redaction_cairo_cache_invalidation():
    """Verify that after applying redactions, the cached Cairo surface is invalidated

    and the newly fetched Cairo surface reflects the applied redactions immediately on UI.
    """
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "KONU: ODEV PART-2", fontsize=12)

    # 1. Simulate UI drawing the page prior to redaction
    surf1 = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf1 is not None

    # 2. Add staged redaction mark and burn into PDF stream
    mark = RedactionMark(
        page_number=0,
        bbox=(40, 35, 220, 65),
        overlay_text="CONFIDENTIAL",
        fill_color=(0.0, 0.0, 0.0),
        text_color=(1.0, 1.0, 1.0)
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    # 3. Requesting Cairo surface again must return a fresh, re-rendered surface
    surf2 = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf2 is not None
    assert surf2 is not surf1, "Cairo surface cache was not invalidated after redaction!"

    # 4. Underlying text must be eradicated from page
    assert "KONU: ODEV PART-2" not in page.get_text()
    assert "CONFIDENTIAL" in page.get_text()


def test_redaction_ui_flow_cache_invalidation():
    """Verify apply_all_redactions in PdfEditorWindow invalidates page cache and triggers redraw."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "CONFIDENTIAL_REPORT", fontsize=12)

    # Prime cairo surface cache
    surf_before = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf_before is not None

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    mark = RedactionMark(page_number=0, bbox=(40, 30, 250, 70), overlay_text="[REDACTED]")
    win._active_session = MagicMock()
    win._active_session.redaction_marks = {0: [mark]}
    win._page_objects_cache = {0: {}}
    win.status_label = MagicMock()
    win.pdf_view = MagicMock()
    win.annotations_sidebar = MagicMock()

    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=True):
        result = PdfEditorWindow.apply_all_redactions(win, prompt_warning=True)

    assert result is True
    # Verify cache key was purged
    cache_key = (id(doc), 0, 1.0)
    assert cache_key not in pdf_handler._cairo_page_cache

    surf_after = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf_after is not surf_before


def test_sanitize_metadata_and_xmp():
    """Verify sanitize_document strips all standard metadata, trailer Info dict, and XMP packets."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.set_metadata({
        "title": "Secret Strategy",
        "author": "Chief Officer",
        "subject": "Acquisition",
        "keywords": "confidential, merger",
        "creator": "WordSys Internal Tool",
        "producer": "Enterprise PDF",
    })
    doc.set_xml_metadata(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator><rdf:Seq>'
        '<rdf:li>Internal Department</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>'
    )

    # Verify document is dirty before sanitization
    hygiene_before = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_before["is_clean"] is False
    assert "sensitive_metadata" in hygiene_before["details"]
    assert "has_xmp" in hygiene_before["details"]

    # Sanitize document
    res = pdf_handler.sanitize_document(doc, strip_metadata=True, purge_xmp=True)
    assert res["success"] is True
    assert res["metadata_stripped"] is True
    assert res["xmp_purged"] is True

    # Verify metadata is blank
    meta = doc.metadata
    for field in ("title", "author", "subject", "keywords", "creator", "producer"):
        assert meta.get(field, "") == ""

    # Verify XMP is gone
    assert doc.get_xml_metadata() == ""
    cat = doc.pdf_catalog()
    assert "Metadata" not in doc.xref_get_keys(cat)

    # Verify hygiene check passes
    hygiene_after = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_after["is_clean"] is True


def test_sanitize_embedded_attachments():
    """Verify document-level embedded files and page-level file attachment annotations are purged."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    doc.embfile_add("payload.bin", b"sensitive binary stream", filename="payload.bin")
    page.add_file_annot((100, 100), b"attached evidence notes", "notes.txt")

    assert doc.embfile_count() == 1
    assert any(a.type[1] == "FileAttachment" for a in page.annots())

    res = pdf_handler.sanitize_document(doc, strip_metadata=False, purge_xmp=False, purge_attachments=True)
    assert res["success"] is True
    assert res["attachments_purged"] >= 2
    assert doc.embfile_count() == 0
    assert not any(a.type[1] == "FileAttachment" for a in page.annots())


def test_sanitize_comments_and_markup_preserving_forms_and_links():
    """Verify sticky notes and review comments are purged while form fields and links are preserved."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)

    # 1. Add comment & review markup
    page.add_text_annot((50, 50), "Reviewer Comment 1")
    page.add_highlight_annot(fitz.Rect(60, 60, 150, 80))

    # 2. Add an AcroForm widget (Form field)
    widget = fitz.Widget()
    widget.rect = fitz.Rect(100, 150, 250, 180)
    widget.field_name = "UserFullName"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    page.add_widget(widget)

    # 3. Add a hyperlink
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(100, 200, 200, 220), "uri": "https://example.com"})

    # Re-open doc from memory to ensure PyMuPDF parses the link structures
    doc = fitz.open("pdf", doc.tobytes())
    page = doc[0]

    # Add comments
    page.add_text_annot((50, 50), "Reviewer Comment 1")
    page.add_highlight_annot(fitz.Rect(60, 60, 150, 80))

    annots_before = [a.type[1] for a in page.annots()]
    assert "Text" in annots_before
    assert "Highlight" in annots_before
    assert len(list(page.widgets())) == 1
    assert len(page.get_links()) == 1

    # Sanitize comments with preserve_forms=True and preserve_links=True
    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=True,
        preserve_forms=True,
        preserve_links=True
    )

    assert res["success"] is True
    assert res["comments_purged"] >= 2

    annots_after = [a.type[1] for a in page.annots()]
    assert "Text" not in annots_after
    assert "Highlight" not in annots_after
    assert len(list(page.widgets())) == 1, "Form field widget should have been preserved!"
    assert len(page.get_links()) > 0, "Hyperlink should have been preserved!"


def test_sanitize_hidden_layers_ocgs():
    """Verify Optional Content Groups (OCGs) are purged during sanitization."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    doc.add_ocg("Visible Design", on=1)
    doc.add_ocg("Hidden Confidential Annotations", on=0)

    ocgs_before = doc.get_ocgs()
    assert len(ocgs_before) >= 2

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=True
    )

    assert res["success"] is True
    assert res["hidden_layers_purged"] >= 2
    assert len(doc.get_ocgs()) == 0


def test_sanitize_orphaned_and_redacted_toc_bookmarks():
    """Verify bookmarks pointing to redacted or invalid pages are cleanly purged."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)

    toc = [
        [1, "Public Chapter 1", 1],
        [1, "Confidential Section 2", 2],
        [2, "Sub-secret 2.1", 2],
        [1, "Public Conclusion", 3],
        [1, "Dangling Reference", 99]
    ]
    doc.set_toc(toc)

    # Page 1 (0-indexed, which corresponds to page 2 in 1-based TOC) was redacted
    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=True,
        redacted_pages={1}
    )

    assert res["success"] is True
    assert res["toc_items_purged"] >= 2

    cleaned_toc = doc.get_toc()
    titles = [item[1] for item in cleaned_toc]
    assert "Public Chapter 1" in titles
    assert "Public Conclusion" in titles
    assert "Confidential Section 2" not in titles
    assert "Sub-secret 2.1" not in titles


def test_sanitize_strip_all_bookmarks():
    """Verify strip_bookmarks option completely clears the entire Table of Contents."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    doc.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])

    assert len(doc.get_toc()) == 2

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        strip_bookmarks=True
    )

    assert res["success"] is True
    assert res["toc_items_purged"] == 2
    assert len(doc.get_toc()) == 0


def test_sanitize_dialog_ui_and_window_integration():
    """Verify SanitizeDialog controls and PdfEditorWindow sanitize_active_document."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    doc.set_metadata({"author": "Target User", "title": "Classified"})

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    win._active_session = MagicMock()
    win._active_session.sticky_note_objects = [MagicMock()]
    win.sticky_notes = [MagicMock()]
    win._page_objects_cache = {0: {}}
    win.status_label = MagicMock()
    win.pdf_view = MagicMock()
    win.annotations_sidebar = MagicMock()

    options = {
        "strip_metadata": True,
        "purge_xmp": True,
        "purge_attachments": True,
        "purge_hidden_layers": True,
        "purge_comments": True,
        "purge_orphaned_toc": True,
        "strip_bookmarks": False,
    }

    with patch("word_sys_pdf_editor.window.show_info_dialog") as mock_info:
        res = PdfEditorWindow.sanitize_active_document(win, options)

    assert res["success"] is True
    assert res["metadata_stripped"] is True
    assert len(win._active_session.sticky_note_objects) == 0
    assert len(win.sticky_notes) == 0
    win.status_label.set_text.assert_called()
    mock_info.assert_called_once()


def test_sanitize_dialog_rows_and_markup():
    """Verify SanitizeDialog ActionRows have valid titles and subtitles rendered without Pango markup errors."""
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw
    Adw.init()

    dlg = SanitizeDialog(None)
    rows = [
        dlg.metadata_row,
        dlg.xmp_row,
        dlg.attachments_row,
        dlg.hidden_layers_row,
        dlg.comments_row,
        dlg.orphaned_toc_row,
        dlg.strip_bookmarks_row,
        dlg.thumbnails_row,
        dlg.javascript_row,
        dlg.document_id_row,
    ]
    for row in rows:
        title = row.get_title()
        subtitle = row.get_subtitle()
        assert title and len(title) > 0, f"Row title is empty for row {row}!"
        assert subtitle and len(subtitle) > 0, f"Row subtitle is empty for row {row}!"


def test_sanitize_page_thumbnails():
    """Verify embedded page thumbnails (/Thumb) in page dictionaries are cleanly purged."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    p0 = doc[0]
    p1 = doc[1]

    # Attach dummy /Thumb references to pages
    doc.xref_set_key(p0.xref, "Thumb", "1 0 R")
    doc.xref_set_key(p1.xref, "Thumb", "2 0 R")

    hygiene_before = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_before["is_clean"] is False
    assert hygiene_before["details"].get("thumbnails_count") == 2

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=False,
        purge_thumbnails=True,
    )

    assert res["success"] is True
    assert res["thumbnails_purged"] == 2
    assert doc.xref_get_key(p0.xref, "Thumb")[0] == "null"
    assert doc.xref_get_key(p1.xref, "Thumb")[0] == "null"

    hygiene_after = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_after["is_clean"] is True


def test_sanitize_javascript_and_actions():
    """Verify OpenAction, AA dictionaries, Names/JavaScript, and widget actions are purged."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    cat = doc.pdf_catalog()

    # Add OpenAction with JS
    doc.xref_set_key(cat, "OpenAction", "<< /S /JavaScript /JS (app.alert('malicious');) >>")
    # Add Catalog /AA
    doc.xref_set_key(cat, "AA", "<< /WS << /S /JavaScript /JS (app.alert('close');) >> >>")
    # Add Page /AA
    doc.xref_set_key(page.xref, "AA", "<< /O << /S /JavaScript /JS (app.alert('open');) >> >>")
    # Add a widget with /AA
    w = fitz.Widget()
    w.rect = fitz.Rect(10, 10, 100, 30)
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = "SecureField"
    page.add_widget(w)
    for widget in page.widgets():
        doc.xref_set_key(widget.xref, "AA", "<< /K << /S /JavaScript /JS (app.alert('key');) >> >>")

    hygiene_before = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_before["is_clean"] is False
    assert hygiene_before["details"].get("has_javascript_or_actions") is True

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=False,
        purge_thumbnails=False,
        purge_javascript=True,
    )

    assert res["success"] is True
    assert res["javascript_actions_purged"] >= 4
    assert doc.xref_get_key(cat, "OpenAction")[0] == "null"
    assert doc.xref_get_key(cat, "AA")[0] == "null"
    assert doc.xref_get_key(page.xref, "AA")[0] == "null"
    for widget in page.widgets():
        assert doc.xref_get_key(widget.xref, "AA")[0] == "null"

    hygiene_after = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_after["is_clean"] is True


def test_sanitize_scrub_and_randomize_document_id(tmp_path):
    """Verify document ID (/ID trailer) is anonymized and randomized."""
    orig_path = str(tmp_path / "doc.pdf")
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.save(orig_path)
    doc.close()

    doc2 = fitz.open(orig_path)
    old_id = doc2.xref_get_key(-1, "ID")[1]
    assert old_id != "null"

    res = pdf_handler.sanitize_document(
        doc2,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=False,
        scrub_document_id=True,
    )

    assert res["success"] is True
    assert res["document_id_scrubbed"] is True
    new_id = doc2.xref_get_key(-1, "ID")[1]
    assert new_id != "null"
    assert new_id != old_id
    doc2.close()


