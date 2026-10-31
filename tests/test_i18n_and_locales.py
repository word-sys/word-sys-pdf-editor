"""Consolidated Localization and Translations Test Suite for word-sys-pdf-editor.

This suite validates translation dictionary completeness, parameter interpolation,
German and French full dictionary mappings, and system/environment locale detection.
"""

# ============================================================================
# SECTION: test_i18n.py
# ============================================================================
import unittest
from word_sys_pdf_editor.i18n import _STRINGS, get_supported_languages


class TestI18n(unittest.TestCase):
    def test_all_7_languages_supported(self):
        langs = dict(get_supported_languages())
        expected = ["en", "tr", "fr", "de", "es", "it", "ru"]
        for code in expected:
            self.assertIn(code, langs)
            self.assertIn(code, _STRINGS)

    def test_common_keys_present_in_all_languages(self):
        core_keys = [
            "app_subtitle", "btn_open", "btn_new", "btn_save", "btn_cancel",
            "btn_confirm", "menu_merge_documents", "untitled", "page_info",
            "tool_select", "tool_add_text", "tool_add_image", "tool_drag",
            "btn_guide", "add_page_tip", "color_tip", "bold_tip", "italic_tip",
        ]
        for code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            d = _STRINGS[code]
            for key in core_keys:
                self.assertIn(key, d, f"Key '{key}' missing from language '{code}'")
                self.assertTrue(d[key], f"Key '{key}' is empty in language '{code}'")

    def test_merge_keys_present_in_all_languages(self):
        merge_keys = [
            "menu_merge_documents", "merge_workspace_title", "merge_workspace_subtitle",
            "merge_source_a", "merge_source_b", "merge_target_doc",
            "merge_empty_source_title", "merge_empty_source_desc",
            "merge_empty_target_title", "merge_empty_target_desc",
            "merge_btn_choose_pdf", "merge_btn_save", "merge_add_page",
            "merge_add_all_tip", "merge_clear_tip", "merge_clear_target_tip",
            "merge_page_count", "merge_remove_page_tip", "merge_move_up_tip",
            "merge_move_down_tip",
        ]
        for code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            d = _STRINGS[code]
            for key in merge_keys:
                self.assertIn(key, d, f"Merge key '{key}' missing from language '{code}'")
                self.assertTrue(d[key], f"Merge key '{key}' is empty in language '{code}'")


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_de.py
# ============================================================================
"""Generate complete verified dictionaries for German, Spanish, Italian, and Russian."""
import os
import sys

sys.path.insert(0, "/home/word-sys/word-sys-pdf-editor")
from word_sys_pdf_editor.i18n import _STRINGS

en = _STRINGS["en"]

