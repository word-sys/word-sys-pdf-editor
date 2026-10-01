import unittest
import os
import sys
import tempfile
import pathlib
import zipfile

import fitz

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableStroke


class TestAnyConvertIntegration(unittest.TestCase):
    """Thorough unit tests for Part 13: AnyConvert Backend Integration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = pathlib.Path(self.temp_dir.name)

        # Create a standard test PDF
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.page.insert_text((72, 100), "AnyConvert Integration Test", fontsize=20)
        self.page.insert_text((72, 150), "Testing Native Python Document Export.", fontsize=12)

        self.sample_pdf_path = str(self.temp_path / "sample.pdf")
        self.doc.save(self.sample_pdf_path)

    def tearDown(self):
        try:
            self.doc.close()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_01_purge_verification(self):
        """Verify that all LibreOffice and flatpak-spawn functions are completely purged."""
        self.assertFalse(hasattr(pdf_handler, "_is_flatpak_sandbox"))
        self.assertFalse(hasattr(pdf_handler, "_resolve_libreoffice_command"))
        self.assertFalse(hasattr(pdf_handler, "_export_via_libreoffice"))
        self.assertFalse(hasattr(pdf_handler, "_export_pdf_via_libreoffice"))
        self.assertTrue(pdf_handler.HAS_ANYCONVERT)
        self.assertTrue(hasattr(pdf_handler, "export_document"))

    def test_02_export_document_all_formats_canvas_mode(self):
        """Test export_document for docx, pptx, odt, odp, txt in canvas mode."""
        for fmt in ("docx", "pptx", "odt", "odp", "txt"):
            out_file = str(self.temp_path / f"export_canvas.{fmt}")
            success, err = pdf_handler.export_document(
                doc=self.doc,
                source_pdf_path=self.sample_pdf_path,
                output_path=out_file,
                target_format=fmt,
                mode="canvas",
            )
            self.assertTrue(success, f"Failed exporting {fmt} in canvas mode: {err}")
            self.assertIsNone(err)
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 0)

            # Check ZIP validity for archive formats
            if fmt in ("docx", "pptx", "odt", "odp"):
                self.assertTrue(zipfile.is_zipfile(out_file), f"{out_file} is not a valid zip archive")

            # Check TXT content
            if fmt == "txt":
                with open(out_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("AnyConvert Integration Test", content)

    def test_03_export_document_all_formats_flow_mode(self):
        """Test export_document for docx, pptx, odt, odp, txt in flow mode."""
        for fmt in ("docx", "pptx", "odt", "odp", "txt"):
            out_file = str(self.temp_path / f"export_flow.{fmt}")
            success, err = pdf_handler.export_document(
                doc=self.doc,
                source_pdf_path=self.sample_pdf_path,
                output_path=out_file,
                target_format=fmt,
                mode="flow",
            )
            self.assertTrue(success, f"Failed exporting {fmt} in flow mode: {err}")
            self.assertIsNone(err)
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 0)

            if fmt == "txt":
                with open(out_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("AnyConvert Integration Test", content)

    def test_04_in_memory_unsaved_edits_exported(self):
        """Verify that in-memory edits to doc convert directly without saving to disk first."""
        # Add edited elements to in-memory doc
        edited_doc = fitz.open()
        p = edited_doc.new_page(width=600, height=800)
        p.insert_text((72, 100), "Unsaved Original Title", fontsize=18)

        # Apply an in-memory modification
        text_obj = EditableText(
            x=72,
            y=180,
            text="Unsaved Modified Secret Content",
            font_size=16,
            color=(0, 0, 1),
            rotation=15.0,
            alignment="center",
        )
        text_obj.is_strikethrough = True
        pdf_handler._apply_single_object_to_page(edited_doc, p, text_obj)

        out_docx = str(self.temp_path / "in_memory_edit.docx")
        out_txt = str(self.temp_path / "in_memory_edit.txt")

        # Export without saving edited_doc to disk
        success_docx, err_docx = pdf_handler.export_pdf_as_docx(edited_doc, None, out_docx, mode="canvas")
        self.assertTrue(success_docx, f"DOCX in-memory export failed: {err_docx}")
        self.assertTrue(os.path.exists(out_docx))

        success_txt, err_txt = pdf_handler.export_pdf_as_text(edited_doc, out_txt, mode="canvas")
        self.assertTrue(success_txt, f"TXT in-memory export failed: {err_txt}")
        with open(out_txt, "r", encoding="utf-8") as f:
            txt_content = f.read()
        self.assertIn("SecretContent", txt_content.replace(" ", ""))
        edited_doc.close()

    def test_05_export_from_source_path_only(self):
        """Test exporting when doc is None and only source_pdf_path is provided."""
        out_docx = str(self.temp_path / "from_path.docx")
        success, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=self.sample_pdf_path,
            output_path=out_docx,
            target_format="docx",
        )
        self.assertTrue(success, f"Failed exporting from path: {err}")
        self.assertTrue(os.path.exists(out_docx))

    def test_06_format_wrappers(self):
        """Test format-specific wrappers export_pdf_as_*."""
        docx_path = str(self.temp_path / "wrapper.docx")
        odt_path = str(self.temp_path / "wrapper.odt")
        pptx_path = str(self.temp_path / "wrapper.pptx")
        odp_path = str(self.temp_path / "wrapper.odp")
        txt_path = str(self.temp_path / "wrapper.txt")

        s1, e1 = pdf_handler.export_pdf_as_docx(self.doc, self.sample_pdf_path, docx_path)
        self.assertTrue(s1, e1)
        self.assertTrue(os.path.exists(docx_path))

        s2, e2 = pdf_handler.export_pdf_as_odt(self.doc, self.sample_pdf_path, odt_path)
        self.assertTrue(s2, e2)
        self.assertTrue(os.path.exists(odt_path))

        s3, e3 = pdf_handler.export_pdf_as_pptx(self.doc, self.sample_pdf_path, pptx_path)
        self.assertTrue(s3, e3)
        self.assertTrue(os.path.exists(pptx_path))

        s4, e4 = pdf_handler.export_pdf_as_odp(self.doc, self.sample_pdf_path, odp_path)
        self.assertTrue(s4, e4)
        self.assertTrue(os.path.exists(odp_path))

        s5, e5 = pdf_handler.export_pdf_as_text(self.doc, txt_path)
        self.assertTrue(s5, e5)
        self.assertTrue(os.path.exists(txt_path))

    def test_07_invalid_inputs_and_error_handling(self):
        """Test error handling on invalid formats, missing paths, and missing documents."""
        # Missing output path
        s, err = pdf_handler.export_document(doc=self.doc, output_path="")
        self.assertFalse(s)
        self.assertIn("Destination output path must be specified", err)

        # Unsupported target format
        s, err = pdf_handler.export_document(
            doc=self.doc,
            output_path=str(self.temp_path / "out.xyz"),
            target_format="xyz",
        )
        self.assertFalse(s)
        self.assertIn("Unsupported export format", err)

        # No doc and no source path
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=None,
            output_path=str(self.temp_path / "out.docx"),
            target_format="docx",
        )
        self.assertFalse(s)
        self.assertIn("No valid document or file path", err)

    def test_08_password_protected_pdf_handling(self):
        """Test export behavior on encrypted/password-protected PDFs."""
        enc_doc = fitz.open()
        p = enc_doc.new_page()
        p.insert_text((72, 100), "Confidential AnyConvert Document")
        enc_bytes = enc_doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="securepass",
            owner_pw="ownerpass",
        )
        enc_path = str(self.temp_path / "encrypted.pdf")
        with open(enc_path, "wb") as f:
            f.write(enc_bytes)
        enc_doc.close()

        out_docx = str(self.temp_path / "decrypted.docx")

        # 1. Attempt export without password -> should report password required
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=enc_path,
            output_path=out_docx,
            target_format="docx",
            password="",
        )
        self.assertFalse(s)
        self.assertIn("password-protected", err.lower())

        # 2. Attempt export with wrong password -> should report incorrect password
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=enc_path,
            output_path=out_docx,
            target_format="docx",
            password="wrongpassword",
        )
        self.assertFalse(s)
        self.assertIn("incorrect", err.lower())

        # 3. Export with correct password -> should succeed cleanly
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=enc_path,
            output_path=out_docx,
            target_format="docx",
            password="securepass",
        )
        self.assertTrue(s, f"Export with correct password failed: {err}")
        self.assertTrue(os.path.exists(out_docx))
        self.assertGreater(os.path.getsize(out_docx), 0)

    def test_09_multilingual_unicode_content(self):
        """Test exporting text in FR, DE, ES, IT, RU, TR."""
        multi_doc = fitz.open()
        p = multi_doc.new_page(width=595, height=842)
        multilingual_text = (
            "Français: Déjà vu, été, forêt\n"
            "Deutsch: Äpfel, Grüße, Übertragen\n"
            "Español: Niño, año, pingüino, canción\n"
            "Italiano: Città, caffè, perché, più\n"
            "Русский: Привет, мир, редактирование PDF\n"
            "Türkçe: Şiir, ağaç, çağdaş, gün ışığı"
        )
        p.insert_text((50, 100), multilingual_text, fontsize=12)

        for fmt in ("docx", "odt", "txt"):
            out_file = str(self.temp_path / f"multilingual.{fmt}")
            s, err = pdf_handler.export_document(multi_doc, None, out_file, target_format=fmt, mode="canvas")
            self.assertTrue(s, f"Failed exporting multilingual {fmt}: {err}")
            self.assertTrue(os.path.exists(out_file))

        multi_doc.close()

    def test_10_multipage_complex_layout(self):
        """Test exporting multi-page PDF with shapes, text, and different aspect ratios."""
        doc = fitz.open()
        # Page 1: Portrait A4
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((72, 100), "Page 1 - Architecture Overview", fontsize=18)
        p1.draw_rect(fitz.Rect(72, 150, 500, 300), color=(0.2, 0.4, 0.8), fill=(0.95, 0.95, 1.0))
        p1.insert_text((90, 200), "Boxed layout content", fontsize=14)

        # Page 2: Landscape
        p2 = doc.new_page(width=842, height=595)
        p2.insert_text((72, 100), "Page 2 - Landscape Diagram Presentation", fontsize=18)
        p2.draw_rect(fitz.Rect(100, 200, 400, 400), color=(0.8, 0.2, 0.2), fill=(1.0, 0.95, 0.95))

        for fmt in ("pptx", "odp", "docx"):
            out_file = str(self.temp_path / f"multipage.{fmt}")
            s, err = pdf_handler.export_document(doc, None, out_file, target_format=fmt, mode="canvas")
            self.assertTrue(s, f"Failed multipage {fmt}: {err}")
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 1000)

        doc.close()

    def test_11_conversion_mode_enum(self):
        """Test passing ConversionMode enum directly as mode argument."""
        from anyconvert import ConversionMode
        out_docx = str(self.temp_path / "enum_mode.docx")
        s, err = pdf_handler.export_document(
            doc=self.doc,
            output_path=out_docx,
            target_format="docx",
            mode=ConversionMode.CANVAS,
        )
        self.assertTrue(s, err)
        self.assertTrue(os.path.exists(out_docx))

    def test_12_case_insensitive_and_dotted_format(self):
        """Test formats specified with uppercase or leading dots."""
        for fmt, ext in [(".DOCX", "docx"), ("PpTx", "pptx"), (".odt", "odt"), ("ODP", "odp"), (".TXT", "txt")]:
            out_file = str(self.temp_path / f"case_test.{ext}")
            s, err = pdf_handler.export_document(
                doc=self.doc,
                output_path=out_file,
                target_format=fmt,
            )
            self.assertTrue(s, f"Failed on format specifier '{fmt}': {err}")
            self.assertTrue(os.path.exists(out_file))

    def test_13_corrupt_bytes_error_handling(self):
        """Test graceful error handling when invalid/corrupt PDF bytes are provided."""
        corrupt_path = str(self.temp_path / "corrupt.pdf")
        with open(corrupt_path, "wb") as f:
            f.write(b"NOT_A_REAL_PDF_HEADER_OR_BODY_DATA")

        out_docx = str(self.temp_path / "corrupt_out.docx")
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=corrupt_path,
            output_path=out_docx,
            target_format="docx",
        )
        self.assertFalse(s)
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()
