from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.signature_dialog import DigitalSignatureDialog, SignatureDetailsDialog
from word_sys_pdf_editor.pades_signer import PADES_B_B, PADES_B_T, PADES_B_LT, PADES_B_LTA
from word_sys_pdf_editor.tsa_client import PRESET_TSAS, TSAConfig


class TestSignatureUI(unittest.TestCase):
    def test_digital_signature_dialog_initial_box(self):
        dlg_without_box = DigitalSignatureDialog(parent_window=None, page_count=2, current_page=0)
        self.assertEqual(dlg_without_box.position_combo.get_model().get_n_items(), 4)
        dlg_without_box.destroy()

        box = (45.0, 75.0, 190.0, 55.0)
        dlg_with_box = DigitalSignatureDialog(parent_window=None, page_count=2, current_page=0, initial_box=box)
        self.assertEqual(dlg_with_box.position_combo.get_model().get_n_items(), 5)
        self.assertEqual(dlg_with_box.position_combo.get_selected(), 0)
        dlg_with_box.destroy()

    def test_digital_signature_dialog_source_switching(self):
        dlg = DigitalSignatureDialog(parent_window=None, page_count=1, current_page=0)
        self.assertEqual(dlg.cert_source, "software")
        self.assertTrue(dlg.sw_cert_group.get_visible())
        self.assertFalse(dlg.hw_token_group.get_visible())

        with patch("word_sys_pdf_editor.signature_dialog.find_available_pkcs11_drivers", return_value=[{"name": "Mock OpenSC", "path": "/usr/lib/opensc.so"}]):
            dlg.source_combo.set_selected(1)
            self.assertEqual(dlg.cert_source, "hardware")
            self.assertFalse(dlg.sw_cert_group.get_visible())
            self.assertTrue(dlg.hw_token_group.get_visible())

        dlg.source_combo.set_selected(0)
        self.assertEqual(dlg.cert_source, "software")
        self.assertTrue(dlg.sw_cert_group.get_visible())
        self.assertFalse(dlg.hw_token_group.get_visible())
        dlg.destroy()

    def test_digital_signature_dialog_pades_and_tsa(self):
        dlg = DigitalSignatureDialog(parent_window=None, page_count=1, current_page=0)
        self.assertFalse(dlg.tsa_row.get_visible())
        self.assertFalse(dlg.custom_tsa_row.get_visible())
        self.assertFalse(dlg.tsa_auth_row.get_visible())

        dlg.pades_combo.set_selected(1)
        self.assertTrue(dlg.tsa_row.get_visible())
        self.assertFalse(dlg.custom_tsa_row.get_visible())

        dlg.tsa_combo.set_selected(3)
        self.assertTrue(dlg.custom_tsa_row.get_visible())
        self.assertTrue(dlg.tsa_auth_row.get_visible())

        dlg.pades_combo.set_selected(0)
        self.assertFalse(dlg.tsa_row.get_visible())
        self.assertFalse(dlg.custom_tsa_row.get_visible())
        self.assertFalse(dlg.tsa_auth_row.get_visible())
        dlg.destroy()

    def test_digital_signature_dialog_draw_canvas_request(self):
        draw_requested = False

        def on_draw():
            nonlocal draw_requested
            draw_requested = True

        dlg = DigitalSignatureDialog(
            parent_window=None,
            page_count=1,
            current_page=0,
            on_draw_canvas_requested=on_draw,
        )
        dlg._on_draw_canvas_clicked(None)
        self.assertTrue(draw_requested)

    def test_signature_details_dialog_presentation_and_export(self):
        dummy_sig = {
            "field_name": "TestSignature_1",
            "intact": True,
            "valid": True,
            "trusted": True,
            "signer_cn": "Jane Doe",
            "signer_org": "Acme Corp",
            "issuer_cn": "Acme Root CA",
            "pades_profile": PADES_B_LT,
            "tsa_timestamp": datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
            "tsa_valid": True,
            "tsa_cn": "DigiCert TSA",
            "has_ltv": True,
            "has_dss": True,
            "cert_der": b"\x30\x82\x01\x0a",
            "cert_pem": "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----\n",
            "sha256_fingerprint": "aabbccddeeff",
            "coverage": "ENTIRE_FILE",
        }

        dlg = SignatureDetailsDialog(parent_window=None, signatures=[dummy_sig])
        self.assertIsNotNone(dlg)

        with patch("word_sys_pdf_editor.signature_dialog.show_save_file_dialog") as mock_save:
            dlg._export_certificate(dummy_sig)
            mock_save.assert_called_once()
            args, kwargs = mock_save.call_args
            self.assertEqual(kwargs.get("initial_name"), "Jane_Doe.cer")

        dlg.destroy()

    def test_window_interactive_canvas_signature_placement(self):
        from word_sys_pdf_editor.window import PdfEditorWindow
        import fitz

        win = PdfEditorWindow()
        doc = fitz.open()
        doc.new_page(width=595.0, height=842.0)
        win.doc = doc
        win.current_pdf_page_width = 595.0
        win.current_pdf_page_height = 842.0
        win.zoom_level = 1.0
        win.view_mode = False
        win.get_page_canvas_rect = MagicMock(return_value=(0.0, 0.0, 595.0, 842.0))

        win.on_tool_selected(None, "place_signature")
        self.assertEqual(win.tool_mode, "place_signature")

        mock_gesture = MagicMock()

        win.on_drag_begin(mock_gesture, 100.0, 200.0)
        self.assertTrue(win.dragging_to_create)
        self.assertIsNotNone(win.temp_sig_bbox)
        self.assertEqual(win.temp_sig_bbox, (100.0, 200.0, 100.0, 200.0))

        win.on_drag_update(mock_gesture, 120.0, 45.0)
        self.assertEqual(win.temp_sig_bbox, (100.0, 200.0, 220.0, 245.0))

        with patch.object(DigitalSignatureDialog, "present") as mock_present:
            win.on_drag_end(mock_gesture, 120.0, 45.0)
            self.assertFalse(win.dragging_to_create)
            self.assertIsNone(win.temp_sig_bbox)
            self.assertEqual(win.tool_mode, "select")
            self.assertIsNotNone(win._digital_sig_dialog)
            self.assertEqual(win._digital_sig_dialog.initial_box, (100.0, 200.0, 120.0, 45.0))
            mock_present.assert_called_once()
            win._digital_sig_dialog.destroy()

        doc.close()
        win.destroy()


if __name__ == "__main__":
    unittest.main()