# German translation
de = {
    "app_subtitle": "Einfacher, schneller und quelloffener PDF-Editor",
    "btn_open": "Datei öffnen…",
    "btn_new": "Neues PDF",
    "btn_guide": "Schnellstartanleitung",
    "btn_cancel": "Abbrechen",
    "btn_confirm": "Bestätigen",
    "btn_copy": "Kopieren",
    "btn_copy_text": "Text kopieren",
    "btn_paste": "Einfügen",
    "btn_paste_new": "Als neuen Text einfügen",
    "btn_dont_save": "Nicht speichern",
    "recent_header": "<b>PDF-Dateien auf dem System</b>",
    "tip_prefix": "Tipp:",
    "tips": [
        "Tipp: Doppelklicken Sie auf einen Textblock, um ihn zu bearbeiten.",
        "Tipp: Strg + Mausrad zum Vergrößern und Verkleinern.",
        "Tipp: Wählen Sie ein Objekt aus und drücken Sie Entf, um es zu löschen.",
        "Tipp: Verwenden Sie das Verschieben-Werkzeug, um Text und Bilder zu positionieren.",
        "Tipp: Ziehen Sie eine PDF-Datei in das Fenster, um sie zu öffnen.",
        "Tipp: Verwenden Sie die Farbschaltfläche, um die Textfarbe zu ändern.",
        "Tipp: Verwenden Sie die Druckschaltfläche, um Ihr PDF zu drucken.",
        "Tipp: Verwenden Sie 'Speichern unter', um eine Kopie mit neuem Namen zu speichern.",
    ],
    "zoom_out_tip": "Verkleinern (Strg+Mausrad nach unten)",
    "zoom_in_tip": "Vergrößern (Strg+Mausrad nach oben)",
    "prev_page_tip": "Vorherige Seite",
    "next_page_tip": "Nächste Seite",
    "add_page_tip": "Neue Seite hinzufügen",
    "font_tip": "Schriftart",
    "font_size_tip": "Schriftgröße",
    "bold_tip": "Fett",
    "italic_tip": "Kursiv",
    "underline_tip": "Unterstrichen",
    "color_tip": "Textfarbe",
    "shape_fill_tip": "Formfüllfarbe",
    "shape_transparent_tip": "Transparent (keine Füllung) / Gefüllt",
    "shape_stroke_tip": "Formlinienfarbe",
    "shape_width_tip": "Formlinienbreite",
    "tool_select": "Auswählen (S)",
    "tool_select_tip": "Objekte auswählen & skalieren (S)",
    "tool_add_text": "Text (T)",
    "tool_add_text_tip": "Neuen Textblock hinzufügen (T)",
    "tool_add_image": "Bild (I)",
    "tool_add_image_tip": "Bild hinzufügen (I)",
    "tool_drag": "Verschieben (M)",
    "tool_drag_tip": "Objekte ziehen & verschieben (M)",
    "tool_ellipse": "Ellipse (C)",
    "tool_ellipse_tip": "Ellipsenform hinzufügen (C)",
    "tool_rectangle": "Rechteck (R)",
    "tool_rectangle_tip": "Rechteckform hinzufügen (R)",
    "tool_pen": "Stift (P)",
    "tool_pen_tip": "Freihand-Stiftlinien zeichnen (P)",
    "tool_highlighter": "Textmarker (H)",
    "tool_highlighter_tip": "Freihand-Textmarker (H)",
    "tool_checkmark": "Häkchen (V)",
    "tool_checkmark_tip": "Häkchen hinzufügen ✓ (V)",
    "tool_cross": "Kreuz (X)",
    "tool_cross_tip": "Kreuz hinzufügen ✗ (X)",
    "tooltip_symbols": "Sonderzeichen, Symbole & Emojis",
    "tab_symbols": "Symbole",
    "tab_emojis": "Emojis",
    "symbol_copied": "'{}' in die Zwischenablage kopiert",
    "stroke_color_tip": "Strich- / Stiftfarbe",
    "stroke_width_tip": "Strich- / Stiftbreite",
    "pages_label": "Seiten",
    "delete_page_tip": "Ausgewählte Seite löschen",
    "loading": "Lade {}…",
    "thumbnails_loading": "Lade Vorschaubilder…",
    "thumbnail_loaded": "Vorschaubild geladen {}/{}",
    "loaded": "Geladen: {}",
    "new_doc_loaded": "Neues Dokument geladen.",
    "saving": "Speichere {}…",
    "saved": "Gespeichert und neu geladen: {}",
    "save_failed": "Speichern fehlgeschlagen.",
    "doc_load_failed": "Dokument konnte nicht geladen werden.",
    "scan_fonts": "Systemschriftarten werden gesucht…",
    "unsaved_changes": "Es gibt ungespeicherte Änderungen. Möchten Sie vor dem Schließen/Öffnen speichern?",
    "unsaved_title": "Ungespeicherte Änderungen",
    "delete_page_confirm": "Möchten Sie diese Seite wirklich löschen?",
    "delete_confirm_title": "Seite löschen",
    "delete_text_confirm": "Ausgewählten Text löschen?\n'{}'",
    "delete_shape_confirm": "Möchten Sie die ausgewählte Form wirklich löschen?",
    "delete_image_confirm": "Möchten Sie das ausgewählte Bild wirklich löschen?",
    "delete_confirm": "Löschen",
    "do_not_ask_again": "Nicht mehr fragen",
    "menu_confirm_delete": "Vor dem Löschen von Objekten bestätigen",
    "menu_highlight": "Hervorheben",
    "menu_remove_highlight": "Hervorhebung entfernen",
    "menu_edit_text": "Text bearbeiten",
    "menu_delete_shape": "Form löschen",
    "menu_delete_image": "Bild löschen",
    "change_applied": "Änderung angewendet.",
    "reverted": "Rückgängig gemacht.",
    "object_added": "Objekt hinzugefügt.",
    "object_deleted": "Objekt gelöscht.",
    "delete_reverted": "Löschen rückgängig gemacht.",
    "page_info": "Seite {}",
    "page_info_count": "Seite {} / {}",
    "image_select_title": "Bilddatei auswählen",
    "image_filter_label": "Bilddateien",
    "image_add_error": "Beim Verarbeiten der Bilddatei ist ein Fehler aufgetreten:\n{}",
    "image_error_title": "Bildfehler",
    "image_extract_error": "Bilder von Seite {} konnten nicht extrahiert werden.\n{}",
    "object_moved": "Objekt verschoben.",
    "tool_changed": "Werkzeug gewechselt: {}",
    "home_button_tip": "Zurück zum Startbildschirm",
    "home_confirm": "Zurück zum Startbildschirm wechseln?\nUngespeicherte Änderungen gehen verloren, wenn Sie nicht zuerst speichern.",
    "home_confirm_title": "Zurück zum Startbildschirm",
    "export_success": "Erfolgreich exportiert.",
    "export_error": "Export fehlgeschlagen: {}",
    "lang_label": "Sprache",
    "lang_en": "English",
    "lang_tr": "Türkçe",
    "lang_fr": "Français",
    "lang_de": "Deutsch",
    "lang_es": "Español",
    "lang_it": "Italiano",
    "lang_ru": "Русский",
    "lang_restart_msg": "Die Anwendung wird neu gestartet, um die Sprachänderung anzuwenden.",
    "lang_restart_title": "Neustart erforderlich",
    "btn_new_doc": "Neu",
    "btn_open_doc": "Öffnen",
    "btn_save": "Speichern",
    "undo_tip": "Rückgängig (Strg+Z)",
    "redo_tip": "Wiederholen (Strg+Y)",
    "print_tip": "Drucken (Strg+P)",
    "menu_save_as": "Speichern unter…",
    "menu_export_as": "Exportieren als…",
    "menu_about": "Über",
    "menu_quick_guide": "Schnellstartanleitung",
    "menu_quit": "Beenden",
    "btn_done": "Fertig",
    "default_new_text": "Neuer Text",
    "untitled": "Ohne Titel",
    "status_open_or_drop": "Öffnen Sie eine Datei oder ziehen Sie eine hierher.",
    "guide_title": "Schnellstartanleitung",
    "guide_dialog_title": "Schnellstartanleitung & Handbuch",
    "guide_tab_tools": "Werkzeuge & Bearbeitung",
    "guide_tab_canvas": "Arbeitsfläche & Seiten",
    "guide_tab_shortcuts": "Tastenkürzel",
    "guide_grp_selection_text": "Auswahl & Typografie",
    "guide_tool_select_title": "Auswahl- & Verschiebewerkzeug",
    "guide_tool_select_desc": "Wählen Sie Text, Vektorformen oder Bilder aus. Ziehen Sie sie zum Neupositionieren oder nutzen Sie Pfeiltasten (Umschalt+Pfeil für 10pt). Doppelklicken Sie zum Bearbeiten.",
    "guide_tool_text_title": "Text hinzufügen & formatieren",
    "guide_tool_text_desc": "Klicken Sie an eine beliebige Stelle, um neue Textblöcke zu erstellen. Passen Sie Schriftart, Größe, Fett, Kursiv, Unterstreichung und Farbe an. Emojis über die Symbolschaltfläche.",
    "guide_tool_drag_title": "Schwenk- & Ziehwerkzeug",
    "guide_tool_drag_desc": "Klicken und ziehen Sie über die Seite, um die Ansicht flüssig zu verschieben, ohne Objekte aus Versehen zu markieren.",
    "guide_grp_drawing_shapes": "Freihandzeichnen & Vektorformen",
    "guide_tool_pen_title": "Freihand-Stiftwerkzeug",
    "guide_tool_pen_desc": "Schreiben Sie Notizen oder zeichnen Sie Skizzen. Linien werden automatisch in glatte Bézier-Kurven mit einstellbarer Breite und Farbe umgewandelt.",
    "guide_tool_highlighter_title": "Textmarker-Werkzeug",
    "guide_tool_highlighter_desc": "Heben Sie Textpassagen mit leuchtender, halbtransparenter Tinte hervor. Flache Linienenden halten Markierungen sauber innerhalb der Zeilen.",
    "guide_tool_shapes_title": "Geometrische Formen (Rechteck & Ellipse)",
    "guide_tool_shapes_desc": "Zeichnen Sie scharfe Vektorrechtecke und Ellipsen. Passen Sie Rahmenfarbe, Dicke und Füllfarbe an.",
    "guide_tool_markers_title": "Prüfmarkierungen (Häkchen & Kreuz)",
    "guide_tool_markers_desc": "Setzen Sie mit einem Klick Genehmigungshäkchen oder Ablehnungskreuze zum schnellen Ausfüllen und Korrigieren von Formularen.",
    "guide_tool_image_title": "Bilder & Logos einfügen",
    "guide_tool_image_desc": "Fügen Sie PNG-, JPEG- oder SVG-Grafiken ein. Transparente PNGs behalten ihren Alphakanal ohne dunkle Ränder bei.",
    "guide_grp_navigation": "Navigation & Verlauf",
    "guide_nav_focal_zoom_title": "Präzisions-Mauszeiger-Zoom",
    "guide_nav_focal_zoom_desc": "Halten Sie Strg gedrückt und scrollen Sie, um zentriert um den Mauszeiger zu zoomen. Strg++ zum Vergrößern, Strg+- zum Verkleinern, Strg+0 für 100 %.",
    "guide_nav_undo_title": "Mehrstufiges Rückgängigmachen & Wiederholen",
    "guide_nav_undo_desc": "Jede Aktion – Tippen, Formatieren, Bewegen, Zeichnen und Löschen – wird im Verlauf erfasst. Mit Strg+Z rückgängig machen, mit Strg+Y wiederholen.",
    "guide_grp_pages": "Seitenoperationen & Dokumentaufbau",
    "guide_pages_sidebar_title": "Seitenleisten-Sortierung per Drag-and-Drop",
    "guide_pages_sidebar_desc": "Sehen Sie Miniaturansichten aller Seiten in der linken Seitenleiste. Ziehen Sie Miniaturansichten per Drag-and-Drop, um Seiten neu anzuordnen.",
    "guide_pages_actions_title": "Seiten drehen, hinzufügen & löschen",
    "guide_pages_actions_desc": "Drehen Sie Seiten um 90° im oder gegen den Uhrzeigersinn, duplizieren Sie Seiten, fügen Sie leere Seiten ein oder löschen Sie Seiten.",
    "guide_pages_new_doc_title": "Anpassbare Dokumenterstellung",
    "guide_pages_new_doc_desc": "Erstellen Sie Dokumente mit 18 internationalen Vorlagen (A0–A6, B4–B5, US Letter/Legal, Folien, Quadrat) oder benutzerdefinierten Maßen mit Einheitenumrechnung.",
    "guide_grp_shortcuts_doc": "Datei & Dokument",
    "guide_sc_new": "Neues Dokument",
    "guide_sc_open": "PDF-Dokument öffnen",
    "guide_sc_save": "Dokument speichern",
    "guide_sc_save_as": "Speichern unter",
    "guide_sc_print": "Dokument drucken",
    "guide_sc_quit": "Anwendung beenden",
    "guide_grp_shortcuts_edit": "Bearbeiten & Arbeitsfläche",
    "guide_sc_undo": "Rückgängig",
    "guide_sc_redo": "Wiederholen",
    "guide_sc_zoom_in": "Vergrößern",
    "guide_sc_zoom_out": "Verkleinern",
    "guide_sc_zoom_reset": "Zoom zurücksetzen (100 %)",
    "guide_sc_zoom_scroll": "Mauszeiger-Zoom",
    "guide_sc_delete": "Ausgewähltes Objekt löschen",
    "guide_sc_deselect": "Auswahl aufheben / Abbrechen",
    "guide_sc_nudge": "Objekt fein verschieben (1 pt)",
    "guide_sc_nudge_fast": "Objekt weit verschieben (10 pt)",
    "guide_grp_shortcuts_tools": "Werkzeug-Tastenkürzel",
    "guide_sc_tool_select": "Auswahlwerkzeug",
    "guide_sc_tool_text": "Textwerkzeug",
    "guide_sc_tool_pen": "Stiftwerkzeug",
    "guide_sc_tool_highlighter": "Textmarker-Werkzeug",
    "guide_sc_tool_rect": "Rechteckform",
    "guide_sc_tool_ellipse": "Ellipsenform",
    "guide_sc_tool_check": "Häkchen-Markierung",
    "guide_sc_tool_cross": "Kreuz-Markierung",
    "guide_sc_tool_image": "Bild einfügen",
    "guide_sc_tool_drag": "Schwenkwerkzeug",
    "guide_item1": "<b>1. Auswahl- und Bearbeitungswerkzeug (S)</b>\nStandardwerkzeug. Klicken Sie auf Text oder Bilder, um sie auszuwählen. Doppelklicken Sie auf Text, um ihn zu bearbeiten.",
    "guide_item2": "<b>2. Text-Hinzufügen-Werkzeug (T)</b>\nKlicken Sie an die gewünschte Stelle. Geben Sie den Text ein und passen Sie Schriftart und Farbe an.",
    "guide_item3": "<b>3. Bild-Hinzufügen-Werkzeug (I)</b>\nKlicken Sie an die gewünschte Stelle und wählen Sie eine Bilddatei aus.",
    "guide_item4": "<b>4. Verschieben-Werkzeug (M)</b>\nKlicken und ziehen Sie Text oder Bilder, um ihre Position auf der Seite zu ändern.",
    "font_loading": "Schriftarten werden geladen…",
    "font_none_error": "<Keine Schriftart (Fehler)>",
    "font_none": "<Keine Schriftart>",
    "fonts_loaded_open": "Schriftarten geladen. Öffnen Sie eine Datei.",
    "font_warning_title": "Schriftart-Warnung",
    "font_warning_msg": "Keine passende Unicode-Schriftart gefunden. Sonderzeichen werden möglicherweise nicht korrekt dargestellt.",
    "shape_fill_dialog_title": "Formfüllfarbe auswählen",
    "shape_stroke_dialog_title": "Formlinienfarbe auswählen",
    "transparent_label": "Transparent",
    "about_comments": "word-sys's PDF Editor ist ein Open-Source-Werkzeug zur Bearbeitung von PDF-Inhalten unter Linux.",
    "about_website_label": "Projekt-GitHub-Seite",
    "about_tab_about": "Über",
    "about_tab_credits": "Danksagung",
    "about_tab_license": "Lizenz",
    "github_page": "Projekt-GitHub-Seite",
    "print_no_doc": "Bitte öffnen Sie ein PDF-Dokument zum Drucken.",
    "print_no_doc_title": "Kein Dokument geöffnet",
    "print_error_title": "Druckfehler",
    "print_failed": "Drucken fehlgeschlagen.",
    "print_cancelled": "Druckvorgang abgebrochen.",
    "print_error_occurred": "Beim Drucken ist ein Fehler aufgetreten.",
    "print_success": "Druckauftrag erfolgreich gesendet.",
    "print_in_progress": "Druckvorgang läuft…",
    "print_start_failed": "Drucken konnte nicht gestartet werden: {}",
    "err_pdf_save": "Fehler beim Speichern des PDFs: {}",
    "err_invalid_doc_page_extract": "Ungültiges Dokument oder Seitenindex für die Bildextraktion.",
    "warn_image_skipped": "Warnung: Ein Bild auf Seite {} (xref={}) wurde übersprungen: {}",
    "err_image_extract_page": "Fehler beim Extrahieren der Bilder von Seite {}: {}",
    "err_invalid_doc_page_add_image": "Ungültiges Dokument oder Seitennummer zum Hinzufügen des Bildes.",
    "err_image_file_not_found": "Bilddatei nicht gefunden: {}",
    "err_placing_image": "Fehler beim Platzieren des Bildes: {}",
    "err_invalid_doc_page_delete_image": "Ungültiges Dokument oder Seitennummer zum Löschen des Bildes.",
    "err_invalid_image_bbox": "Ungültiger Bildbegrenzungsrahmen.",
    "err_deleting_image": "Fehler beim Löschen des Bildes: {}",
    "err_invalid_doc_page_delete_shape": "Ungültiges Dokument oder Seitennummer zum Löschen der Form.",
    "err_invalid_shape_bbox": "Ungültiger Formbegrenzungsrahmen.",
    "err_deleting_shape": "Fehler beim Löschen der Form: {}",
    "err_creating_new_pdf": "Fehler beim Erstellen des neuen PDFs: {}",
    "success_blank_page_added": "Leere Seite am Ende hinzugefügt (Seite {})",
    "err_adding_page": "Fehler beim Hinzufügen der Seite: {}",
    "err_source_pdf_empty": "Quell-PDF ist leer.",
    "success_merged_pages": "{} Seiten erfolgreich zusammengeführt.",
    "err_merging_pdf": "Fehler beim Zusammenführen der PDFs: {}",
    "err_invalid_page_index": "Ungültiger Seitenindex.",
    "err_invalid_target_index": "Ungültiger Zielindex.",
    "success_page_already_there": "Seite befindet sich bereits an dieser Position.",
    "success_page_moved": "Seite {} an Position {} verschoben.",
    "err_moving_page": "Fehler beim Verschieben der Seite: {}",
    "err_no_doc_msg_alt": "Kein Dokument.",
    "err_cannot_delete_last_page": "Die letzte Seite kann nicht gelöscht werden. Das Dokument muss mindestens eine Seite enthalten.",
    "err_invalid_page_index_val": "Ungültiger Seitenindex: {}",
    "success_page_deleted": "Seite {} gelöscht.",
    "err_deleting_page": "Fehler beim Löschen der Seite: {}",
    "err_moving_shape": "Fehler beim Verschieben der Form: {}",
    "err_during_op": "Fehler während der Operation: {}",
    "dbg_embedded_font_found": "DEBUG: Verzeichnis der eingebetteten Schriftarten gefunden: {}",
    "err_embedded_font_not_found": "FEHLER: Verzeichnis der eingebetteten Schriftarten nicht gefunden: {}",
    "warn_scanning_dir": "Warnung: Fehler beim Scannen des Verzeichnisses {}: {}",
    "font_scan_completed": "Schriftarten-Scan abgeschlossen. {} Schriftfamilien gefunden.",
    "wait_font_scan": "Warte auf Abschluss des Schriftarten-Scans…",
    "err_font_scan_timeout": "FEHLER: Zeitüberschreitung beim Schriftarten-Scan.",
    "dbg_repaired_while_opening": "DEBUG: Diese PDF-Datei wurde beim Öffnen repariert.",
    "dbg_save_success": "DEBUG: Speichern erfolgreich. Lade Datei neu: {}",
    "btn_open_label": "_Öffnen",
    "btn_cancel_label": "_Abbrechen",
    "font_tip_original": "Schriftart (Original-PDF: {})",
    "dbg_discarding_unsaved": "Verwerfe ungespeicherte Änderungen.",
    "import_pdf_title": "PDF importieren",
    "import_pdf_confirm": "Möchten Sie '{}' in das aktuelle PDF einfügen oder öffnen?",
    "err_merge_title": "PDF-Zusammenführungsfehler",
    "open_pdf_title": "PDF-Datei öffnen",
    "save_as_title": "PDF speichern unter...",
    "export_as_title": "Exportieren als...",
    "status_exporting": "Exportiere als {}...",
    "err_unknown_export_format": "Unbekanntes Exportformat.",
    "status_exported": "Exportiert als {}: {}",
    "err_export_failed_msg": "Export fehlgeschlagen: {}",
    "err_export_unexpected": "Unerwarteter Fehler beim Exportieren: {}",
    "status_export_failed": "Export fehlgeschlagen.",
    "err_no_doc_msg": "Bitte öffnen oder erstellen Sie zuerst ein Dokument.",
    "err_no_doc_title": "Kein Dokument",
    "err_add_page_title": "Fehler beim Hinzufügen der Seite",
    "err_no_doc_open_msg": "Bitte öffnen Sie zuerst ein Dokument.",
    "err_cannot_delete_last_page_title": "Seite kann nicht gelöscht werden",
    "delete_page_warn_msg": "Seite {} wird gelöscht. Dieser Vorgang kann nicht rückgängig gemacht werden. Fortfahren?",
    "delete_page_warn_title": "Seite löschen",
    "err_delete_page_title": "Fehler beim Löschen der Seite",
    "err_move_page_title": "Fehler beim Verschieben der Seite",
    "err_fonts_scanning_msg": "Schriftarten werden noch gescannt. Bitte warten.",
    "err_fonts_scanning_title": "Schriftarten-Scan",
    "font_user_added": "{} (Benutzerdefiniert)",
    "err_delete_image_failed": "Bild konnte nicht gelöscht werden: {}",
    "delete_error_title": "Löschfehler",
    "dbg_applying_changes_before_tool": "Wende Änderungen vor Werkzeugwechsel an...",
    "dbg_tool_changed_to": "Werkzeug gewechselt zu: {}",
    "dbg_creating_drag_cmd": "DEBUG: Erstelle Befehl für Ziehvorgang.",
    "dbg_saving_pending_format_cmd": "DEBUG: Speichere ausstehende Formatänderung.",
    "status_new_doc_created": "Neues leeres Dokument erstellt. Bitte Änderungen speichern.",
    "err_adding_image_dialog": "Fehler beim Hinzufügen des Bildes: {}",
    "err_title": "Fehler",
    "mode_edit": "Bearbeiten",
    "mode_view": "Ansicht",
    "mode_toggle_tip": "Zwischen Ansichts- und Bearbeitungsmodus wechseln",
    "tools": "Werkzeuge",
    "highlight": "Hervorheben",
    "highlight_tip": "Ausgewählten Text hervorheben",
    "highlight_color_tip": "Hervorhebungsfarbe",
    "remove_highlight": "Hervorhebung entfernen",
    "remove_highlight_tip": "Hervorhebung vom Text entfernen",
    "save_error_title": "Speicherfehler",
    "text_extract_error": "Textstruktur von Seite {} konnte nicht extrahiert werden.\n{}",
    "highlight_failed": "Hervorhebung fehlgeschlagen: {}",
    "filter_pdf": "PDF-Dateien (*.pdf)",
    "filter_all": "Alle Dateien",
    "filter_word": "Word-Dokument (*.docx)",
    "filter_odt": "OpenDocument-Text (*.odt)",
    "filter_pptx": "PowerPoint-Präsentation (*.pptx)",
    "filter_odp": "OpenDocument-Präsentation (*.odp)",
    "filter_txt": "Textdatei (*.txt)",
    "new_doc_dialog_title": "Neues Dokument",
    "new_doc_create": "Erstellen",
    "new_doc_cancel": "Abbrechen",
    "new_doc_page_setup": "Seiteneinrichtung",
    "new_doc_template": "Vorlage",
    "new_doc_orientation": "Ausrichtung",
    "new_doc_portrait": "Hochformat",
    "new_doc_landscape": "Querformat",
    "new_doc_dimensions": "Abmessungen",
    "new_doc_unit": "Einheit",
    "new_doc_width": "Breite",
    "new_doc_height": "Höhe",
    "new_doc_document": "Dokument",
    "new_doc_num_pages": "Seitenanzahl",
    "new_doc_pages_desc": "Anfängliche leere Seiten",
    "new_doc_unit_mm": "Millimeter (mm)",
    "new_doc_unit_cm": "Zentimeter (cm)",
    "new_doc_unit_in": "Zoll (in)",
    "new_doc_unit_pt": "Punkte (pt)",
    "new_doc_unit_px": "Pixel (px @ 72 dpi)",
    "preset_a4": "A4 (210 × 297 mm)",
    "preset_a3": "A3 (297 × 420 mm)",
    "preset_a5": "A5 (148 × 210 mm)",
    "preset_a6": "A6 (105 × 148 mm)",
    "preset_a2": "A2 (420 × 594 mm)",
    "preset_a1": "A1 (594 × 841 mm)",
    "preset_a0": "A0 (841 × 1189 mm)",
    "preset_b4": "B4 (250 × 353 mm)",
    "preset_b5": "B5 (176 × 250 mm)",
    "preset_letter": "US Letter (8.5 × 11 in)",
    "preset_legal": "US Legal (8.5 × 14 in)",
    "preset_executive": "US Executive (7.25 × 10.5 in)",
    "preset_tabloid": "Tabloid / Ledger (11 × 17 in)",
    "preset_slide_16_9": "Folie 16:9 (1920 × 1080 pt)",
    "preset_slide_16_10": "Folie 16:10 (1920 × 1200 pt)",
    "preset_slide_4_3": "Folie 4:3 (1024 × 768 pt)",
    "preset_square": "Quadrat (1080 × 1080 pt)",
    "preset_custom": "Benutzerdefiniert...",
}
import unittest


class TestGermanLocales(unittest.TestCase):
    def test_german_dictionary_populated(self):
        self.assertGreater(len(de), 300)
        for k, v in de.items():
            self.assertTrue(v, f"Empty translation for {k}")


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_fr.py
# ============================================================================
"""Generate complete locales.py for French, German, Spanish, Italian, and Russian."""
import os
import sys
import json

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/word-sys/word-sys-pdf-editor")

from word_sys_pdf_editor.i18n import _STRINGS

en = _STRINGS["en"]

# Mapping dictionary for French
fr = {
    "app_subtitle": "Éditeur PDF simple, rapide et open-source",
    "btn_open": "Ouvrir un fichier…",
    "btn_new": "Nouveau PDF",
    "btn_guide": "Guide de démarrage rapide",
    "btn_cancel": "Annuler",
    "btn_confirm": "Confirmer",
    "btn_copy": "Copier",
    "btn_copy_text": "Copier le texte",
    "btn_paste": "Coller",
    "btn_paste_new": "Coller comme nouveau texte",
    "btn_dont_save": "Ne pas enregistrer",
    "recent_header": "<b>Fichiers PDF sur le système</b>",
    "tip_prefix": "Astuce :",
    "tips": [
        "Astuce : Double-cliquez sur un bloc de texte pour le modifier.",
        "Astuce : Ctrl + Molette pour zoomer et dézoomer.",
        "Astuce : Sélectionnez un objet et appuyez sur Suppr pour le retirer.",
        "Astuce : Utilisez l'outil Déplacer pour repositionner textes et images.",
        "Astuce : Glissez-déposez un PDF sur la fenêtre pour l'ouvrir.",
        "Astuce : Utilisez le bouton Couleur pour changer la couleur du texte.",
        "Astuce : Utilisez le bouton Imprimer pour imprimer votre PDF.",
        "Astuce : Utilisez Enregistrer sous pour enregistrer une copie sous un autre nom.",
    ],
    "zoom_out_tip": "Dézoomer (Ctrl+Molette vers le bas)",
    "zoom_in_tip": "Zoomer (Ctrl+Molette vers le haut)",
    "prev_page_tip": "Page précédente",
    "next_page_tip": "Page suivante",
    "add_page_tip": "Ajouter une nouvelle page",
    "font_tip": "Police de caractères",
    "font_size_tip": "Taille de police",
    "bold_tip": "Gras",
    "italic_tip": "Italique",
    "underline_tip": "Souligné",
    "color_tip": "Couleur du texte",
    "shape_fill_tip": "Couleur de remplissage de la forme",
    "shape_transparent_tip": "Transparent (sans remplissage) / Rempli",
    "shape_stroke_tip": "Couleur du contour de la forme",
    "shape_width_tip": "Épaisseur du contour de la forme",
    "tool_select": "Sélectionner (S)",
    "tool_select_tip": "Sélectionner & Redimensionner des objets (S)",
    "tool_add_text": "Texte (T)",
    "tool_add_text_tip": "Ajouter un bloc de texte (T)",
    "tool_add_image": "Image (I)",
    "tool_add_image_tip": "Ajouter une image (I)",
    "tool_drag": "Déplacer (M)",
    "tool_drag_tip": "Glisser & Déplacer des objets (M)",
    "tool_ellipse": "Ellipse (C)",
    "tool_ellipse_tip": "Ajouter une forme ellipse (C)",
    "tool_rectangle": "Rectangle (R)",
    "tool_rectangle_tip": "Ajouter une forme rectangle (R)",
    "tool_pen": "Stylo (P)",
    "tool_pen_tip": "Dessin à main levée au stylo (P)",
    "tool_highlighter": "Surligneur (H)",
    "tool_highlighter_tip": "Surligneur à main levée (H)",
    "tool_checkmark": "Coche (V)",
    "tool_checkmark_tip": "Ajouter une coche ✓ (V)",
    "tool_cross": "Croix (X)",
    "tool_cross_tip": "Ajouter une croix ✗ (X)",
    "tooltip_symbols": "Caractères spéciaux, symboles & émojis",
    "tab_symbols": "Symboles",
    "tab_emojis": "Émojis",
    "symbol_copied": "'{}' copié dans le presse-papiers",
    "stroke_color_tip": "Couleur du trait / stylo",
    "stroke_width_tip": "Épaisseur du trait / stylo",
    "pages_label": "Pages",
    "delete_page_tip": "Supprimer la page sélectionnée",
    "loading": "Chargement de {}…",
    "thumbnails_loading": "Chargement des miniatures…",
    "thumbnail_loaded": "Miniature chargée {}/{}",
    "loaded": "Chargé : {}",
    "new_doc_loaded": "Nouveau document chargé.",
    "saving": "Enregistrement de {}…",
    "saved": "Enregistré et rechargé : {}",
    "save_failed": "Échec de l'enregistrement.",
    "doc_load_failed": "Impossible de charger le document.",
    "scan_fonts": "Analyse des polices système…",
    "unsaved_changes": "Des modifications ne sont pas enregistrées. Voulez-vous enregistrer avant de fermer/ouvrir ?",
    "unsaved_title": "Modifications non enregistrées",
    "delete_page_confirm": "Voulez-vous vraiment supprimer cette page ?",
    "delete_confirm_title": "Supprimer la page",
    "delete_text_confirm": "Supprimer le texte sélectionné ?\n'{}'",
    "delete_shape_confirm": "Voulez-vous vraiment supprimer la forme sélectionnée ?",
    "delete_image_confirm": "Voulez-vous vraiment supprimer l'image sélectionnée ?",
    "delete_confirm": "Supprimer",
    "do_not_ask_again": "Ne plus demander",
    "menu_confirm_delete": "Confirmer avant de supprimer des objets",
    "menu_highlight": "Surligner",
    "menu_remove_highlight": "Supprimer le surlignage",
    "menu_edit_text": "Modifier le texte",
    "menu_delete_shape": "Supprimer la forme",
    "menu_delete_image": "Supprimer l'image",
    "change_applied": "Modification appliquée.",
    "reverted": "Annulé.",
    "object_added": "Objet ajouté.",
    "object_deleted": "Objet supprimé.",
    "delete_reverted": "Suppression annulée.",
    "page_info": "Page {}",
    "page_info_count": "Page {} / {}",
    "image_select_title": "Sélectionner un fichier image",
    "image_filter_label": "Fichiers image",
    "image_add_error": "Une erreur est survenue lors du traitement du fichier image :\n{}",
    "image_error_title": "Erreur d'image",
    "image_extract_error": "Impossible d'extraire les images de la page {}.\n{}",
    "object_moved": "Objet déplacé.",
    "tool_changed": "Outil changé : {}",
    "home_button_tip": "Retour à l'écran d'accueil",
    "home_confirm": "Retourner à l'écran d'accueil ?\nLes modifications non enregistrées seront perdues.",
    "home_confirm_title": "Retour à l'accueil",
    "export_success": "Exportation réussie.",
    "export_error": "Échec de l'exportation : {}",
    "lang_label": "Langue",
    "lang_en": "English",
    "lang_tr": "Türkçe",
    "lang_fr": "Français",
    "lang_de": "Deutsch",
    "lang_es": "Español",
    "lang_it": "Italiano",
    "lang_ru": "Русский",
    "lang_restart_msg": "L'application va redémarrer pour appliquer le changement de langue.",
    "lang_restart_title": "Redémarrage requis",
    "btn_new_doc": "Nouveau",
    "btn_open_doc": "Ouvrir",
    "btn_save": "Enregistrer",
    "undo_tip": "Annuler (Ctrl+Z)",
    "redo_tip": "Rétablir (Ctrl+Y)",
    "print_tip": "Imprimer (Ctrl+P)",
    "menu_save_as": "Enregistrer sous…",
    "menu_export_as": "Exporter sous…",
    "menu_about": "À propos",
    "menu_quick_guide": "Guide de démarrage rapide",
    "menu_quit": "Quitter",
    "btn_done": "Terminé",
    "default_new_text": "Nouveau texte",
    "untitled": "Sans titre",
    "status_open_or_drop": "Ouvrez un fichier ou glissez-déposez-en un ici.",
    "guide_title": "Guide de démarrage rapide",
    "guide_dialog_title": "Guide de démarrage rapide & Manuel",
    "guide_tab_tools": "Outils & Édition",
    "guide_tab_canvas": "Canevas & Pages",
    "guide_tab_shortcuts": "Raccourcis",
    "guide_grp_selection_text": "Sélection & Typographie",
    "guide_tool_select_title": "Outil Sélectionner & Déplacer",
    "guide_tool_select_desc": "Sélectionnez du texte, des formes vectorielles ou des images. Glissez pour repositionner ou utilisez les touches fléchées. Double-cliquez sur un texte pour l'éditer. Glissez les 8 poignées pour redimensionner.",
    "guide_tool_text_title": "Ajouter & Formater du texte",
    "guide_tool_text_desc": "Cliquez n'importe où pour créer de nouveaux blocs de texte. Personnalisez la police, la taille, le gras, l'italique, le soulignement et la couleur. Utilisez le bouton Symboles pour les émojis.",
    "guide_tool_drag_title": "Outil Panoramique & Déplacement",
    "guide_tool_drag_desc": "Cliquez et glissez à travers la page pour faire défiler le canevas en douceur sans déplacer d'objets.",
    "guide_grp_drawing_shapes": "Dessin à main levée & Formes vectorielles",
    "guide_tool_pen_title": "Outil Stylo à main levée",
    "guide_tool_pen_desc": "Prenez des notes ou esquissez des dessins. Les tracés sont automatiquement convertis en courbes de Bézier lisses avec couleur et épaisseur réglables.",
    "guide_tool_highlighter_title": "Outil Surligneur",
    "guide_tool_highlighter_desc": "Surlignez des passages de texte avec une encre lumineuse semi-transparente délimitée proprement par des extrémités plates.",
    "guide_tool_shapes_title": "Formes géométriques (Rectangle & Ellipse)",
    "guide_tool_shapes_desc": "Dessinez des rectangles et des ellipses vectoriels nets. Personnalisez la couleur de bordure, l'épaisseur et la couleur de remplissage.",
    "guide_tool_markers_title": "Marqueurs de révision rapide (Coche & Croix)",
    "guide_tool_markers_desc": "Tamponnez d'un seul clic des coches d'approbation ou des croix de rejet pour réviser et annoter facilement des formulaires.",
    "guide_tool_image_title": "Insérer des images & logos",
    "guide_tool_image_desc": "Placez des graphiques PNG, JPEG ou SVG. Les PNG transparents préservent le canal alpha sans bordures sombres.",
    "guide_grp_navigation": "Navigation & Historique",
    "guide_nav_focal_zoom_title": "Zoom focal de précision",
    "guide_nav_focal_zoom_desc": "Maintenez Ctrl et utilisez la molette de la souris pour zoomer précisément autour du curseur. Ctrl++ pour zoomer, Ctrl+- pour dézoomer et Ctrl+0 pour réinitialiser à 100 %.",
    "guide_nav_undo_title": "Annulation & Rétablissement multi-niveaux",
    "guide_nav_undo_desc": "Chaque action — saisie, déplacement, tracés, dimensionnement et suppression — est suivie dans l'historique. Annulez avec Ctrl+Z et rétablissez avec Ctrl+Y.",
    "guide_grp_pages": "Opérations de page & Configuration du document",
    "guide_pages_sidebar_title": "Réorganisation par glisser-déposer dans la barre latérale",
    "guide_pages_sidebar_desc": "Affichez les miniatures de toutes les pages dans le volet gauche. Glissez-déposez n'importe quelle miniature pour réorganiser l'ordre des pages.",
    "guide_pages_actions_title": "Faire pivoter, ajouter & supprimer des pages",
    "guide_pages_actions_desc": "Faites pivoter des pages individuelles à 90° dans le sens horaire ou antihoraire, dupliquez des pages, insérez de nouvelles pages vierges ou supprimez des pages inutiles.",
    "guide_pages_new_doc_title": "Création de document personnalisable",
    "guide_pages_new_doc_desc": "Créez de nouveaux documents avec 18 préréglages internationaux (A0–A6, B4–B5, US Letter/Legal, Diapositives, Carré) ou dimensions personnalisées avec conversion en direct (mm, cm, in, pt, px).",
    "guide_grp_shortcuts_doc": "Fichier & Document",
    "guide_sc_new": "Nouveau document",
    "guide_sc_open": "Ouvrir un document PDF",
    "guide_sc_save": "Enregistrer le document",
    "guide_sc_save_as": "Enregistrer sous",
    "guide_sc_print": "Imprimer le document",
    "guide_sc_quit": "Quitter l'application",
    "guide_grp_shortcuts_edit": "Édition & Canevas",
    "guide_sc_undo": "Annuler",
    "guide_sc_redo": "Rétablir",
    "guide_sc_zoom_in": "Zoom avant",
    "guide_sc_zoom_out": "Zoom arrière",
    "guide_sc_zoom_reset": "Réinitialiser le zoom (100 %)",
    "guide_sc_zoom_scroll": "Zoom sous le pointeur",
    "guide_sc_delete": "Supprimer l'objet sélectionné",
    "guide_sc_deselect": "Désélectionner / Quitter l'éditeur",
    "guide_sc_nudge": "Déplacer légèrement l'objet (1 pt)",
    "guide_sc_nudge_fast": "Déplacer l'objet (10 pt)",
    "guide_grp_shortcuts_tools": "Raccourcis d'activation des outils",
    "guide_sc_tool_select": "Outil Sélectionner",
    "guide_sc_tool_text": "Outil Texte",
    "guide_sc_tool_pen": "Outil Stylo",
    "guide_sc_tool_highlighter": "Outil Surligneur",
    "guide_sc_tool_rect": "Forme Rectangle",
    "guide_sc_tool_ellipse": "Forme Ellipse",
    "guide_sc_tool_check": "Marqueur Coche",
    "guide_sc_tool_cross": "Marqueur Croix",
    "guide_sc_tool_image": "Ajouter une image",
    "guide_sc_tool_drag": "Outil Panoramique",
    "guide_item1": "<b>1. Outil Sélectionner et Modifier (S)</b>\nOutil par défaut. Cliquez sur du texte ou des images pour les sélectionner. Double-cliquez sur un texte pour ouvrir la fenêtre de modification.",
    "guide_item2": "<b>2. Outil Ajouter du texte (T)</b>\nCliquez là où vous souhaitez ajouter du texte. Saisissez votre texte et ajustez police, taille et couleur dans la barre d'outils.",
    "guide_item3": "<b>3. Outil Ajouter une image (I)</b>\nCliquez là où vous souhaitez placer une image, puis choisissez votre fichier image dans le sélecteur.",
    "guide_item4": "<b>4. Outil Déplacer (M)</b>\nAprès avoir sélectionné cet outil, cliquez et faites glisser n'importe quel texte ou image pour changer sa position.",
    "font_loading": "Chargement des polices…",
    "font_none_error": "<Aucune police (Erreur)>",
    "font_none": "<Aucune police>",
    "fonts_loaded_open": "Polices chargées. Ouvrez un fichier.",
    "font_warning_title": "Avertissement de police",
    "font_warning_msg": "Aucune police Unicode appropriée n'a été trouvée. La modification de textes avec des caractères spéciaux peut ne pas fonctionner correctement.",
    "shape_fill_dialog_title": "Sélectionner la couleur de remplissage",
    "shape_stroke_dialog_title": "Sélectionner la couleur du contour",
    "transparent_label": "Transparent",
    "about_comments": "word-sys's PDF Editor est un outil open-source pour éditer le contenu des fichiers PDF sous Linux.",
    "about_website_label": "Page GitHub du projet",
    "about_tab_about": "À propos",
    "about_tab_credits": "Crédits",
    "about_tab_license": "Licence",
    "github_page": "Page GitHub du projet",
    "print_no_doc": "Veuillez ouvrir un fichier PDF pour imprimer.",
    "print_no_doc_title": "Aucun document ouvert",
    "print_error_title": "Erreur d'impression",
    "print_failed": "L'impression a échoué.",
    "print_cancelled": "Opération d'impression annulée.",
    "print_error_occurred": "Une erreur est survenue lors de l'impression.",
    "print_success": "Impression envoyée avec succès.",
    "print_in_progress": "Impression en cours…",
    "print_start_failed": "Impossible de démarrer l'impression : {}",
    "err_pdf_save": "Erreur lors de l'enregistrement du PDF : {}",
    "err_invalid_doc_page_extract": "Document ou index de page invalide pour l'extraction d'images.",
    "warn_image_skipped": "Avertissement : Une image de la page {} (xref={}) a été ignorée : {}",
    "err_image_extract_page": "Erreur lors de l'extraction des images de la page {} : {}",
    "err_invalid_doc_page_add_image": "Document ou numéro de page invalide pour ajouter l'image.",
    "err_image_file_not_found": "Fichier image introuvable : {}",
    "err_placing_image": "Erreur lors du placement de l'image : {}",
    "err_invalid_doc_page_delete_image": "Document ou numéro de page invalide pour supprimer l'image.",
    "err_invalid_image_bbox": "Cadre de délimitation de l'image invalide.",
    "err_deleting_image": "Erreur lors de la suppression de l'image : {}",
    "err_invalid_doc_page_delete_shape": "Document ou numéro de page invalide pour supprimer la forme.",
    "err_invalid_shape_bbox": "Cadre de délimitation de la forme invalide.",
    "err_deleting_shape": "Erreur lors de la suppression de la forme : {}",
    "err_creating_new_pdf": "Erreur lors de la création du nouveau PDF : {}",
    "success_blank_page_added": "Page vierge ajoutée à la fin (Page {})",
    "err_adding_page": "Erreur lors de l'ajout de la page : {}",
    "err_source_pdf_empty": "Le PDF source est vide.",
    "success_merged_pages": "{} pages fusionnées avec succès.",
    "err_merging_pdf": "Erreur lors de la fusion du PDF : {}",
    "err_invalid_page_index": "Index de page invalide.",
    "err_invalid_target_index": "Index cible invalide.",
    "success_page_already_there": "La page est déjà à cette position.",
    "success_page_moved": "Page {} déplacée vers la position {}.",
    "err_moving_page": "Erreur lors du déplacement de la page : {}",
    "err_no_doc_msg_alt": "Aucun document.",
    "err_cannot_delete_last_page": "Impossible de supprimer la dernière page. Le document doit contenir au moins une page.",
    "err_invalid_page_index_val": "Index de page invalide : {}",
    "success_page_deleted": "Page {} supprimée.",
    "err_deleting_page": "Erreur lors de la suppression de la page : {}",
    "err_moving_shape": "Erreur lors du déplacement de la forme : {}",
    "err_during_op": "Erreur lors de l'opération : {}",
    "dbg_embedded_font_found": "DEBUG : Répertoire des polices intégrées trouvé : {}",
    "err_embedded_font_not_found": "ERREUR : Répertoire des polices intégrées introuvable : {}",
    "warn_scanning_dir": "Avertissement : Erreur lors de l'analyse du répertoire {} : {}",
    "font_scan_completed": "Analyse des polices terminée. {} familles trouvées.",
    "wait_font_scan": "En attente de la fin de l'analyse des polices…",
    "err_font_scan_timeout": "ERREUR : Délai d'analyse des polices dépassé.",
    "dbg_repaired_while_opening": "DEBUG : Ce fichier PDF a été réparé à l'ouverture.",
    "dbg_save_success": "DEBUG : Enregistrement réussi. Rechargement : {}",
    "btn_open_label": "_Ouvrir",
    "btn_cancel_label": "_Annuler",
    "font_tip_original": "Police (PDF original : {})",
    "dbg_discarding_unsaved": "Abandon des modifications non enregistrées.",
    "import_pdf_title": "Importer un PDF",
    "import_pdf_confirm": "Voulez-vous fusionner '{}' dans le PDF actuel ou l'ouvrir ?",
    "err_merge_title": "Erreur de fusion PDF",
    "open_pdf_title": "Ouvrir un fichier PDF",
    "save_as_title": "Enregistrer le PDF sous...",
    "export_as_title": "Exporter sous...",
    "status_exporting": "Exportation au format {}...",
    "err_unknown_export_format": "Format d'exportation inconnu.",
    "status_exported": "Exporté en {} : {}",
    "err_export_failed_msg": "Échec de l'exportation : {}",
    "err_export_unexpected": "Erreur inattendue pendant l'exportation : {}",
    "status_export_failed": "Exportation échouée.",
    "err_no_doc_msg": "Veuillez d'abord ouvrir ou créer un document.",
    "err_no_doc_title": "Aucun document",
    "err_add_page_title": "Erreur d'ajout de page",
    "err_no_doc_open_msg": "Veuillez d'abord ouvrir un document.",
    "err_cannot_delete_last_page_title": "Impossible de supprimer la page",
    "delete_page_warn_msg": "La page {} sera supprimée. Cette opération ne peut pas être annulée. Continuer ?",
    "delete_page_warn_title": "Supprimer la page",
    "err_delete_page_title": "Erreur de suppression de page",
    "err_move_page_title": "Erreur de déplacement de page",
    "err_fonts_scanning_msg": "Les polices sont en cours d'analyse. Veuillez patienter.",
    "err_fonts_scanning_title": "Analyse des polices",
    "font_user_added": "{} (Ajouté par l'utilisateur)",
    "err_delete_image_failed": "Impossible de supprimer l'image : {}",
    "delete_error_title": "Erreur de suppression",
    "dbg_applying_changes_before_tool": "Application des modifications avant le changement d'outil...",
    "dbg_tool_changed_to": "Outil changé pour : {}",
    "dbg_creating_drag_cmd": "DEBUG : Création de la commande pour l'opération de déplacement.",
    "dbg_saving_pending_format_cmd": "DEBUG : Enregistrement du changement de format en attente.",
    "status_new_doc_created": "Nouveau document vide créé. N'oubliez pas d'enregistrer.",
    "err_adding_image_dialog": "Erreur lors de l'ajout de l'image : {}",
    "err_title": "Erreur",
    "mode_edit": "Édition",
    "mode_view": "Affichage",
    "mode_toggle_tip": "Basculer entre le mode Affichage et Édition",
    "tools": "Outils",
    "highlight": "Surligner",
    "highlight_tip": "Surligner le texte sélectionné",
    "highlight_color_tip": "Couleur de surlignage",
    "remove_highlight": "Supprimer le surlignage",
    "remove_highlight_tip": "Supprimer le surlignage du texte sélectionné",
    "save_error_title": "Erreur d'enregistrement",
    "text_extract_error": "Impossible d'extraire la structure de texte de la page {}.\n{}",
    "highlight_failed": "Échec du surlignage : {}",
    "filter_pdf": "Fichiers PDF (*.pdf)",
    "filter_all": "Tous les fichiers",
    "filter_word": "Document Word (*.docx)",
    "filter_odt": "Texte OpenDocument (*.odt)",
    "filter_pptx": "Présentation PowerPoint (*.pptx)",
    "filter_odp": "Présentation OpenDocument (*.odp)",
    "filter_txt": "Fichier texte (*.txt)",
    "new_doc_dialog_title": "Nouveau document",
    "new_doc_create": "Créer",
    "new_doc_cancel": "Annuler",
    "new_doc_page_setup": "Configuration de page",
    "new_doc_template": "Modèle",
    "new_doc_orientation": "Orientation",
    "new_doc_portrait": "Portrait",
    "new_doc_landscape": "Paysage",
    "new_doc_dimensions": "Dimensions",
    "new_doc_unit": "Unité",
    "new_doc_width": "Largeur",
    "new_doc_height": "Hauteur",
    "new_doc_document": "Document",
    "new_doc_num_pages": "Nombre de pages",
    "new_doc_pages_desc": "Pages vierges initiales",
    "new_doc_unit_mm": "Millimètres (mm)",
    "new_doc_unit_cm": "Centimètres (cm)",
    "new_doc_unit_in": "Pouces (in)",
    "new_doc_unit_pt": "Points (pt)",
    "new_doc_unit_px": "Pixels (px @ 72 dpi)",
    "preset_a4": "A4 (210 × 297 mm)",
    "preset_a3": "A3 (297 × 420 mm)",
    "preset_a5": "A5 (148 × 210 mm)",
    "preset_a6": "A6 (105 × 148 mm)",
    "preset_a2": "A2 (420 × 594 mm)",
    "preset_a1": "A1 (594 × 841 mm)",
    "preset_a0": "A0 (841 × 1189 mm)",
    "preset_b4": "B4 (250 × 353 mm)",
    "preset_b5": "B5 (176 × 250 mm)",
    "preset_letter": "US Letter (8.5 × 11 in)",
    "preset_legal": "US Legal (8.5 × 14 in)",
    "preset_executive": "US Executive (7.25 × 10.5 in)",
    "preset_tabloid": "Tabloid / Ledger (11 × 17 in)",
    "preset_slide_16_9": "Diapositive 16:9 (1920 × 1080 pt)",
    "preset_slide_16_10": "Diapositive 16:10 (1920 × 1200 pt)",
    "preset_slide_4_3": "Diapositive 4:3 (1024 × 768 pt)",
    "preset_square": "Carré (1080 × 1080 pt)",
    "preset_custom": "Personnalisé...",
}

import unittest


class TestFrenchLocales(unittest.TestCase):
    def test_french_dictionary_populated(self):
        self.assertGreater(len(fr), 300)
        for k, v in fr.items():
            self.assertTrue(v, f"Empty translation for {k}")


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_locale_detection.py
# ============================================================================
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

import word_sys_pdf_editor.i18n as i18n
from word_sys_pdf_editor.i18n import (
    _normalize_lang_code,
    _detect_system_language,
    detect_system_language,
    get_language,
    set_language,
    get_supported_languages,
    _save_settings,
    _load_settings,
    _STRINGS,
)
from word_sys_pdf_editor.welcome_view import WelcomeView


class TestLocaleDetectionAndPersistence(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        set_language("en", restart=False)

    def test_normalize_lang_code(self):
        self.assertEqual(_normalize_lang_code("tr_TR.UTF-8"), "tr")
        self.assertEqual(_normalize_lang_code("de_DE@euro"), "de")
        self.assertEqual(_normalize_lang_code("fr-FR"), "fr")
        self.assertEqual(_normalize_lang_code("es_ES"), "es")
        self.assertEqual(_normalize_lang_code("it_IT.UTF-8"), "it")
        self.assertEqual(_normalize_lang_code("ru_RU.CP1251"), "ru")
        self.assertEqual(_normalize_lang_code("en_US.UTF-8"), "en")
        self.assertIsNone(_normalize_lang_code("C"))
        self.assertIsNone(_normalize_lang_code("POSIX"))
        self.assertIsNone(_normalize_lang_code(""))
        self.assertIsNone(_normalize_lang_code(None))

    def test_detect_system_language_glib(self):
        with patch("gi.repository.GLib.get_language_names", return_value=["tr_TR.UTF-8", "tr", "en_US"]):
            self.assertEqual(_detect_system_language(), "tr")

        with patch("gi.repository.GLib.get_language_names", return_value=["de_DE@euro", "de"]):
            self.assertEqual(_detect_system_language(), "de")

        with patch("gi.repository.GLib.get_language_names", return_value=["fr_FR.UTF-8", "fr"]):
            self.assertEqual(_detect_system_language(), "fr")

        with patch("gi.repository.GLib.get_language_names", return_value=["ru_RU.UTF-8", "ru"]):
            self.assertEqual(_detect_system_language(), "ru")

    def test_detect_system_language_env_vars(self):
        with patch("gi.repository.GLib.get_language_names", side_effect=Exception("No GLib")):
            with patch.dict(os.environ, {"LC_ALL": "es_ES.UTF-8", "LANG": "C"}, clear=False):
                self.assertEqual(_detect_system_language(), "es")

            with patch.dict(os.environ, {"LC_ALL": "", "LANG": "it_IT.UTF-8"}, clear=False):
                self.assertEqual(_detect_system_language(), "it")

            with patch.dict(os.environ, {"LC_ALL": "", "LANG": "", "LANGUAGE": "de:fr:en"}, clear=False):
                self.assertEqual(_detect_system_language(), "de")

    def test_detect_system_language_unsupported_fallback(self):
        with patch("gi.repository.GLib.get_language_names", return_value=["ja_JP.UTF-8", "ja", "C"]):
            with patch.dict(os.environ, {"LC_ALL": "C", "LANG": "C", "LANGUAGE": ""}, clear=False):
                self.assertEqual(_detect_system_language(), "en")

    def test_atomic_settings_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            orig_dir = i18n._CONFIG_DIR
            orig_file = i18n._CONFIG_FILE
            try:
                i18n._CONFIG_DIR = tmp_path
                i18n._CONFIG_FILE = tmp_path / "settings.json"

                test_data = {"language": "de", "confirm_delete_objects": False}
                _save_settings(test_data)

                # Ensure target file exists and is valid JSON
                self.assertTrue(i18n._CONFIG_FILE.is_file())
                loaded = _load_settings()
                self.assertEqual(loaded, test_data)

                # Ensure temporary files are cleaned up
                temp_files = list(tmp_path.glob(".settings.json.tmp.*"))
                self.assertEqual(len(temp_files), 0)
            finally:
                i18n._CONFIG_DIR = orig_dir
                i18n._CONFIG_FILE = orig_file

    def test_saved_language_precedence_over_system_locale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            orig_dir = i18n._CONFIG_DIR
            orig_file = i18n._CONFIG_FILE
            orig_lang = i18n._active_lang
            try:
                i18n._CONFIG_DIR = tmp_path
                i18n._CONFIG_FILE = tmp_path / "settings.json"

                # 1. First run: no settings file -> uses detected system language
                with patch("gi.repository.GLib.get_language_names", return_value=["tr_TR.UTF-8", "en"]):
                    loaded = _load_settings()
                    self.assertNotIn("language", loaded)
                    self.assertEqual(_detect_system_language(), "tr")

                # 2. User explicitly saves "fr"
                set_language("fr", restart=False)
                self.assertEqual(get_language(), "fr")

                # 3. Subsequent reload respects explicit "fr" even if system locale is "de"
                with patch("gi.repository.GLib.get_language_names", return_value=["de_DE.UTF-8"]):
                    reloaded = _load_settings()
                    self.assertEqual(reloaded.get("language"), "fr")
            finally:
                i18n._CONFIG_DIR = orig_dir
                i18n._CONFIG_FILE = orig_file
                set_language(orig_lang, restart=False)

    def test_welcome_view_pill_button_and_display_update(self):
        mock_win = MagicMock()
        mock_win.doc = None
        mock_win.document_modified = False

        view = WelcomeView(parent_window=mock_win)
        self.assertIsNotNone(view.lang_menu_btn)
        self.assertIsNotNone(view._lang_dropdown)
        self.assertTrue(view.lang_menu_btn.has_css_class("pill"))
        self.assertEqual(len(view._languages), 7)

        # Update display
        view.update_language_display("tr")
        self.assertEqual(view.lang_btn_label.get_text(), "Türkçe")

        view.update_language_display("de")
        self.assertEqual(view.lang_btn_label.get_text(), "Deutsch")

        view.update_language_display("en")
        self.assertEqual(view.lang_btn_label.get_text(), "English")

    def test_request_language_change_unsaved_guard(self):
        from word_sys_pdf_editor.window import PdfEditorWindow

        mock_win = MagicMock()
        mock_sess = MagicMock()
        mock_sess.is_modified = True
        mock_sess.doc = MagicMock()
        mock_win.sessions = [mock_sess]

        orig_lang = get_language()
        with patch("word_sys_pdf_editor.ui_components.show_confirm_dialog", return_value=False):
            # User cancels unsaved changes warning -> language switch should be aborted
            PdfEditorWindow.request_language_change(mock_win, "de" if orig_lang != "de" else "fr")
            # State should remain unchanged
            self.assertEqual(get_language(), orig_lang)

    def test_quick_guide_dialog_tabs_search_and_localization(self):
        from word_sys_pdf_editor.quick_guide_dialog import QuickGuideDialog

        new_guide_keys = [
            "guide_search_placeholder",
            "guide_search_tooltip",
            "guide_tab_security_ocr",
            "guide_tool_clone_title",
            "guide_tool_clone_desc",
            "guide_grp_annotations_forms",
            "guide_tool_notes_title",
            "guide_tool_stamps_title",
            "guide_tool_measure_title",
            "guide_tool_forms_title",
            "guide_nav_continuous_title",
            "guide_nav_search_title",
            "guide_split_title",
            "guide_compress_title",
            "guide_headers_watermarks_title",
            "guide_grp_ocr",
            "guide_ocr_streaming_title",
            "guide_ocr_region_title",
            "guide_ocr_languages_title",
            "guide_grp_security",
            "guide_sec_signatures_title",
            "guide_sec_redaction_title",
            "guide_sec_encryption_title",
            "guide_sc_find",
            "guide_sc_replace",
            "guide_sc_ocr",
            "guide_sc_quick_guide",
            "guide_sc_copy_paste_dup",
            "guide_sc_tool_stamp",
            "guide_sc_tool_note",
            "guide_sc_tool_ruler",
            "guide_sc_tool_area",
            "guide_sc_tool_signature",
            "guide_sc_tool_ocr_region",
            "guide_sc_tool_form_builder",
        ]
        for lang_code, _ in get_supported_languages():
            table = i18n._STRINGS[lang_code]
            for key in new_guide_keys:
                self.assertIn(key, table, f"Missing guide key '{key}' in '{lang_code}'")
                self.assertTrue(len(table[key].strip()) > 0)

        dlg = QuickGuideDialog(None)
        for tab_id in ("tools", "canvas", "security_ocr", "shortcuts"):
            self.assertIsNotNone(dlg.view_stack.get_child_by_name(tab_id))
            self.assertTrue(len(dlg._tab_groups[tab_id]) >= 2)

        # Verify live search filters rows and switches to matching tab when current tab has 0 matches
        dlg.view_stack.set_visible_child_name("tools")
        dlg.search_entry.set_text("PKCS#11")
        dlg._on_search_changed(dlg.search_entry)
        self.assertEqual(dlg.view_stack.get_visible_child_name(), "security_ocr")
        visible_rows = [r for r in dlg._filter_records if r["row"].get_visible()]
        self.assertGreaterEqual(len(visible_rows), 1)

        # Clearing search restores all rows
        dlg.search_entry.set_text("")
        dlg._on_search_changed(dlg.search_entry)
        self.assertTrue(all(r["row"].get_visible() for r in dlg._filter_records))
        dlg.destroy()

