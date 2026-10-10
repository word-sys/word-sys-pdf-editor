import copy
from typing import Optional, List, Dict, Tuple, Any
from .undo_manager import UndoManager, EditObjectCommand, AddObjectCommand, DeleteObjectCommand, RotatePageCommand, RotateObjectCommand, EditFormFieldCommand, AddFormFieldCommand, DeleteFormFieldCommand, MoveResizeFormFieldCommand, EditFormFieldChoicesCommand, ReplaceImageCommand, CalibrateScaleCommand
from .i18n import _, get_language, get_setting, set_setting

import gi
import os
from pathlib import Path
import cairo
import threading
import math
import re
try:
    import pymupdf as fitz
except ImportError:
    import fitz

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib, Adw, Gdk, GdkPixbuf, Pango, GObject, PangoCairo

from . import constants
from . import pdf_handler
from . import print_handler
from .welcome_view import WelcomeView
from .models import PdfPage, EditableText, BASE14_FALLBACK_MAP, EditableImage, EditableShape, EditableStroke, DocumentSession, AcroFormField, ScaleCalibration, PRESET_SCALES
from .ui_components import (
    PageThumbnailFactory, show_error_dialog, show_confirm_dialog,
    show_save_changes_dialog, show_open_file_dialog, show_save_file_dialog,
    SymbolsPopover, render_emoji_to_png_bytes, show_new_document_dialog
)
from .quick_guide_dialog import QuickGuideDialog
from . import utils

class PdfEditorWindow(Adw.ApplicationWindow):
    """Main application window providing PDF viewing, editing, annotation, and exporting capabilities."""
    _active_session = None
    sessions = None
    tab_view = None
    tab_bar = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_title(constants.APP_NAME)
        self.set_default_size(1200, 800)
        self.set_icon_name("f-pv1")

        self.sessions = []
        self._active_session = DocumentSession(undo_manager=UndoManager(self))
        self.sessions.append(self._active_session)
        self.tab_view = None
        self.tab_bar = None
        self._is_switching_tabs = False

        self.current_file_path = None
        self.original_file_path = None
        self.allow_incremental_save = True
        self.doc = None 
        self.current_page_index = 0
        self.zoom_level = 1.0
        self._last_pointer_pos = None
        self.pages_model = Gio.ListStore(item_type=PdfPage)
        self.editable_texts = [] 
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.form_fields = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self._form_field_overlay_widgets = {}
        self._enable_persistent_form_overlays = False
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None
        self._active_form_field_initial_val = None
        self._syncing_form_field = False
        self.text_edit_popover = None
        self.text_edit_view = None
        self.is_saving = False
        self.dragged_object = None
        self.drag_start_pos = (0, 0)
        self.drag_object_start_pos = (0, 0)
        self.resize_handle = None  
        self.resize_start_bbox = None  
        self.dragging_to_create = False  
        self.temp_shape = None  
        self.temp_stroke = None
        self.temp_image_bbox = None  
        self.temp_image_path = None  
        self.drag_start_page_pos = None  
        self.next_shape_fill = (255, 255, 255)
        self.next_shape_stroke = (0, 0, 0)
        self.next_shape_stroke_width = 2.0
        self.next_shape_transparent = True
        self.pen_color = (0.0, 0.0, 0.0)
        self.pen_width = 2.0
        self.highlighter_color = (1.0, 0.9, 0.0)
        self.highlighter_width = 14.0
        self.highlighter_opacity = 0.35
        self.document_modified = False 
        self.tool_mode = "select" 
        self.temp_form_field_rect = None
        self.form_builder_field_type = "text"
        self.form_builder_tool_button = None
        self.form_builder_delete_button = None
        self.form_builder_add_label_check = None
        self.form_builder_label_entry = None
        self.form_builder_options_box = None
        self.form_builder_options_entry = None
        self.form_builder_edit_options_btn = None
        self.calibrate_tool_button = None
        self.temp_calibration_line = None
        self.calibration_toolbar_box = None
        self.calibration_scale_label = None
        self.calibration_preset_dropdown = None
        self.calibrate_dialog_btn = None
        self.calibrate_reset_btn = None
        self._updating_form_builder_ui = False
        self._active_editing_form_field = None
        self.current_pdf_page_width = 0
        self.current_pdf_page_height = 0
        self.bold_button = None
        self.italic_button = None
        self.font_scan_in_progress = True
        self.undo_manager = UndoManager(self)
        self.pending_format_change_obj = None
        self.before_format_change_state = None
        self.is_repaired_file = False
        self._last_font_family = None
        self._last_font_size = 11.0
        self._last_is_bold = False
        self._last_is_italic = False
        self._last_is_strikethrough = False
        self._last_alignment = 'left'
        self._last_color = (0.0, 0.0, 0.0)

        self.view_mode = True
        self.view_sel_start = None
        self.view_sel_rect = None
        self.view_selected_text = ""
        self.view_drag_active = False
        
        self.selected_word = None
        self.selected_word_start_char = None
        self.selected_word_end_char = None
        self.word_selection_mode = False

        self.inline_editor_widget = None
        self.inline_editor_text_obj = None

        self._build_ui()
        self._setup_controllers()
        self._connect_actions()
        self._apply_css()
        self._update_ui_state() 

        self.status_label.set_text(_("scan_fonts"))
        utils.scan_system_fonts_async(callback_on_done=self._on_font_scan_complete)

    def _on_font_scan_complete(self):
        """Callback when background system font scan finishes, populating font combo."""
        self.font_scan_in_progress = False
        utils.get_default_unicode_font_path()
        self._populate_font_combo()

        if not utils.UNICODE_FONT_PATH:
             show_error_dialog(self, _("font_warning_msg"), _("font_warning_title"))

        if not self.doc:
            self.status_label.set_text(_("fonts_loaded_open"))
        elif self.current_file_path:
            self.status_label.set_text(_("loaded").format(os.path.basename(self.current_file_path)))
        else:
            self.status_label.set_text(_("new_doc_loaded"))
        self._update_ui_state()

    def _populate_font_combo(self):
        """Populate font selector dropdown with discovered system fonts."""
        self.font_store.clear() 
        if utils.FONT_FAMILY_LIST_SORTED:
            for family_name in utils.FONT_FAMILY_LIST_SORTED:
                self.font_store.append([family_name, family_name])
            if len(self.font_store) > 0:
                self.font_combo.set_active(0)
            else:
                 self.font_store.append([_("font_none_error"), ""])
                 self.font_combo.set_active(0)
        else:
            self.font_store.append([_("font_none"), ""])
            self.font_combo.set_active(0)
            print("WARNING: utils.FONT_FAMILY_LIST_SORTED is empty.")
        
        self._update_ui_state()

    def _apply_css(self):
        """Apply custom application stylesheet for toolbars, canvas, and popovers."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .toolbar { padding: 6px; }
            .pdf-view { background-color: #6c6c6c; }
            .statusbar { padding: 4px 8px; border-top: 1px solid @borders; background-color: @theme_bg_color; }
            popover > .box { padding: 10px; }

            textview {
                font-family: monospace;
                min-height: 80px;
                margin-bottom: 6px;
                border-radius: 6px;
                border: 1px solid @borders;
                background-color: @theme_bg_color;
                padding: 4px 6px;
            }

            textview.new-text-entry {
                border: 2px solid @accent_color;
                background-color: @popover_bg_color;
            }

            .inline-editor-frame {
                background-color: @card_bg_color;
                border: 1.5px solid @accent_color;
                border-radius: 4px;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
                padding: 0;
                margin: 0;
            }

            .inline-editor-tv {
                min-height: 0px;
                min-width: 0px;
                margin: 0;
                padding: 2px 3px;
                border: none;
                border-radius: 3px;
                background-color: transparent;
            }

            .tool-button.active { background-color: @theme_selected_bg_color; }
            .acroform-entry {
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(53, 132, 228, 0.6);
                border-radius: 3px;
                padding: 1px 4px;
                min-height: 18px;
                color: #111111;
                font-size: 13px;
            }
            .acroform-entry:focus {
                border: 2px solid @accent_color;
                background-color: #ffffff;
            }
            .acroform-entry.readonly {
                background-color: rgba(240, 240, 240, 0.75);
                border: 1px dashed rgba(130, 130, 130, 0.5);
                color: #555555;
            }
            .acroform-frame {
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(53, 132, 228, 0.6);
                border-radius: 3px;
            }
            .acroform-textview {
                background-color: transparent;
                padding: 2px;
                font-family: inherit;
                font-size: 13px;
                color: #111111;
            }
            .acroform-check {
                background: transparent;
                padding: 0;
                margin: 0;
            }
            .acroform-check check {
                min-width: 16px;
                min-height: 16px;
                border: 1.5px solid #333333;
                border-radius: 3px;
                background-color: #ffffff;
            }
            .acroform-check:checked check {
                background-color: @accent_color;
                border-color: @accent_color;
                color: #ffffff;
            }
            .acroform-check.radio check {
                border-radius: 50%;
            }
            .acroform-dropdown {
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(53, 132, 228, 0.6);
                border-radius: 3px;
                min-height: 20px;
                font-size: 13px;
                padding: 0 4px;
                color: #111111;
            }
            .acroform-dropdown:focus {
                border: 2px solid @accent_color;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    @property
    def active_session(self) -> DocumentSession:
        """Get current active DocumentSession."""
        return self._active_session

    @active_session.setter
    def active_session(self, session: DocumentSession):
        """Set active DocumentSession."""
        self.set_active_session(session)

    def set_active_session(self, session: DocumentSession):
        """Switch the active document session with clean state isolation and tab synchronization."""
        if session is None:
            return

        if self._active_session is session:
            if hasattr(self, 'stack') and self.stack and session.doc is not None:
                self.stack.set_visible_child_name("editor")
                self.set_title(f"{constants.APP_NAME} - {session.display_title}")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
            # Ensure paned is parented correctly even if session unchanged
            if getattr(session, 'bin_widget', None) and hasattr(self, 'paned'):
                if self.paned.get_parent() != session.bin_widget:
                    old_parent = self.paned.get_parent()
                    if old_parent:
                        old_parent.set_child(None)
                    session.bin_widget.set_child(self.paned)
            return

        if self._active_session and self._active_session.doc:
            try:
                self.commit_pending_format_change()
                if self.inline_editor_widget is not None:
                    self._apply_and_hide_editor(force_apply=True)
                self._clear_form_field_overlays()
                if hasattr(self, 'pdf_scroll') and self.pdf_scroll:
                    v_adj = self.pdf_scroll.get_vadjustment()
                    h_adj = self.pdf_scroll.get_hadjustment()
                    if v_adj:
                        self._active_session.scroll_y = v_adj.get_value()
                    if h_adj:
                        self._active_session.scroll_x = h_adj.get_value()
                pdf_handler.save_page_snapshot(
                    self._active_session.doc,
                    self._active_session.current_page_index,
                    force=True
                )
            except Exception:
                pass

        self._active_session = session
        if session not in self.sessions:
            self.sessions.append(session)

        # Ensure tab exists in TabView
        if hasattr(self, 'tab_view') and self.tab_view:
            if getattr(session, 'tab_page', None) is None:
                self._create_tab_for_session(session)

            self._is_switching_tabs = True
            try:
                if session.tab_page and self.tab_view.get_selected_page() != session.tab_page:
                    self.tab_view.set_selected_page(session.tab_page)
            finally:
                self._is_switching_tabs = False

        # Attach self.paned to active session's bin_widget
        if getattr(session, 'bin_widget', None) is not None and hasattr(self, 'paned'):
            current_parent = self.paned.get_parent()
            if current_parent != session.bin_widget:
                if current_parent:
                    current_parent.set_child(None)
                session.bin_widget.set_child(self.paned)

        if hasattr(self, 'thumbnail_selection_model') and self.thumbnail_selection_model is not None:
            if session.pages_model is not None:
                self._syncing_thumb = True
                try:
                    self.thumbnail_selection_model.set_model(session.pages_model)
                finally:
                    self._syncing_thumb = False

        if session.doc is not None:
            self.set_title(f"{constants.APP_NAME} - {session.display_title}")
            if hasattr(self, 'stack') and self.stack:
                self.stack.set_visible_child_name("editor")
            if hasattr(self, 'tab_bar') and self.tab_bar:
                self.tab_bar.set_autohide(False)
                self.tab_bar.set_visible(True)
            if hasattr(self, 'pdf_scroll'):
                has_objects = bool(session.editable_texts or session.editable_shapes or session.editable_strokes or session.editable_images or session.form_fields or session.is_modified)
                self._load_page(session.current_page_index, reload_objects=(not has_objects))
            if hasattr(self, 'thumbnail_selection_model') and self.thumbnail_selection_model:
                try:
                    self.thumbnail_selection_model.set_selected(session.current_page_index)
                except Exception:
                    pass
            self.update_zoom_label()

            if hasattr(self, 'pdf_scroll') and self.pdf_scroll:
                saved_sx = getattr(session, 'scroll_x', 0.0)
                saved_sy = getattr(session, 'scroll_y', 0.0)
                if saved_sx > 0 or saved_sy > 0:
                    def _restore_tab_scroll(sess=session, sx=saved_sx, sy=saved_sy):
                        if getattr(self, '_active_session', None) == sess and hasattr(self, 'pdf_scroll') and self.pdf_scroll:
                            v = self.pdf_scroll.get_vadjustment()
                            h = self.pdf_scroll.get_hadjustment()
                            if v and sy > 0:
                                max_v = max(0.0, v.get_upper() - v.get_page_size())
                                v.set_value(min(sy, max_v))
                            if h and sx > 0:
                                max_h = max(0.0, h.get_upper() - h.get_page_size())
                                h.set_value(min(sx, max_h))
                        return GLib.SOURCE_REMOVE
                    GLib.idle_add(_restore_tab_scroll)
        else:
            self.set_title(constants.APP_NAME)
            if hasattr(self, 'stack') and self.stack:
                any_docs = any(s.doc is not None for s in self.sessions)
                if not any_docs:
                    self.stack.set_visible_child_name("welcome")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_visible(False)
                        self.tab_bar.set_autohide(True)
                else:
                    self.stack.set_visible_child_name("editor")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_autohide(False)
                        self.tab_bar.set_visible(True)

        self._update_tab_title(session)
        self._update_ui_state()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _create_tab_for_session(self, session: DocumentSession):
        """Create and bind an Adw.TabPage in tab_view for the given DocumentSession."""
        if not hasattr(self, 'tab_view') or self.tab_view is None:
            return None
        if getattr(session, 'tab_page', None) is not None:
            return session.tab_page

        bin_widget = Adw.Bin()
        bin_widget.set_vexpand(True)
        bin_widget.set_hexpand(True)
        page = self.tab_view.append(bin_widget)
        session.tab_page = page
        session.bin_widget = bin_widget

        if hasattr(self, 'paned') and self.paned is not None:
            if session == self._active_session or self.paned.get_parent() is None:
                old_parent = self.paned.get_parent()
                if old_parent:
                    old_parent.set_child(None)
                bin_widget.set_child(self.paned)

        self._update_tab_title(session)
        return page

    def _update_tab_title(self, session: DocumentSession):
        """Sync tab title, tooltip, and dirty indicators for the given session."""
        if not session or not getattr(session, 'tab_page', None):
            return
        try:
            page = session.tab_page
            display_title = session.display_title
            page.set_title(display_title)
            page.set_tooltip(session.pdf_path or _("untitled_document") if "_" in dir() else (session.pdf_path or "Untitled Document"))
            page.set_icon(Gio.ThemedIcon.new("application-pdf-symbolic"))
            page.set_needs_attention(session.is_modified)
        except Exception:
            pass

    def get_session_by_tab_page(self, page) -> Optional[DocumentSession]:
        """Find the DocumentSession associated with the specified Adw.TabPage."""
        if not page or not self.sessions:
            return None
        page_child = page.get_child() if hasattr(page, 'get_child') else None
        for s in self.sessions:
            if getattr(s, 'tab_page', None) == page:
                return s
            if page_child is not None and getattr(s, 'bin_widget', None) == page_child:
                return s
        return None

    def _on_tab_selected_page_changed(self, tab_view, pspec):
        """Handle user tab selection changes from Adw.TabBar or keyboard navigation."""
        if getattr(self, '_is_switching_tabs', False):
            return
        if not hasattr(self, 'tab_view') or self.tab_view is None:
            return
        selected_page = self.tab_view.get_selected_page()
        if not selected_page:
            return
        target_session = self.get_session_by_tab_page(selected_page)
        if target_session:
            if hasattr(self, 'stack') and self.stack and self.stack.get_visible_child_name() == "welcome":
                self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
            if target_session != self._active_session:
                self.set_active_session(target_session)
            elif target_session.doc is not None:
                self.set_title(f"{constants.APP_NAME} - {target_session.display_title}")

    def _on_tab_close_page(self, tab_view, page) -> bool:
        """Handle tab close request, prompting to save unsaved modifications."""
        target_session = self.get_session_by_tab_page(page)
        if target_session:
            if target_session.is_modified:
                self.set_active_session(target_session)
                response = show_save_changes_dialog(self)
                if response == Gtk.ResponseType.ACCEPT:
                    if target_session.pdf_path:
                        self.save_document(target_session.pdf_path, incremental=False)
                    else:
                        self.on_save_as(None, None)
                        if target_session.is_modified:
                            self.tab_view.close_page_finish(page, False)
                            return True
                elif response == Gtk.ResponseType.REJECT:
                    pass
                else:  # Cancel
                    self.tab_view.close_page_finish(page, False)
                    return True

            try:
                page.set_icon(None)
            except Exception:
                pass
            self.tab_view.close_page_finish(page, True)
            target_session.tab_page = None
            self.remove_session(target_session)
            return True

        try:
            page.set_icon(None)
        except Exception:
            pass
        self.tab_view.close_page_finish(page, True)
        return True

    def _on_tab_page_reordered(self, tab_view, page, position):
        """Update internal session list order when user drags and reorders tabs."""
        session = self.get_session_by_tab_page(page)
        if session and session in self.sessions:
            self.sessions.remove(session)
            self.sessions.insert(position, session)

    def _on_tab_extra_drag_drop(self, tab_bar, page, value):
        """Handle dropping a PDF file onto the TabBar to open it in a new tab."""
        if isinstance(value, Gio.File):
            filepath = value.get_path()
            if filepath and filepath.lower().endswith('.pdf'):
                GLib.idle_add(self.load_document, filepath, 0, True)
                return True
        return False

    def create_session(self, doc=None, filepath=None) -> DocumentSession:
        """Create a new DocumentSession configured for this window."""
        session = DocumentSession(
            doc=doc,
            pdf_path=filepath,
            original_file_path=filepath,
            undo_manager=UndoManager(self)
        )
        return session

    def add_session(self, session: DocumentSession, switch_to: bool = True):
        """Add a session to the session pool and create a tab for it."""
        if session not in self.sessions:
            self.sessions.append(session)
        if hasattr(self, 'tab_view') and self.tab_view:
            if getattr(session, 'tab_page', None) is None:
                self._create_tab_for_session(session)
        if switch_to:
            self.set_active_session(session)

    def remove_session(self, session_or_id):
        """Remove a session from the session pool, close its tab, and cleanly close it."""
        target_session = None
        if isinstance(session_or_id, DocumentSession):
            target_session = session_or_id
        elif isinstance(session_or_id, str):
            target_session = self.get_session_by_id(session_or_id)

        if not target_session or target_session not in self.sessions:
            return

        self.sessions.remove(target_session)

        if hasattr(self, 'paned') and self.paned.get_parent() == getattr(target_session, 'bin_widget', None):
            if target_session.bin_widget:
                target_session.bin_widget.set_child(None)

        if hasattr(self, 'tab_view') and self.tab_view and getattr(target_session, 'tab_page', None):
            page = target_session.tab_page
            target_session.tab_page = None
            try:
                page.set_icon(None)
                self.tab_view.close_page(page)
            except Exception:
                pass

        target_session.close()

        if getattr(self, '_is_closing', False):
            return

        if self._active_session == target_session or self._active_session not in self.sessions:
            selected_page = self.tab_view.get_selected_page() if hasattr(self, 'tab_view') and self.tab_view else None
            candidate = self.get_session_by_tab_page(selected_page) if selected_page else None
            if candidate and candidate != target_session and candidate in self.sessions:
                self.set_active_session(candidate)
            else:
                remaining_with_doc = [s for s in self.sessions if s.doc is not None]
                if remaining_with_doc:
                    self.set_active_session(remaining_with_doc[-1])
                elif self.sessions:
                    self.set_active_session(self.sessions[-1])
                else:
                    new_session = self.create_session()
                    self._active_session = new_session
                    self.sessions = [new_session]
                    if hasattr(self, 'tab_view') and self.tab_view:
                        self._create_tab_for_session(new_session)
                    self.close_document()
                    if hasattr(self, 'stack') and self.stack:
                        self.stack.set_visible_child_name("welcome")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_visible(False)

    def get_session_by_id(self, session_id: str):
        """Retrieve session by UUID."""
        for s in self.sessions:
            if s.session_id == session_id:
                return s
        return None

    def get_session_by_path(self, filepath: str):
        """Retrieve session by canonical file path."""
        if not filepath:
            return None
        try:
            norm_target = os.path.realpath(filepath)
        except Exception:
            norm_target = filepath
        for s in self.sessions:
            if s.pdf_path:
                try:
                    if os.path.realpath(s.pdf_path) == norm_target:
                        return s
                except Exception:
                    if s.pdf_path == filepath:
                        return s
        return None

    @property
    def doc(self):
        """Active document object."""
        return self._active_session.doc if self._active_session else None

    @doc.setter
    def doc(self, val):
        if self._active_session:
            self._active_session.doc = val

    @property
    def current_file_path(self):
        """Active document file path."""
        return self._active_session.pdf_path if self._active_session else None

    @current_file_path.setter
    def current_file_path(self, val):
        if self._active_session:
            self._active_session.pdf_path = val
            self._update_tab_title(self._active_session)

    @property
    def original_file_path(self):
        """Active document original file path."""
        return self._active_session.original_file_path if self._active_session else None

    @original_file_path.setter
    def original_file_path(self, val):
        if self._active_session:
            self._active_session.original_file_path = val

    @property
    def current_page_index(self):
        """Active document current page index."""
        return self._active_session.current_page_index if self._active_session else 0

    @current_page_index.setter
    def current_page_index(self, val):
        if self._active_session:
            self._active_session.current_page_index = val

    @property
    def zoom_level(self):
        """Active document zoom level."""
        return self._active_session.zoom_level if self._active_session else 1.0

    @zoom_level.setter
    def zoom_level(self, val):
        if self._active_session:
            self._active_session.zoom_level = val

    @property
    def view_mode(self):
        """Active document view mode flag."""
        return self._active_session.view_mode if self._active_session else True

    @view_mode.setter
    def view_mode(self, val):
        if self._active_session:
            self._active_session.view_mode = val

    @property
    def document_modified(self):
        """Active document modified flag."""
        return self._active_session.is_modified if self._active_session else False

    @document_modified.setter
    def document_modified(self, val):
        if self._active_session:
            self._active_session.is_modified = val
            self._update_tab_title(self._active_session)
            if val and hasattr(self, 'get_title'):
                title = self.get_title()
                if not title.endswith("*"):
                    self.set_title(title + "*")
            elif not val and hasattr(self, 'get_title'):
                title = self.get_title()
                if title.endswith("*"):
                    self.set_title(title[:-1])

    @property
    def allow_incremental_save(self):
        """Active document allow incremental save flag."""
        return self._active_session.allow_incremental_save if self._active_session else True

    @allow_incremental_save.setter
    def allow_incremental_save(self, val):
        if self._active_session:
            self._active_session.allow_incremental_save = val

    @property
    def is_repaired_file(self):
        """Active document repaired file flag."""
        return self._active_session.is_repaired_file if self._active_session else False

    @is_repaired_file.setter
    def is_repaired_file(self, val):
        if self._active_session:
            self._active_session.is_repaired_file = val

    @property
    def undo_manager(self):
        """Active document undo manager."""
        return self._active_session.undo_manager if self._active_session else None

    @undo_manager.setter
    def undo_manager(self, val):
        if self._active_session:
            self._active_session.undo_manager = val

    @property
    def pages_model(self):
        """Active document pages model."""
        return self._active_session.pages_model if self._active_session else None

    @pages_model.setter
    def pages_model(self, val):
        if self._active_session:
            self._active_session.pages_model = val

    @property
    def editable_texts(self):
        """Active document editable texts list."""
        return self._active_session.editable_texts if self._active_session else []

    @editable_texts.setter
    def editable_texts(self, val):
        if self._active_session:
            self._active_session.editable_texts = val

    @property
    def editable_images(self):
        """Active document editable images list."""
        return self._active_session.editable_images if self._active_session else []

    @editable_images.setter
    def editable_images(self, val):
        if self._active_session:
            self._active_session.editable_images = val

    @property
    def editable_shapes(self):
        """Active document editable shapes list."""
        return self._active_session.editable_shapes if self._active_session else []

    @editable_shapes.setter
    def editable_shapes(self, val):
        if self._active_session:
            self._active_session.editable_shapes = val

    @property
    def editable_strokes(self):
        """Active document editable strokes list."""
        return self._active_session.editable_strokes if self._active_session else []

    @editable_strokes.setter
    def editable_strokes(self, val):
        if self._active_session:
            self._active_session.editable_strokes = val

    @property
    def form_fields(self):
        """Active document interactive AcroForm fields."""
        return self._active_session.form_fields if self._active_session else []

    @form_fields.setter
    def form_fields(self, val):
        if self._active_session:
            self._active_session.form_fields = val

    @property
    def selected_text(self):
        """Active document selected text."""
        return self._active_session.selected_text if self._active_session else None

    @selected_text.setter
    def selected_text(self, val):
        if self._active_session:
            self._active_session.selected_text = val

    @property
    def selected_image(self):
        """Active document selected image."""
        return self._active_session.selected_image if self._active_session else None

    @selected_image.setter
    def selected_image(self, val):
        if self._active_session:
            self._active_session.selected_image = val

    @property
    def selected_shape(self):
        """Active document selected shape."""
        return self._active_session.selected_shape if self._active_session else None

    @selected_shape.setter
    def selected_shape(self, val):
        if self._active_session:
            self._active_session.selected_shape = val

    @property
    def selected_stroke(self):
        """Active document selected stroke."""
        return self._active_session.selected_stroke if self._active_session else None

    @selected_stroke.setter
    def selected_stroke(self, val):
        if self._active_session:
            self._active_session.selected_stroke = val

    @property
    def selected_form_field(self):
        """Active document selected form field."""
        return self._active_session.selected_form_field if self._active_session else None

    @selected_form_field.setter
    def selected_form_field(self, val):
        if self._active_session:
            self._active_session.selected_form_field = val

    @property
    def view_sel_start(self):
        """Active document view mode selection start."""
        return self._active_session.view_sel_start if self._active_session else None

    @view_sel_start.setter
    def view_sel_start(self, val):
        if self._active_session:
            self._active_session.view_sel_start = val

    @property
    def view_sel_rect(self):
        """Active document view mode selection rectangle."""
        return self._active_session.view_sel_rect if self._active_session else None

    @view_sel_rect.setter
    def view_sel_rect(self, val):
        if self._active_session:
            self._active_session.view_sel_rect = val

    @property
    def view_selected_text(self):
        """Active document view mode selected text."""
        return self._active_session.view_selected_text if self._active_session else ""

    @view_selected_text.setter
    def view_selected_text(self, val):
        if self._active_session:
            self._active_session.view_selected_text = val

    @property
    def view_drag_active(self):
        """Active document view drag active flag."""
        return self._active_session.view_drag_active if self._active_session else False

    @view_drag_active.setter
    def view_drag_active(self, val):
        if self._active_session:
            self._active_session.view_drag_active = val

    @property
    def selected_word(self):
        """Active document selected word."""
        return self._active_session.selected_word if self._active_session else None

    @selected_word.setter
    def selected_word(self, val):
        if self._active_session:
            self._active_session.selected_word = val

    @property
    def selected_word_start_char(self):
        """Active document selected word start char index."""
        return self._active_session.selected_word_start_char if self._active_session else None

    @selected_word_start_char.setter
    def selected_word_start_char(self, val):
        if self._active_session:
            self._active_session.selected_word_start_char = val

    @property
    def selected_word_end_char(self):
        """Active document selected word end char index."""
        return self._active_session.selected_word_end_char if self._active_session else None

    @selected_word_end_char.setter
    def selected_word_end_char(self, val):
        if self._active_session:
            self._active_session.selected_word_end_char = val

    @property
    def word_selection_mode(self):
        """Active document word selection mode flag."""
        return self._active_session.word_selection_mode if self._active_session else False

    @word_selection_mode.setter
    def word_selection_mode(self, val):
        if self._active_session:
            self._active_session.word_selection_mode = val

    @property
    def scale_calibration(self):
        """Active document scale calibration."""
        return self._active_session.scale_calibration if self._active_session else None

    @scale_calibration.setter
    def scale_calibration(self, val):
        if self._active_session:
            self._active_session.scale_calibration = val

    def _build_ui(self):
        """Build UI."""
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)

        header = Adw.HeaderBar()
        self.main_box.append(header)

        self.new_button = Gtk.Button(label=_("btn_new_doc"))
        self.new_button.set_tooltip_text(f"{_('btn_new_doc')} (Ctrl+N)")
        self.new_button.connect("clicked", self.on_new_clicked)
        header.pack_start(self.new_button)

        self.open_button = Gtk.Button(label=_("btn_open_doc"))
        self.open_button.set_tooltip_text(f"{_('btn_open_doc')} (Ctrl+O)")
        self.open_button.connect("clicked", self.on_open_clicked)
        header.pack_start(self.open_button)

        save_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        save_button_box.get_style_context().add_class("linked")

        self.save_button = Gtk.Button(label=_("btn_save"))
        self.save_button.get_style_context().add_class("suggested-action")
        self.save_button.connect("clicked", self.on_save_clicked)
        save_button_box.append(self.save_button)

        header.pack_start(save_button_box)

        self.undo_button = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        self.undo_button.set_tooltip_text(_("undo_tip"))
        self.undo_button.connect("clicked", lambda w: self.undo_manager.undo())
        header.pack_start(self.undo_button)

        self.redo_button = Gtk.Button.new_from_icon_name("edit-redo-symbolic")
        self.redo_button.set_tooltip_text(_("redo_tip"))
        self.redo_button.connect("clicked", lambda w: self.undo_manager.redo())
        header.pack_start(self.redo_button)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        header.pack_end(menu_button)

        self.home_button = Gtk.Button.new_from_icon_name("go-home-symbolic")
        self.home_button.set_tooltip_text(_("home_button_tip"))
        self.home_button.connect("clicked", lambda w: self.go_to_welcome())
        self.home_button.add_css_class("flat")
        header.pack_end(self.home_button)
        self.print_button = Gtk.Button.new_from_icon_name("printer-symbolic")
        self.print_button.set_tooltip_text(_("print_tip"))
        self.print_button.connect("clicked", lambda w: self.on_print_activated(None, None))
        header.pack_end(self.print_button)

        self.mode_toggle_button = Gtk.Button(label=_("mode_edit"))
        self.mode_toggle_button.set_tooltip_text(_("mode_toggle_tip"))
        self.mode_toggle_button.get_style_context().add_class("suggested-action")
        self.mode_toggle_button.connect("clicked", self._toggle_view_edit_mode)
        header.pack_end(self.mode_toggle_button)
        menu = Gio.Menu()
        menu.append(_("menu_save_as"), "win.save_as")
        menu.append(_("menu_merge_documents"), "win.merge_documents")

        export_menu = Gio.Menu()
        export_menu.append(_("menu_export_as"), "win.export_as")
        export_formats_section = Gio.Menu()
        export_formats_section.append(_("export_format_docx"), "win.export_docx")
        export_formats_section.append(_("export_format_pptx"), "win.export_pptx")
        export_formats_section.append(_("export_format_odt"), "win.export_odt")
        export_formats_section.append(_("export_format_odp"), "win.export_odp")
        export_formats_section.append(_("export_format_txt"), "win.export_txt")
        export_menu.append_section(None, export_formats_section)
        menu.append_submenu(_("menu_export"), export_menu)
        
        pref_section = Gio.Menu()
        pref_section.append(_("menu_confirm_delete"), "win.confirm_delete")
        menu.append_section(None, pref_section)

        menu.append_section(None, Gio.Menu())
        menu.append(_("menu_quick_guide"), "win.quick_guide")
        menu.append(_("menu_about"), "win.about")
        menu.append(_("menu_quit"), "app.quit")
        popover_menu = Gtk.PopoverMenu.new_from_model(menu)
        menu_button.set_popover(popover_menu)

        self.tab_view = Adw.TabView()
        self.tab_bar = Adw.TabBar()
        self.tab_bar.set_view(self.tab_view)
        self.tab_bar.set_autohide(True)
        self.tab_bar.set_visible(False)

        new_tab_btn = Gtk.Button.new_from_icon_name("tab-new-symbolic")
        new_tab_btn.add_css_class("flat")
        new_tab_btn.set_tooltip_text(_("btn_new_doc"))
        new_tab_btn.connect("clicked", lambda b: self.on_new_clicked())
        self.tab_bar.set_end_action_widget(new_tab_btn)

        try:
            self.tab_bar.setup_extra_drop_target(Gdk.DragAction.COPY, [Gio.File])
            self.tab_bar.connect("extra-drag-drop", self._on_tab_extra_drag_drop)
        except Exception:
            pass

        self.tab_view.connect("notify::selected-page", self._on_tab_selected_page_changed)
        self.tab_view.connect("close-page", self._on_tab_close_page)
        self.tab_view.connect("page-reordered", self._on_tab_page_reordered)

        tab_click = Gtk.GestureClick.new()
        tab_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        tab_click.connect("pressed", self._on_tab_bar_pressed)
        self.tab_bar.add_controller(tab_click)

        self.main_box.append(self.tab_bar)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_box.append(self.stack)

        welcome_view = WelcomeView(parent_window=self)
        self.stack.add_named(welcome_view, "welcome")

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True, vexpand=True, shrink_start_child=False)
        
        self._create_sidebar()

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, vexpand=True)
        self._create_main_toolbar()
        content_box.append(self.main_toolbar)
        
        self.pdf_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True,
                                            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        self.pdf_view = Gtk.DrawingArea(content_width=1, content_height=1,
                                        hexpand=True, vexpand=True)
        self.pdf_view.set_draw_func(self.draw_pdf_page)
        self.pdf_view.add_css_class('pdf-view')
        self.pdf_view.set_focusable(True)
        self.pdf_view.connect("notify::allocated-width", lambda *a: self._update_form_field_overlay_positions())
        self.pdf_view.connect("notify::allocated-height", lambda *a: self._update_form_field_overlay_positions())

        self.pdf_overlay = Gtk.Overlay()
        self.pdf_overlay.set_child(self.pdf_view)

        self.pdf_viewport = Gtk.Viewport()
        self.pdf_viewport.set_child(self.pdf_overlay)
        self.pdf_scroll.set_child(self.pdf_viewport)
        
        content_box.append(self.pdf_scroll)

        self.paned.set_end_child(content_box)
        self.paned.set_position(200)

        self.stack.add_named(self.tab_view, "editor")

        if self._active_session:
            self._create_tab_for_session(self._active_session)
            if getattr(self._active_session, 'bin_widget', None) is not None:
                if self.paned.get_parent() != self._active_session.bin_widget:
                    old_parent = self.paned.get_parent()
                    if old_parent:
                        old_parent.set_child(None)
                    self._active_session.bin_widget.set_child(self.paned)

        status_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, vexpand=False)
        status_bar_box.add_css_class('statusbar')
        self.status_label = Gtk.Label(label=_('new_doc_loaded'), xalign=0.0)
        status_bar_box.append(self.status_label)
        self.main_box.append(status_bar_box)

    def _create_sidebar(self):
        """Create sidebar."""
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                            margin_start=6, margin_end=6, margin_top=10, margin_bottom=6)
        sidebar_box.set_size_request(190, -1)

        tools_label = Gtk.Label(label=_("tools"), xalign=0.0)
        tools_label.add_css_class('title-4')
        sidebar_box.append(tools_label)

        tools_grid = Gtk.Grid(
            row_spacing=6, 
            column_spacing=6,
            column_homogeneous=True
        )
        
        def _make_tool_btn(icon_name, label_text, tooltip, tool_id):
            btn = Gtk.Button()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_halign(Gtk.Align.CENTER)
            img = Gtk.Image.new_from_icon_name(icon_name)
            lbl = Gtk.Label(label=label_text)
            box.append(img)
            box.append(lbl)
            btn.set_child(box)
            btn.set_tooltip_text(tooltip)
            btn.add_css_class("tool-button")
            btn.connect('clicked', self.on_tool_selected, tool_id)
            return btn

        self.select_tool_button = _make_tool_btn("input-mouse-symbolic", _("tool_select"), _("tool_select_tip"), "select")
        tools_grid.attach(self.select_tool_button, 0, 0, 1, 1)

        self.add_text_tool_button = _make_tool_btn("insert-text-symbolic", _("tool_add_text"), _("tool_add_text_tip"), "add_text")
        tools_grid.attach(self.add_text_tool_button, 1, 0, 1, 1)

        self.add_image_tool_button = _make_tool_btn("insert-image-symbolic", _("tool_add_image"), _("tool_add_image_tip"), "add_image")
        tools_grid.attach(self.add_image_tool_button, 0, 1, 1, 1)

        self.drag_tool_button = _make_tool_btn("drag-handle-symbolic", _("tool_drag"), _("tool_drag_tip"), "drag")
        tools_grid.attach(self.drag_tool_button, 1, 1, 1, 1)

        self.add_ellipse_tool_button = _make_tool_btn("media-record-symbolic", _("tool_ellipse"), _("tool_ellipse_tip"), "add_ellipse")
        tools_grid.attach(self.add_ellipse_tool_button, 0, 2, 1, 1)

        self.add_rectangle_tool_button = _make_tool_btn("checkbox-symbolic", _("tool_rectangle"), _("tool_rectangle_tip"), "add_rectangle")
        tools_grid.attach(self.add_rectangle_tool_button, 1, 2, 1, 1)

        self.pen_tool_button = _make_tool_btn("document-edit-symbolic", _("tool_pen"), _("tool_pen_tip"), "pen")
        tools_grid.attach(self.pen_tool_button, 0, 3, 1, 1)

        self.highlighter_tool_button = _make_tool_btn("marker-symbolic", _("tool_highlighter"), _("tool_highlighter_tip"), "highlighter")
        tools_grid.attach(self.highlighter_tool_button, 1, 3, 1, 1)

        self.checkmark_tool_button = _make_tool_btn("emblem-ok-symbolic", _("tool_checkmark"), _("tool_checkmark_tip"), "add_checkmark")
        tools_grid.attach(self.checkmark_tool_button, 0, 4, 1, 1)

        self.cross_tool_button = _make_tool_btn("window-close-symbolic", _("tool_cross"), _("tool_cross_tip"), "add_cross")
        tools_grid.attach(self.cross_tool_button, 1, 4, 1, 1)

        self.form_builder_tool_button = _make_tool_btn("edit-select-all-symbolic", _("tool_form_builder"), _("tool_form_builder_tip"), "form_builder")
        tools_grid.attach(self.form_builder_tool_button, 0, 5, 2, 1)

        self.calibrate_tool_button = _make_tool_btn("applications-engineering-symbolic", _("tool_calibrate"), _("tool_calibrate_tip"), "calibrate")
        tools_grid.attach(self.calibrate_tool_button, 0, 6, 2, 1)
        
        sidebar_box.append(tools_grid)

        sidebar_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=6, margin_bottom=6))

        pages_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        thumbnails_label = Gtk.Label(label=_("pages_label"), xalign=0.0, hexpand=True)
        thumbnails_label.add_css_class('title-4')
        pages_header.append(thumbnails_label)

        self.rotate_page_ccw_button = Gtk.Button.new_from_icon_name("object-rotate-left-symbolic")
        self.rotate_page_ccw_button.set_tooltip_text(_("rotate_page_ccw_tip"))
        self.rotate_page_ccw_button.connect('clicked', lambda b: self.rotate_current_page(-90))
        self.rotate_page_ccw_button.add_css_class('flat')
        pages_header.append(self.rotate_page_ccw_button)

        self.rotate_page_cw_button = Gtk.Button.new_from_icon_name("object-rotate-right-symbolic")
        self.rotate_page_cw_button.set_tooltip_text(_("rotate_page_cw_tip"))
        self.rotate_page_cw_button.connect('clicked', lambda b: self.rotate_current_page(90))
        self.rotate_page_cw_button.add_css_class('flat')
        pages_header.append(self.rotate_page_cw_button)

        self.delete_page_button = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.delete_page_button.set_tooltip_text(_("delete_page_tip"))
        self.delete_page_button.connect('clicked', self.on_delete_page)
        self.delete_page_button.add_css_class('flat')
        pages_header.append(self.delete_page_button)

        sidebar_box.append(pages_header)

        factory = PageThumbnailFactory(editor_window=self)
        self.thumbnails_list = Gtk.GridView.new(None, factory)
        self.thumbnails_list.set_max_columns(1)
        self.thumbnails_list.set_min_columns(1)
        self.thumbnails_list.set_vexpand(True)

        self.thumbnail_selection_model = Gtk.SingleSelection(model=self.pages_model)
        self.thumbnails_list.set_model(self.thumbnail_selection_model)
        self.thumbnail_selection_model.connect("selection-changed", self.on_thumbnail_selected)

        thumbnails_scroll = Gtk.ScrolledWindow(vexpand=True)
        thumbnails_scroll.set_child(self.thumbnails_list)
        thumbnails_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_box.append(thumbnails_scroll)

        self.paned.set_start_child(sidebar_box)

    def _create_main_toolbar(self):
        """Create main toolbar."""
        self.main_toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.main_toolbar.add_css_class('toolbar')

        self.toolbar_row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.toolbar_row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_toolbar.append(self.toolbar_row1)
        self.main_toolbar.append(self.toolbar_row2)

        zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out.set_tooltip_text(_("zoom_out_tip"))
        zoom_out.connect("clicked", self.on_zoom_out)
        self.zoom_label = Gtk.Label(label="100%")
        zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in.set_tooltip_text(_("zoom_in_tip"))
        zoom_in.connect("clicked", self.on_zoom_in)
        self.toolbar_row1.append(zoom_out)
        self.toolbar_row1.append(self.zoom_label)
        self.toolbar_row1.append(zoom_in)

        self.toolbar_row1.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6))

        self.prev_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.prev_button.set_tooltip_text(_("prev_page_tip"))
        self.prev_button.connect("clicked", self.on_prev_page)
        self.page_label = Gtk.Label(label=_("page_info_count").format(0, 0))
        self.next_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_button.set_tooltip_text(_("next_page_tip"))
        self.next_button.connect("clicked", self.on_next_page)
        self.add_page_button = Gtk.Button.new_from_icon_name("document-new-symbolic")
        self.add_page_button.set_tooltip_text(_("add_page_tip"))
        self.add_page_button.connect("clicked", self.on_add_page)
        self.toolbar_row1.append(self.prev_button)
        self.toolbar_row1.append(self.page_label)
        self.toolbar_row1.append(self.next_button)
        self.toolbar_row1.append(self.add_page_button)

        self.toolbar_row1.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6))

        self.symbols_button = Gtk.MenuButton()
        self.symbols_button.set_icon_name("face-smile-symbolic")
        self.symbols_button.set_tooltip_text(_("tooltip_symbols"))
        self.symbols_popover = SymbolsPopover(editor_window=self)
        self.symbols_button.set_popover(self.symbols_popover)
        self.toolbar_row1.append(self.symbols_button)

        self.text_format_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.text_format_sep)
        self.text_format_sep.set_visible(False)

        self.text_format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.font_store = Gtk.ListStore(str, str)
        self.font_store.append([_("font_loading"), ""])
        self.font_combo = Gtk.ComboBox(model=self.font_store)
        cell = Gtk.CellRendererText()
        self.font_combo.pack_start(cell, True)
        self.font_combo.add_attribute(cell, "text", 0)
        self.font_combo.set_active(0)
        self.font_combo.set_tooltip_text(_("font_tip"))
        self.font_combo.connect("changed", self.on_text_format_changed)
        self.font_combo.set_sensitive(False)
        self.text_format_box.append(self.font_combo)

        self.font_size_spin = Gtk.SpinButton.new_with_range(6, 96, 1)
        self.font_size_spin.set_value(11)
        self.font_size_spin.set_tooltip_text(_("font_size_tip"))
        self.font_size_spin.connect("value-changed", self.on_text_format_changed)
        self.text_format_box.append(self.font_size_spin)

        self.bold_button = Gtk.ToggleButton(icon_name="format-text-bold-symbolic")
        self.bold_button.set_tooltip_text(_("bold_tip"))
        self.bold_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.bold_button)

        self.italic_button = Gtk.ToggleButton(icon_name="format-text-italic-symbolic")
        self.italic_button.set_tooltip_text(_("italic_tip"))
        self.italic_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.italic_button)

        self.underline_button = Gtk.ToggleButton(icon_name="format-text-underline-symbolic")
        self.underline_button.set_tooltip_text(_("underline_tip"))
        self.underline_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.underline_button)

        self.strikethrough_button = Gtk.ToggleButton(icon_name="format-text-strikethrough-symbolic")
        self.strikethrough_button.set_tooltip_text(_("strikethrough_tip"))
        self.strikethrough_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.strikethrough_button)

        align_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        align_box.add_css_class("linked")

        self.align_left_button = Gtk.ToggleButton(icon_name="format-justify-left-symbolic")
        self.align_left_button.set_tooltip_text(_("align_left_tip"))
        self.align_left_button.set_active(True)
        self.align_left_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_left_button)

        self.align_center_button = Gtk.ToggleButton(icon_name="format-justify-center-symbolic")
        self.align_center_button.set_tooltip_text(_("align_center_tip"))
        self.align_center_button.set_group(self.align_left_button)
        self.align_center_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_center_button)

        self.align_right_button = Gtk.ToggleButton(icon_name="format-justify-right-symbolic")
        self.align_right_button.set_tooltip_text(_("align_right_tip"))
        self.align_right_button.set_group(self.align_left_button)
        self.align_right_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_right_button)

        self.align_justify_button = Gtk.ToggleButton(icon_name="format-justify-fill-symbolic")
        self.align_justify_button.set_tooltip_text(_("align_justify_tip"))
        self.align_justify_button.set_group(self.align_left_button)
        self.align_justify_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_justify_button)

        self.text_format_box.append(align_box)

        self.color_button = Gtk.ColorButton()
        default_rgba = Gdk.RGBA()
        default_rgba.parse("black")
        self.color_button.set_rgba(default_rgba)
        self.color_button.set_tooltip_text(_("color_tip"))
        self.color_button.connect("color-set", self.on_text_format_changed)
        self.text_format_box.append(self.color_button)

        self.link_button = Gtk.Button.new_from_icon_name("insert-link-symbolic")
        self.link_button.set_tooltip_text(_("insert_link_tip"))
        self.link_button.connect("clicked", self.on_insert_edit_link_clicked)
        self.text_format_box.append(self.link_button)

        self.toolbar_row2.append(self.text_format_box)

        self.shape_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.shape_toolbar_sep)
        self.shape_toolbar_sep.set_visible(False)

        self.shape_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.shape_fill_button = Gtk.ColorButton()
        self.shape_fill_button.set_title(_("shape_fill_dialog_title"))
        fill_rgba = Gdk.RGBA()
        fill_rgba.parse("white")
        self.shape_fill_button.set_rgba(fill_rgba)
        self.shape_fill_button.set_tooltip_text(_("shape_fill_tip"))
        self.shape_fill_button.connect("color-set", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_fill_button)

        self.shape_transparent_toggle = Gtk.ToggleButton(label=_("transparent_label"))
        self.shape_transparent_toggle.set_active(True)
        self.shape_transparent_toggle.set_tooltip_text(_("shape_transparent_tip"))
        self.shape_transparent_toggle.connect("toggled", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_transparent_toggle)

        self.shape_stroke_button = Gtk.ColorButton()
        self.shape_stroke_button.set_title(_("shape_stroke_dialog_title"))
        stroke_rgba = Gdk.RGBA()
        stroke_rgba.parse("black")
        self.shape_stroke_button.set_rgba(stroke_rgba)
        self.shape_stroke_button.set_tooltip_text(_("shape_stroke_tip"))
        self.shape_stroke_button.connect("color-set", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_stroke_button)

        self.shape_stroke_width_spin = Gtk.SpinButton.new_with_range(0.5, 10, 0.5)
        self.shape_stroke_width_spin.set_value(2.0)
        self.shape_stroke_width_spin.set_tooltip_text(_("shape_width_tip"))
        self.shape_stroke_width_spin.connect("value-changed", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_stroke_width_spin)
        self.toolbar_row2.append(self.shape_toolbar_box)
        self.shape_toolbar_box.set_visible(False)

        self.stroke_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.stroke_toolbar_sep)
        self.stroke_toolbar_sep.set_visible(False)

        self.stroke_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.stroke_color_button = Gtk.ColorButton()
        self.stroke_color_button.set_tooltip_text(_("stroke_color_tip"))
        stroke_color_rgba = Gdk.RGBA()
        stroke_color_rgba.parse("black")
        self.stroke_color_button.set_rgba(stroke_color_rgba)
        self.stroke_color_button.connect("color-set", self.on_stroke_format_changed)
        self.stroke_toolbar_box.append(self.stroke_color_button)

        self.stroke_width_spin = Gtk.SpinButton.new_with_range(0.5, 40, 0.5)
        self.stroke_width_spin.set_value(2.0)
        self.stroke_width_spin.set_tooltip_text(_("stroke_width_tip"))
        self.stroke_width_spin.connect("value-changed", self.on_stroke_format_changed)
        self.stroke_toolbar_box.append(self.stroke_width_spin)
        self.toolbar_row2.append(self.stroke_toolbar_box)
        self.stroke_toolbar_box.set_visible(False)

        self.rotation_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.rotation_toolbar_sep)
        self.rotation_toolbar_sep.set_visible(False)

        self.rotation_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.rotate_obj_ccw_button = Gtk.Button.new_from_icon_name("object-rotate-left-symbolic")
        self.rotate_obj_ccw_button.set_tooltip_text(_("rotate_obj_ccw_tip"))
        self.rotate_obj_ccw_button.connect("clicked", self.on_rotate_object_ccw_clicked)
        self.rotation_toolbar_box.append(self.rotate_obj_ccw_button)

        self.rotate_obj_cw_button = Gtk.Button.new_from_icon_name("object-rotate-right-symbolic")
        self.rotate_obj_cw_button.set_tooltip_text(_("rotate_obj_cw_tip"))
        self.rotate_obj_cw_button.connect("clicked", self.on_rotate_object_cw_clicked)
        self.rotation_toolbar_box.append(self.rotate_obj_cw_button)

        rot_adj = Gtk.Adjustment.new(0.0, 0.0, 360.0, 1.0, 15.0, 0.0)
        self.rotation_spin = Gtk.SpinButton(adjustment=rot_adj, climb_rate=1.0, digits=0)
        self.rotation_spin.set_wrap(True)
        self.rotation_spin.set_tooltip_text(_("rotation_angle_tip"))
        self.rotation_spin.connect("value-changed", self.on_object_rotation_spin_changed)
        self.rotation_toolbar_box.append(self.rotation_spin)

        rot_deg_lbl = Gtk.Label(label="°")
        rot_deg_lbl.add_css_class("dim-label")
        self.rotation_toolbar_box.append(rot_deg_lbl)

        self.rotate_obj_reset_button = Gtk.Button(label="0°")
        self.rotate_obj_reset_button.set_tooltip_text(_("rotation_reset_tip"))
        self.rotate_obj_reset_button.connect("clicked", self.on_rotate_object_reset_clicked)
        self.rotation_toolbar_box.append(self.rotate_obj_reset_button)

        self.toolbar_row2.append(self.rotation_toolbar_box)
        self.rotation_toolbar_box.set_visible(False)

        self.form_builder_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.form_builder_toolbar_sep)
        self.form_builder_toolbar_sep.set_visible(False)

        self.form_builder_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        fb_type_label = Gtk.Label(label=_("form_field_type_label"))
        self.form_builder_toolbar_box.append(fb_type_label)
        self.form_builder_type_dropdown = Gtk.DropDown.new_from_strings([
            _("field_type_text"),
            _("field_type_checkbox"),
            _("field_type_dropdown")
        ])
        self.form_builder_type_dropdown.connect("notify::selected", self._on_form_builder_type_changed)
        self.form_builder_toolbar_box.append(self.form_builder_type_dropdown)

        fb_name_label = Gtk.Label(label=_("form_field_name_label"))
        self.form_builder_toolbar_box.append(fb_name_label)
        self.form_builder_name_entry = Gtk.Entry()
        self.form_builder_name_entry.set_placeholder_text(_("form_field_name_placeholder"))
        self.form_builder_name_entry.set_tooltip_text(_("form_field_name_tip"))
        self.form_builder_name_entry.set_width_chars(12)
        self.form_builder_name_entry.connect("changed", self._on_form_builder_name_changed)
        self.form_builder_toolbar_box.append(self.form_builder_name_entry)

        self.form_builder_multiline_check = Gtk.CheckButton(label=_("form_field_multiline"))
        self.form_builder_multiline_check.set_tooltip_text(_("form_field_multiline_tip"))
        self.form_builder_multiline_check.connect("toggled", self._on_form_builder_multiline_toggled)
        self.form_builder_toolbar_box.append(self.form_builder_multiline_check)

        self.form_builder_add_label_check = Gtk.CheckButton(label=_("form_field_add_label"))
        self.form_builder_add_label_check.set_tooltip_text(_("form_field_add_label_tip"))
        self.form_builder_toolbar_box.append(self.form_builder_add_label_check)

        self.form_builder_label_entry = Gtk.Entry()
        self.form_builder_label_entry.set_placeholder_text(_("form_field_label_placeholder"))
        self.form_builder_label_entry.set_tooltip_text(_("form_field_add_label_tip"))
        self.form_builder_label_entry.set_width_chars(11)
        self.form_builder_toolbar_box.append(self.form_builder_label_entry)

        self.form_builder_options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        fb_opt_label = Gtk.Label(label=_("form_field_options_label"))
        self.form_builder_options_box.append(fb_opt_label)
        self.form_builder_options_entry = Gtk.Entry()
        self.form_builder_options_entry.set_placeholder_text(_("form_field_options_placeholder"))
        self.form_builder_options_entry.set_tooltip_text(_("form_field_options_tip"))
        self.form_builder_options_entry.set_width_chars(16)
        self.form_builder_options_entry.connect("changed", self._on_form_builder_options_changed)
        self.form_builder_options_box.append(self.form_builder_options_entry)

        self.form_builder_edit_options_btn = Gtk.Button.new_from_icon_name("view-list-bullet-symbolic")
        self.form_builder_edit_options_btn.set_tooltip_text(_("form_field_edit_options"))
        self.form_builder_edit_options_btn.add_css_class("flat")
        self.form_builder_edit_options_btn.connect("clicked", self._on_form_builder_edit_options_clicked)
        self.form_builder_options_box.append(self.form_builder_edit_options_btn)

        self.form_builder_toolbar_box.append(self.form_builder_options_box)
        self.form_builder_options_box.set_visible(False)

        fb_del_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.form_builder_toolbar_box.append(fb_del_sep)

        self.form_builder_delete_button = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
        self.form_builder_delete_button.set_tooltip_text(_("form_field_delete_tip"))
        self.form_builder_delete_button.add_css_class("flat")
        self.form_builder_delete_button.set_sensitive(False)
        self.form_builder_delete_button.connect("clicked", self._on_form_builder_delete_clicked)
        self.form_builder_toolbar_box.append(self.form_builder_delete_button)

        fb_hint_label = Gtk.Label(label=_("form_builder_hint"))
        fb_hint_label.add_css_class("dim-label")
        self.form_builder_toolbar_box.append(fb_hint_label)

        self.toolbar_row2.append(self.form_builder_toolbar_box)
        self.form_builder_toolbar_box.set_visible(False)

        self.calibration_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.calibration_toolbar_sep)
        self.calibration_toolbar_sep.set_visible(False)

        self.calibration_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        calib_lbl = Gtk.Label(label=_("calibration_toolbar_label"))
        calib_lbl.add_css_class("heading")
        self.calibration_toolbar_box.append(calib_lbl)

        self.calibration_scale_label = Gtk.Label(label=_("scale_uncalibrated"))
        self.calibration_scale_label.add_css_class("dim-label")
        self.calibration_toolbar_box.append(self.calibration_scale_label)

        preset_strings = [_("scale_preset_custom")] + list(PRESET_SCALES.keys())
        self.calibration_preset_dropdown = Gtk.DropDown.new_from_strings(preset_strings)
        self.calibration_preset_dropdown.connect("notify::selected", self.on_calibration_preset_changed)
        self.calibration_toolbar_box.append(self.calibration_preset_dropdown)

        self.calibrate_dialog_btn = Gtk.Button(label=_("btn_calibrate"))
        self.calibrate_dialog_btn.connect("clicked", self.on_calibrate_dialog_clicked)
        self.calibration_toolbar_box.append(self.calibrate_dialog_btn)

        self.calibrate_reset_btn = Gtk.Button(label=_("btn_reset_scale"))
        self.calibrate_reset_btn.add_css_class("flat")
        self.calibrate_reset_btn.connect("clicked", self.on_calibration_reset_clicked)
        self.calibration_toolbar_box.append(self.calibrate_reset_btn)

        calib_hint_lbl = Gtk.Label(label=_("tool_calibrate_tip"))
        calib_hint_lbl.add_css_class("dim-label")
        self.calibration_toolbar_box.append(calib_hint_lbl)

        self.toolbar_row2.append(self.calibration_toolbar_box)
        self.calibration_toolbar_box.set_visible(False)

        self.view_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row1.append(self.view_toolbar_sep)
        self.view_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        self.highlight_color_button = Gtk.ColorButton()
        hl_rgba = Gdk.RGBA()
        hl_rgba.parse("yellow")
        self.highlight_color_button.set_rgba(hl_rgba)
        self.highlight_color_button.set_tooltip_text(_("highlight_color_tip"))
        self.view_toolbar_box.append(self.highlight_color_button)
        
        def _make_icon_label_btn(icon_name, label_text, tooltip, callback):
            btn = Gtk.Button()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            img = Gtk.Image.new_from_icon_name(icon_name)
            lbl = Gtk.Label(label=label_text)
            box.append(img)
            box.append(lbl)
            btn.set_child(box)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            return btn

        self.highlight_button = _make_icon_label_btn("marker-symbolic", _("highlight"), _("highlight_tip"), self.on_highlight_clicked)
        self.view_toolbar_box.append(self.highlight_button)
        
        self.remove_highlight_button = _make_icon_label_btn("edit-clear-symbolic", _("remove_highlight"), _("remove_highlight_tip"), self.on_remove_highlight_clicked)
        self.view_toolbar_box.append(self.remove_highlight_button)
        
        self.toolbar_row1.append(self.view_toolbar_box)
        self.view_toolbar_box.set_visible(False)
        self.view_toolbar_sep.set_visible(False)

    def _setup_controllers(self):
        """Setup controllers."""
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect('drop', self.on_drop)
        self.add_controller(drop_target)

        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect('scroll', self.on_scroll_zoom)
        self.pdf_view.add_controller(scroll_controller)

        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect('motion', self._on_pointer_motion)
        self.pdf_view.add_controller(motion_controller)

        click_controller = Gtk.GestureClick.new()
        click_controller.connect('pressed', self.on_pdf_view_pressed)
        self.pdf_view.add_controller(click_controller)

        right_click_controller = Gtk.GestureClick.new()
        right_click_controller.set_button(3)
        right_click_controller.connect('pressed', self._on_right_click)
        self.pdf_view.add_controller(right_click_controller)

        middle_click_controller = Gtk.GestureClick.new()
        middle_click_controller.set_button(2)
        middle_click_controller.connect('pressed', self._on_middle_click)
        self.pdf_view.add_controller(middle_click_controller)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self.on_key_pressed)
        self.add_controller(key_controller)

        drag_controller = Gtk.GestureDrag.new()
        drag_controller.set_button(Gdk.BUTTON_PRIMARY)
        drag_controller.connect("drag-begin", self.on_drag_begin)
        drag_controller.connect("drag-update", self.on_drag_update)
        drag_controller.connect("drag-end", self.on_drag_end)
        self.pdf_view.add_controller(drag_controller)

        thumbnail_drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        thumbnail_drop.connect('drop', self.on_thumbnail_drop)
        self.thumbnails_list.add_controller(thumbnail_drop)

    def _connect_actions(self):
        """Connect actions."""
        action_save_as = Gio.SimpleAction.new('save_as', None)
        action_save_as.connect('activate', self.on_save_as)
        self.add_action(action_save_as)

        action_merge = Gio.SimpleAction.new('merge_documents', None)
        action_merge.connect('activate', self.on_merge_documents)
        self.add_action(action_merge)

        action_export_as = Gio.SimpleAction.new('export_as', None)
        action_export_as.connect('activate', self.on_export_as)
        self.add_action(action_export_as)

        for fmt in ("docx", "pptx", "odt", "odp", "txt"):
            act = Gio.SimpleAction.new(f"export_{fmt}", None)
            act.connect("activate", getattr(self, f"on_export_{fmt}"))
            self.add_action(act)

        action_print = Gio.SimpleAction.new('print', None)
        action_print.connect('activate', self.on_print_activated)
        self.add_action(action_print)

        action_about = Gio.SimpleAction.new('about', None)
        action_about.connect('activate', self.on_about_activated)
        self.add_action(action_about)

        action_new = Gio.SimpleAction.new('new', None)
        action_new.connect('activate', lambda a, p: self.on_new_clicked(None))
        self.add_action(action_new)

        action_open = Gio.SimpleAction.new('open', None)
        action_open.connect('activate', lambda a, p: self.on_open_clicked(None))
        self.add_action(action_open)

        action_quick_guide = Gio.SimpleAction.new('quick_guide', None)
        action_quick_guide.connect('activate', self._on_quick_guide_activated)
        self.add_action(action_quick_guide)

        action_save = Gio.SimpleAction.new('save', None)
        action_save.connect('activate', lambda a, p: self.on_save_clicked(None))
        self.add_action(action_save)

        action_undo = Gio.SimpleAction.new("undo", None)
        action_undo.connect("activate", lambda a, p: self.undo_manager.undo())
        self.add_action(action_undo)

        action_redo = Gio.SimpleAction.new("redo", None)
        action_redo.connect("activate", lambda a, p: self.undo_manager.redo())
        self.add_action(action_redo)

        current_confirm = bool(get_setting("confirm_delete_objects", True))
        self.action_confirm_delete = Gio.SimpleAction.new_stateful(
            'confirm_delete', None, GLib.Variant.new_boolean(current_confirm)
        )
        def on_confirm_delete_change(action, value):
            new_val = value.get_boolean()
            action.set_state(value)
            set_setting("confirm_delete_objects", new_val)
        self.action_confirm_delete.connect('change-state', on_confirm_delete_change)
        self.add_action(self.action_confirm_delete)

        action_close_tab = Gio.SimpleAction.new('close_tab', None)
        action_close_tab.connect('activate', self.on_close_tab)
        self.add_action(action_close_tab)

        action_next_tab = Gio.SimpleAction.new('next_tab', None)
        action_next_tab.connect('activate', self.on_next_tab)
        self.add_action(action_next_tab)

        action_prev_tab = Gio.SimpleAction.new('prev_tab', None)
        action_prev_tab.connect('activate', self.on_prev_tab)
        self.add_action(action_prev_tab)

        app = self.get_application()
        if app:
            app.set_accels_for_action("win.new", ["<Control>n"])
            app.set_accels_for_action("win.open", ["<Control>o"])
            app.set_accels_for_action("win.close_tab", ["<Control>w"])
            app.set_accels_for_action("win.next_tab", ["<Control>Page_Down", "<Control>Tab"])
            app.set_accels_for_action("win.prev_tab", ["<Control>Page_Up", "<Control><Shift>Tab", "<Control><Shift>ISO_Left_Tab"])
            app.set_accels_for_action("win.save", ["<Control>s"])
            app.set_accels_for_action("win.save_as", ["<Control><Shift>s"])
            app.set_accels_for_action("win.merge_documents", ["<Control><Shift>m"])
            app.set_accels_for_action("win.undo", ["<Control>z"])
            app.set_accels_for_action("win.redo", ["<Control>y", "<Control><Shift>z"])
            app.set_accels_for_action("win.print", ["<Control>p"])
            app.set_accels_for_action("win.quick_guide", ["F1"])
            app.set_accels_for_action("win.rotate_page_cw", ["<Control><Shift>r"])
            app.set_accels_for_action("win.rotate_page_ccw", ["<Control><Shift>l"])

        action_rotate_cw = Gio.SimpleAction.new('rotate_page_cw', None)
        action_rotate_cw.connect('activate', lambda a, p: self.rotate_current_page(90))
        self.add_action(action_rotate_cw)

        action_rotate_ccw = Gio.SimpleAction.new('rotate_page_ccw', None)
        action_rotate_ccw.connect('activate', lambda a, p: self.rotate_current_page(-90))
        self.add_action(action_rotate_ccw)

    def _update_ui_state(self):
        """Update UI state."""
        has_doc = self.doc is not None
        page_count = pdf_handler.get_page_count(self.doc) if self.doc else 0
        has_pages = page_count > 0
        can_go_prev = has_pages and self.current_page_index > 0
        can_go_next = has_pages and self.current_page_index < page_count - 1

        self.save_button.set_sensitive(has_doc and self.document_modified)
        if self.lookup_action("save"):
            self.lookup_action("save").set_enabled(has_doc and self.document_modified)
        self.lookup_action("save_as").set_enabled(has_doc)
        for act_name in ("export_as", "export_docx", "export_pptx", "export_odt", "export_odp", "export_txt"):
            act = self.lookup_action(act_name)
            if act:
                act.set_enabled(has_doc)
        self.lookup_action("print").set_enabled(has_doc)
        self.print_button.set_sensitive(has_doc)
        self.prev_button.set_sensitive(can_go_prev)
        self.next_button.set_sensitive(can_go_next)

        in_edit = not self.view_mode
        if hasattr(self, 'mode_toggle_button'):
            self.mode_toggle_button.set_sensitive(has_doc)
            if self.view_mode:
                self.mode_toggle_button.set_label(_("mode_edit"))
            else:
                self.mode_toggle_button.set_label(_("mode_view"))

        sidebar_tools = [self.select_tool_button, self.add_text_tool_button,
                         self.add_image_tool_button, self.drag_tool_button,
                         self.add_ellipse_tool_button, self.add_rectangle_tool_button,
                         self.pen_tool_button, self.highlighter_tool_button,
                         getattr(self, 'checkmark_tool_button', None),
                         getattr(self, 'cross_tool_button', None),
                         getattr(self, 'form_builder_tool_button', None),
                         getattr(self, 'calibrate_tool_button', None)]
        for btn in sidebar_tools:
            if btn:
                btn.set_sensitive(in_edit and has_doc)
            
        if hasattr(self, 'add_page_button'):
            self.add_page_button.set_sensitive(in_edit and has_doc)

        if hasattr(self, 'rotate_page_cw_button'):
            self.rotate_page_cw_button.set_sensitive(has_doc and has_pages)
        if hasattr(self, 'rotate_page_ccw_button'):
            self.rotate_page_ccw_button.set_sensitive(has_doc and has_pages)
        if self.lookup_action("rotate_page_cw"):
            self.lookup_action("rotate_page_cw").set_enabled(has_doc and has_pages)
        if self.lookup_action("rotate_page_ccw"):
            self.lookup_action("rotate_page_ccw").set_enabled(has_doc and has_pages)

        if hasattr(self, 'delete_page_button'):
            self.delete_page_button.set_sensitive(in_edit and has_doc and page_count > 1)

        if hasattr(self, 'symbols_button'):
            self.symbols_button.set_sensitive(in_edit and has_doc)

        shape_selected = self.selected_shape is not None
        stroke_selected = getattr(self, 'selected_stroke', None) is not None
        text_selected = self.selected_text is not None
        shape_controls_active = in_edit and (shape_selected or self.tool_mode in ("add_ellipse", "add_rectangle", "add_checkmark", "add_cross"))
        stroke_controls_active = in_edit and (stroke_selected or self.tool_mode in ("pen", "highlighter"))
        form_builder_active = in_edit and (self.tool_mode == "form_builder")
        calibrate_active = in_edit and (self.tool_mode == "calibrate")
        view_text_selected = self.view_mode and (getattr(self, 'view_sel_rect', None) is not None or getattr(self, 'selected_word', None) is not None)
        format_enabled_base = in_edit and ((text_selected or self.tool_mode == "add_text") and
                               self.selected_image is None and not shape_selected and not stroke_selected and not form_builder_active and not calibrate_active)

        if hasattr(self, 'toolbar_row2'):
            self.toolbar_row2.set_visible(in_edit and has_doc)

        if hasattr(self, 'form_builder_toolbar_box'):
            self.form_builder_toolbar_box.set_visible(form_builder_active)
            self.form_builder_toolbar_sep.set_visible(form_builder_active)
            self.form_builder_type_dropdown.set_sensitive(has_doc)
            self.form_builder_name_entry.set_sensitive(has_doc)
            self.form_builder_multiline_check.set_sensitive(has_doc)
            if hasattr(self, 'form_builder_add_label_check') and self.form_builder_add_label_check:
                self.form_builder_add_label_check.set_sensitive(has_doc)
            if hasattr(self, 'form_builder_label_entry') and self.form_builder_label_entry:
                self.form_builder_label_entry.set_sensitive(has_doc)
            if hasattr(self, 'form_builder_delete_button') and self.form_builder_delete_button:
                self.form_builder_delete_button.set_sensitive(has_doc and getattr(self, 'selected_form_field', None) is not None)
            if hasattr(self, '_update_form_field_overlay_interactivity'):
                self._update_form_field_overlay_interactivity()

        if hasattr(self, 'calibration_toolbar_box'):
            self.calibration_toolbar_box.set_visible(calibrate_active)
            self.calibration_toolbar_sep.set_visible(calibrate_active)
            if calibrate_active:
                self._update_calibration_controls()

        if hasattr(self, 'text_format_box'):
            self.text_format_box.set_visible(in_edit and not shape_controls_active and not stroke_controls_active and not form_builder_active and not calibrate_active and self.selected_image is None)
            self.text_format_sep.set_visible(False)

        self.font_combo.set_sensitive(format_enabled_base and not self.font_scan_in_progress)
        self.font_size_spin.set_sensitive(format_enabled_base)
        self.color_button.set_sensitive(format_enabled_base)
        if self.bold_button: self.bold_button.set_sensitive(format_enabled_base)
        if self.italic_button: self.italic_button.set_sensitive(format_enabled_base)
        if hasattr(self, 'underline_button') and self.underline_button:
            self.underline_button.set_sensitive(format_enabled_base)
        if hasattr(self, 'strikethrough_button') and self.strikethrough_button:
            self.strikethrough_button.set_sensitive(format_enabled_base)
        for btn in [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                    getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]:
            if btn: btn.set_sensitive(format_enabled_base)

        if hasattr(self, 'shape_toolbar_box'):
            self.shape_toolbar_box.set_visible(shape_controls_active)
            self.shape_toolbar_sep.set_visible(False)

        self.shape_fill_button.set_sensitive(shape_controls_active)
        self.shape_stroke_button.set_sensitive(shape_controls_active)
        self.shape_stroke_width_spin.set_sensitive(shape_controls_active)
        self.shape_transparent_toggle.set_sensitive(shape_controls_active)

        if hasattr(self, 'stroke_toolbar_box'):
            self.stroke_toolbar_box.set_visible(stroke_controls_active)
            self.stroke_toolbar_sep.set_visible(False)

        if hasattr(self, 'stroke_color_button'):
            self.stroke_color_button.set_sensitive(stroke_controls_active)
        if hasattr(self, 'stroke_width_spin'):
            self.stroke_width_spin.set_sensitive(stroke_controls_active)

        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        has_selected_obj = in_edit and (selected_obj is not None)

        if hasattr(self, 'rotation_toolbar_box'):
            self.rotation_toolbar_box.set_visible(has_selected_obj)
            self.rotation_toolbar_sep.set_visible(has_selected_obj)
            self.rotation_toolbar_box.set_sensitive(has_selected_obj)
            self._update_rotation_controls(selected_obj)

        if hasattr(self, 'view_toolbar_box'):
            self.view_toolbar_box.set_visible(has_doc)
            self.view_toolbar_sep.set_visible(has_doc)
            
            can_highlight = False
            if self.view_mode:
                can_highlight = self.view_sel_rect is not None
            else:
                can_highlight = self.selected_text is not None
                
            if hasattr(self, 'highlight_button'):
                self.highlight_button.set_sensitive(can_highlight)
            if hasattr(self, 'remove_highlight_button'):
                self.remove_highlight_button.set_sensitive(can_highlight)
            if hasattr(self, 'highlight_color_button'):
                self.highlight_color_button.set_sensitive(can_highlight)

        if shape_selected:
            self.shape_transparent_toggle.handler_block_by_func(self.on_shape_format_changed)
            self.shape_transparent_toggle.set_active(self.selected_shape.is_transparent)
            self.shape_transparent_toggle.handler_unblock_by_func(self.on_shape_format_changed)

        if text_selected:
            self._update_text_format_controls(self.selected_text)
        elif not self.inline_editor_widget:
            self._update_text_format_controls(None)

        if shape_selected:
            self._update_shape_format_controls(self.selected_shape)
        else:
            self._update_shape_format_controls(None)

        if stroke_selected:
            self._update_stroke_format_controls(self.selected_stroke)
        elif stroke_controls_active:
            self._update_stroke_format_controls(None)

        self.select_tool_button.get_style_context().remove_class('active')
        self.add_text_tool_button.get_style_context().remove_class('active')
        self.add_image_tool_button.get_style_context().remove_class('active')
        self.drag_tool_button.get_style_context().remove_class('active')
        self.add_ellipse_tool_button.get_style_context().remove_class('active')
        self.add_rectangle_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'pen_tool_button'):
            self.pen_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'highlighter_tool_button'):
            self.highlighter_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'checkmark_tool_button'):
            self.checkmark_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'cross_tool_button'):
            self.cross_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'form_builder_tool_button') and self.form_builder_tool_button:
            self.form_builder_tool_button.get_style_context().remove_class('active')

        if self.view_mode:
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))
        elif self.tool_mode == "select":
            self.select_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(None)
        elif self.tool_mode == "add_text":
            self.add_text_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_image":
            self.add_image_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("cell"))
        elif self.tool_mode == "drag":
            self.drag_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("move"))
        elif self.tool_mode == "add_ellipse":
            self.add_ellipse_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_rectangle":
            self.add_rectangle_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_checkmark":
            if hasattr(self, 'checkmark_tool_button'):
                self.checkmark_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_cross":
            if hasattr(self, 'cross_tool_button'):
                self.cross_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "pen":
            if hasattr(self, 'pen_tool_button'):
                self.pen_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "highlighter":
            if hasattr(self, 'highlighter_tool_button'):
                self.highlighter_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "form_builder":
            if hasattr(self, 'form_builder_tool_button') and self.form_builder_tool_button:
                self.form_builder_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))

        if has_doc:
            self.stack.set_visible_child_name("editor")
        else:
            self.stack.set_visible_child_name("welcome")

        if has_doc:
            self.update_page_label()
            self.update_zoom_label()
            if self.document_modified and not self.get_title().endswith("*"):
                self.set_title(self.get_title() + "*")
            elif not self.document_modified and self.get_title().endswith("*"):
                self.set_title(self.get_title()[:-1])
        else:
            self.page_label.set_text(_("page_info_count").format(0, 0))
            self.update_zoom_label()
            self.status_label.set_text(_("status_open_or_drop"))
            self.set_title(constants.APP_NAME)
            self.document_modified = False

        self._update_undo_redo_buttons()

    def on_about_activated(self, action, param):
        """Show the application About dialog."""
        about_dialog = Gtk.AboutDialog(transient_for=self, modal=True)

        about_dialog.set_program_name(constants.APP_NAME)
        about_dialog.set_version(constants.APP_VERSION)
        about_dialog.set_authors(["Barın Güzeldemirci (word-sys)"])

        try:
            about_dialog.set_license_type(Gtk.License.GPL_3_0_OR_LATER)
        except AttributeError:
            try:
                about_dialog.set_license_type(Gtk.License.GPL_3_0)
            except AttributeError:
                about_dialog.set_license_type(Gtk.License.CUSTOM)
        try:
            license_path = Path(__file__).resolve().parent.parent / "LICENSE"
            if not license_path.exists():
                license_path = Path("/usr/share/common-licenses/GPL-3")

            if license_path.exists():
                with open(license_path, 'r', encoding='utf-8') as f:
                    license_text = f.read()
                about_dialog.set_license(license_text)
                about_dialog.set_wrap_license(True)
            else:
                about_dialog.set_license("GNU General Public License v3.0 or later.\nFull text could not be loaded.")
        except Exception as e:
            print(f"Error reading LICENSE file: {e}")
            about_dialog.set_license("Error reading license text.")

        about_dialog.set_website("https://github.com/word-sys/word-sys-pdf-editor")
        about_dialog.set_website_label(_("about_website_label"))
        about_dialog.set_comments(_("about_comments"))

        try:
            about_dialog.set_logo_icon_name("f-pv1")
        except Exception as e:
            print(f"Warning: Could not load application icon for About dialog: {e}")
            about_dialog.set_logo_icon_name("application-x-executable")

        about_dialog.set_copyright("© 2024-2026 Barın Güzeldemirci (word-sys)")

        tab_map = {
            "About": _("about_tab_about"),
            "Credits": _("about_tab_credits"),
            "License": _("about_tab_license"),
        }
        def _localize_about_tabs(widget):
            if isinstance(widget, Gtk.Label):
                txt = widget.get_label()
                if txt in tab_map:
                    widget.set_label(tab_map[txt])
            child = widget.get_first_child() if hasattr(widget, 'get_first_child') else None
            while child:
                _localize_about_tabs(child)
                child = child.get_next_sibling()

        _localize_about_tabs(about_dialog)
        about_dialog.present()


    def _record_recent_file(self, filepath):
        """Prepend filepath to recent_opened_files setting, deduplicate, and limit to 15."""
        if not filepath:
            return
        try:
            filepath_str = str(filepath)
            norm_path = os.path.abspath(os.path.normpath(filepath_str))
            recents = get_setting("recent_opened_files", [])
            if not isinstance(recents, list):
                recents = []
            updated = [
                p for p in recents
                if isinstance(p, str) and os.path.abspath(os.path.normpath(p)) != norm_path
            ]
            updated.insert(0, norm_path)
            updated = updated[:15]
            set_setting("recent_opened_files", updated)
        except Exception as e:
            print(f"Warning: Failed to record recent file {filepath}: {e}")

    def load_document(self, filepath, target_page=0, in_new_tab=None):
        """Load document into active session or a new tab."""
        existing_session = self.get_session_by_path(filepath)
        if existing_session:
            self.set_active_session(existing_session)
            if target_page != 0:
                self._load_page(target_page)
            return

        if in_new_tab is None:
            in_new_tab = (self._active_session is not None and self._active_session.doc is not None)

        if in_new_tab:
            new_session = self.create_session(filepath=filepath)
            self.add_session(new_session, switch_to=True)
            target_sess = new_session
        else:
            if self.check_unsaved_changes():
                return
            self.close_document()
            if self._active_session is None:
                self._active_session = self.create_session(filepath=filepath)
                self.sessions = [self._active_session]
            target_sess = self._active_session
            target_sess.pdf_path = filepath
            target_sess.original_file_path = filepath
            if hasattr(self, 'tab_view') and self.tab_view:
                if getattr(target_sess, 'tab_page', None) is None:
                    self._create_tab_for_session(target_sess)
            self._update_tab_title(target_sess)

        self._record_recent_file(filepath)
        self.status_label.set_text(_("loading").format(os.path.basename(filepath)))
        GLib.idle_add(self._show_loading_state)

        def _load_async():
            doc, error_msg = pdf_handler.load_pdf_document(filepath)
            GLib.idle_add(self._finish_loading, doc, error_msg, filepath, target_page, target_sess)

        thread = threading.Thread(target=_load_async)
        thread.daemon = True
        thread.start()

    def _show_loading_state(self):
        """Show loading state."""
        self.open_button.set_sensitive(False)
        self.save_button.set_sensitive(False)
        self.lookup_action("save_as").set_enabled(False)
        for act_name in ("export_as", "export_docx", "export_pptx", "export_odt", "export_odp", "export_txt"):
            act = self.lookup_action(act_name)
            if act:
                act.set_enabled(False)
        self.prev_button.set_sensitive(False)
        self.next_button.set_sensitive(False)
        self.font_combo.set_sensitive(False)
        self.font_size_spin.set_sensitive(False)
        self.color_button.set_sensitive(False)
        self.select_tool_button.set_sensitive(False)
        self.add_text_tool_button.set_sensitive(False)
        if getattr(self, 'calibrate_tool_button', None):
            self.calibrate_tool_button.set_sensitive(False)
        if not any(s.doc is not None for s in self.sessions):
            if hasattr(self, 'stack') and self.stack:
                self.stack.set_visible_child_name("welcome")


    def _finish_loading(self, doc, error_msg, filepath, target_page=0, target_session=None):
        """Finalize document loading, set active session state, and start thumbnail generation."""
        sess = target_session or getattr(self, '_active_session', None)
        if error_msg:
            show_error_dialog(self, error_msg)
            self.status_label.set_text(_("doc_load_failed"))
            if len(self.sessions) > 1 and sess:
                self.remove_session(sess)
            else:
                self.close_document()
            self.open_button.set_sensitive(True)
            self.select_tool_button.set_sensitive(True)
            self.add_text_tool_button.set_sensitive(True)
            if getattr(self, 'calibrate_tool_button', None):
                self.calibrate_tool_button.set_sensitive(True)
            self._update_ui_state()
            return
        elif doc and sess:
            sess.doc = doc
            sess.is_repaired_file = getattr(doc, 'is_repaired', False)
            sess.pdf_path = filepath
            sess.original_file_path = filepath
            sess.allow_incremental_save = True
            sess.is_modified = False
            sess.current_page_index = target_page
            self._update_tab_title(sess)

            calib_data = pdf_handler.extract_scale_calibration(doc)
            if calib_data:
                try:
                    sess.scale_calibration = ScaleCalibration.from_dict(calib_data)
                except Exception as e:
                    print(f"Warning restoring scale calibration: {e}")

            if getattr(sess, 'is_repaired_file', False):
                print(_("dbg_repaired_while_opening"))
            self._record_recent_file(filepath)

            self.set_active_session(sess)

            self.target_page_after_load = target_page
            self._load_page(target_page)
            GLib.idle_add(self._load_thumbnails, sess)

        self.open_button.set_sensitive(True)
        self.select_tool_button.set_sensitive(True)
        self.add_text_tool_button.set_sensitive(True)
        if getattr(self, 'calibrate_tool_button', None):
            self.calibrate_tool_button.set_sensitive(True)
        self._update_ui_state()

    def _load_thumbnails(self, session=None):
        """Asynchronously generate and populate sidebar thumbnails for each document page."""
        sess = session or self._active_session
        if not sess or not sess.doc:
            return

        target_doc = sess.doc
        target_model = sess.pages_model
        if target_model is not None:
            target_model.remove_all()
        page_count = pdf_handler.get_page_count(target_doc)

        thumb_iter = [0]
        def _load_next_thumb():
            if sess.doc != target_doc:
                return GLib.SOURCE_REMOVE
            if thumb_iter[0] < page_count:
                index = thumb_iter[0]
                thumb = pdf_handler.generate_thumbnail(target_doc, index, target_width=150)

                if thumb and target_model is not None:
                    pdf_page_obj = PdfPage(index=index, thumbnail=thumb)
                    target_model.append(pdf_page_obj)
                thumb_iter[0] += 1
                if self._active_session == sess:
                    if index % 5 == 0 or index == page_count - 1:
                        self.status_label.set_text(_("thumbnail_loaded").format(index + 1, page_count))
                return GLib.SOURCE_CONTINUE 
            else:
                if self._active_session == sess:
                    if sess.pdf_path:
                        self.status_label.set_text(_("loaded").format(os.path.basename(sess.pdf_path)))
                    else:
                        self.status_label.set_text(_("new_doc_loaded"))                
                    if page_count > 0:
                        target = getattr(self, 'target_page_after_load', 0)
                        if target >= page_count: target = 0
                        self._load_page(target)
                    else:
                        self._update_ui_state()
                return GLib.SOURCE_REMOVE

        GLib.idle_add(_load_next_thumb)


    def _load_page(self, page_index, preserve_scroll=False, reload_objects=True):
        """Extract editable objects, dimensions, and render page at given index."""
        current_v_scroll = 0
        current_h_scroll = 0
        if preserve_scroll:
            v_adj = self.pdf_scroll.get_vadjustment()
            h_adj = self.pdf_scroll.get_hadjustment()
            if v_adj:
                current_v_scroll = v_adj.get_value()
            if h_adj:
                current_h_scroll = h_adj.get_value()

        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            print(f"Warning: Invalid attempt to load page {page_index}.")
            return

        self.commit_pending_format_change()

        old_page_idx = getattr(self, 'current_page_index', None)
        if self.doc and old_page_idx is not None and (0 <= old_page_idx < pdf_handler.get_page_count(self.doc)):
            if old_page_idx != page_index and reload_objects:
                pdf_handler.save_page_snapshot(self.doc, old_page_idx, force=True)

        if reload_objects:
            self.undo_manager.clear()

        self.current_page_index = page_index
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.hide_text_editor()
        self._clear_form_field_overlays()

        if reload_objects:
            texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
            if error:
                show_error_dialog(self, _("text_extract_error", page_index + 1, error))
                self.editable_texts = []
            else:
                self.editable_texts = texts
                
            images, error = pdf_handler.extract_editable_images(self.doc, page_index)
            if error:
                show_error_dialog(self, _("image_extract_error").format(page_index + 1, error))
                self.editable_images = []
            else:
                self.editable_images = images

            shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
            if shapes_error:
                print(f"Warning: Could not extract shapes from page {page_index + 1}: {shapes_error}")
                self.editable_shapes = []
            else:
                self.editable_shapes = shapes

            strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
            if strokes_error:
                print(f"Warning: Could not extract strokes from page {page_index + 1}: {strokes_error}")
                self.editable_strokes = []
            else:
                self.editable_strokes = strokes

            form_fields, form_fields_error = pdf_handler.extract_acroform_fields(self.doc, page_index)
            if form_fields_error:
                print(f"Warning: Could not extract form fields from page {page_index + 1}: {form_fields_error}")
                self.form_fields = []
            else:
                self.form_fields = form_fields

        page = self.doc.load_page(page_index)
        self.current_pdf_page_width = int(page.rect.width * self.zoom_level)
        self.current_pdf_page_height = int(page.rect.height * self.zoom_level)

        print(f"DEBUG: Setting pdf_view content size: {self.current_pdf_page_width} x {self.current_pdf_page_height}")
        self.pdf_view.set_content_width(self.current_pdf_page_width)
        self.pdf_view.set_content_height(self.current_pdf_page_height)

        self.pdf_view.queue_draw()
        
        if preserve_scroll:
            GLib.idle_add(self.pdf_scroll.get_vadjustment().set_value, current_v_scroll)
            GLib.idle_add(self.pdf_scroll.get_hadjustment().set_value, current_h_scroll)

        self._sync_thumbnail_selection()
        self._update_ui_state()
        self._create_form_field_overlays()
        
        fallback_font = None
        for text_obj in self.editable_texts:
            if getattr(text_obj, 'font_fallback_used', False):
                fallback_font = text_obj.font_fallback_used
                break
        if fallback_font:
            self.status_label.set_text(f"font cannot be determinated, using {fallback_font}")
        
        if self.doc and reload_objects:
            pdf_handler.save_page_snapshot(self.doc, page_index)

    def close_document(self):
        """Close document."""
        if hasattr(self, '_active_session') and self._active_session:
            if self._active_session.undo_manager:
                self._active_session.undo_manager.clear()
            self._active_session.is_repaired_file = False
            if self._active_session.doc:
                pdf_handler.release_page_snapshots(self._active_session.doc)
                pdf_handler.close_pdf_document(self._active_session.doc)
            self._active_session.close()
            self._active_session.pdf_path = None
            self._active_session.original_file_path = None
            self._active_session.current_page_index = 0
            self._active_session.is_modified = False
            if self._active_session.pages_model:
                self._active_session.pages_model.remove_all()
        self.temp_stroke = None
        self.selected_form_field = None
        self.hide_text_editor()
        self._clear_form_field_overlays()
        self.pdf_view.set_content_width(1)
        self.pdf_view.set_content_height(1)
        self.pdf_view.queue_draw()
        self._update_ui_state()

    def _on_tab_bar_pressed(self, gesture, n_press, x, y):
        """Switch back to editor if clicking the tab bar while on welcome screen."""
        if hasattr(self, 'stack') and self.stack and self.stack.get_visible_child_name() == "welcome":
            if any(s.doc is not None for s in self.sessions):
                self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
                if self._active_session and self._active_session.doc is not None:
                    self.set_title(f"{constants.APP_NAME} - {self._active_session.display_title}")

    def go_to_welcome(self):
        """Navigate to welcome hub view."""
        if hasattr(self, 'stack') and self.stack:
            if self.stack.get_visible_child_name() == "welcome":
                # Toggle back to editor if any document is open
                active = self._active_session if (self._active_session and self._active_session.doc is not None) else None
                if not active:
                    for s in self.sessions:
                        if s.doc is not None:
                            active = s
                            break
                if active:
                    self.set_active_session(active)
                    self.stack.set_visible_child_name("editor")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_autohide(False)
                        self.tab_bar.set_visible(True)
                    self.set_title(f"{constants.APP_NAME} - {active.display_title}")
                    return

        if self.check_unsaved_changes():
            return

        old_welcome = self.stack.get_child_by_name("welcome")
        if old_welcome:
            self.stack.remove(old_welcome)
        new_welcome = WelcomeView(parent_window=self)
        self.stack.add_named(new_welcome, "welcome")

        self.stack.set_visible_child_name("welcome")
        has_open_docs = any(s.doc is not None for s in self.sessions)
        if hasattr(self, 'tab_bar') and self.tab_bar:
            self.tab_bar.set_autohide(not has_open_docs)
            self.tab_bar.set_visible(has_open_docs)
        self.set_title(constants.APP_NAME)

    def on_close_tab(self, action=None, param=None):
        """Close the currently active tab or document."""
        if hasattr(self, 'tab_view') and self.tab_view:
            selected_page = self.tab_view.get_selected_page()
            if selected_page:
                self.tab_view.close_page(selected_page)
                return
        if self.check_unsaved_changes():
            return
        self.close_document()

    def on_next_tab(self, action=None, param=None):
        """Switch to next document tab."""
        if hasattr(self, 'tab_view') and self.tab_view and self.tab_view.get_n_pages() > 1:
            self.tab_view.select_next_page()

    def on_prev_tab(self, action=None, param=None):
        """Switch to previous document tab."""
        if hasattr(self, 'tab_view') and self.tab_view and self.tab_view.get_n_pages() > 1:
            self.tab_view.select_previous_page()



    def save_document(self, save_path, incremental=False):
        """Save document."""
        if not self.doc or self.is_saving:
            return
        page_to_restore = self.current_page_index
        self.is_saving = True
        self.status_label.set_text(_("saving").format(os.path.basename(save_path)))
        if self.inline_editor_widget is not None:
            self._apply_and_hide_editor(force_apply=True)
        if hasattr(self, '_commit_pending_form_field_edit'):
            self._commit_pending_form_field_edit()

        if self._active_session and getattr(self._active_session, 'scale_calibration', None):
            pdf_handler.embed_scale_calibration(self.doc, self._active_session.scale_calibration.to_dict())

        success, error_msg = pdf_handler.save_document(self.doc, save_path, incremental=False)
        self.is_saving = False
        
        if success:
            print(_("dbg_save_success", save_path))
            self.document_modified = False 
            if self._active_session:
                self._active_session.pdf_path = save_path
                self._active_session.original_file_path = save_path
                self._update_tab_title(self._active_session)
                self.set_title(f"{constants.APP_NAME} - {self._active_session.display_title}")
            self.load_document(save_path, target_page=page_to_restore, in_new_tab=False)
            self.status_label.set_text(_("saved").format(os.path.basename(save_path)))
        else:
            show_error_dialog(self, _("err_pdf_save", error_msg))
            self.status_label.set_text(_("save_failed"))

        self._update_ui_state()

    def draw_pdf_page(self, area, cr, width, height):
        """Draw PDF page."""
        if not self.doc or self.current_pdf_page_width <= 0:
            cr.set_source_rgb(0.42, 0.42, 0.42)
            cr.paint()
            return

        page_w = self.current_pdf_page_width
        page_h = self.current_pdf_page_height
        page_offset_x = max(0, (width - page_w) / 2.0)
        page_offset_y = max(0, (height - page_h) / 2.0)

        cr.set_source_rgb(0.42, 0.42, 0.42)
        cr.paint()

        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.15)
        cr.rectangle(page_offset_x + 4.0, page_offset_y + 4.0, page_w, page_h)
        cr.fill()
        cr.restore()

        cr.save()
        cr.translate(page_offset_x, page_offset_y)
        cached_surf = pdf_handler.get_page_cairo_surface(self.doc, self.current_page_index, self.zoom_level)
        if cached_surf:
            cr.set_source_surface(cached_surf, 0, 0)
            cr.paint()
        else:
            pdf_handler.draw_page_to_cairo(cr, self.doc, self.current_page_index, self.zoom_level)
        cr.restore()

        page = self.doc[self.current_page_index]
        page_rot = page.rotation % 360
        cr.save()
        cr.translate(page_offset_x, page_offset_y)
        cr.scale(self.zoom_level, self.zoom_level)
        if page_rot != 0:
            mat = page.rotation_matrix
            cr.transform(cairo.Matrix(mat.a, mat.b, mat.c, mat.d, mat.e, mat.f))

        # Mask original underlying text on canvas while inline editor is actively editing
        if getattr(self, 'inline_editor_widget', None) is not None and getattr(self, 'inline_editor_text_obj', None) is not None:
            active_ed_obj = self.inline_editor_text_obj
            target_mask_box = getattr(self, '_inline_editor_target_rect', None) or getattr(active_ed_obj, 'bbox', None)
            if target_mask_box:
                mx1, my1, mx2, my2 = target_mask_box
                cr.save()
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.rectangle(mx1 - 1.5, my1 - 1.5, (mx2 - mx1) + 3.0, (my2 - my1) + 3.0)
                cr.fill()
                cr.restore()

        if self.dragged_object:
            if self.dragged_object.original_bbox:
                orig_x1, orig_y1, orig_x2, orig_y2 = self.dragged_object.original_bbox
                cr.save()
                cr.set_source_rgba(0.85, 0.85, 0.85, 0.55)
                cr.rectangle(orig_x1, orig_y1, orig_x2 - orig_x1, orig_y2 - orig_y1)
                cr.fill()
                cr.set_source_rgba(0.5, 0.5, 0.5, 0.7)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])
                cr.rectangle(orig_x1, orig_y1, orig_x2 - orig_x1, orig_y2 - orig_y1)
                cr.stroke()
                cr.set_dash([])
                cr.restore()

            x1, y1, x2, y2 = self.dragged_object.bbox
            ghost_x = x1
            ghost_y = y1
            ghost_w = x2 - x1
            ghost_h = y2 - y1

            cr.save()
            rot = getattr(self.dragged_object, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = ghost_x + ghost_w / 2.0
                cy = ghost_y + ghost_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            if isinstance(self.dragged_object, EditableImage) and self.dragged_object.image_bytes:
                try:
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(self.dragged_object.image_bytes)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf and ghost_w > 0 and ghost_h > 0:
                        cr.save()
                        cr.translate(ghost_x, ghost_y)
                        cr.scale(ghost_w / pixbuf.get_width(), ghost_h / pixbuf.get_height())
                        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
                        cr.paint_with_alpha(0.6)
                        cr.restore()
                except Exception as e:
                    cr.set_source_rgba(0.2, 0.5, 0.8, 0.5)
                    cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                    cr.fill()
            elif isinstance(self.dragged_object, EditableText):
                layout = PangoCairo.create_layout(cr)
                font_desc_str = f"{self.dragged_object.font_family_base} {self.dragged_object.font_size}"
                if self.dragged_object.is_bold: font_desc_str += " Bold"
                if self.dragged_object.is_italic: font_desc_str += " Italic"

                font_desc = Pango.FontDescription(font_desc_str)
                font_desc.set_absolute_size(int(self.dragged_object.font_size * Pango.SCALE))
                layout.set_font_description(font_desc)
                layout.set_text(self.dragged_object.text, -1)
                align = getattr(self.dragged_object, 'alignment', 'left')
                if ghost_w > 0:
                    nat_pw, _ = layout.get_size()
                    w_to_set = max(ghost_w, nat_pw / Pango.SCALE)
                    layout.set_width(int(w_to_set * Pango.SCALE))
                    if align == 'center':
                        layout.set_alignment(Pango.Alignment.CENTER)
                    elif align == 'right':
                        layout.set_alignment(Pango.Alignment.RIGHT)
                    elif align == 'justify':
                        layout.set_justify(True)

                r, g, b = self.dragged_object.color
                cr.set_source_rgba(r, g, b, 0.6)
                
                import re
                attr_list = Pango.AttrList()
                
                for match in re.finditer(r'(https?://[^\s]+|www\.[^\s]+)', self.dragged_object.text):
                    start_byte = len(self.dragged_object.text[:match.start()].encode('utf-8'))
                    end_byte = len(self.dragged_object.text[:match.end()].encode('utf-8'))
                    
                    color_attr = Pango.attr_foreground_new(0, int(0.33*65535), int(0.8*65535))
                    color_attr.start_index = start_byte
                    color_attr.end_index = end_byte
                    attr_list.insert(color_attr)
                    
                    underline_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                    underline_attr.start_index = start_byte
                    underline_attr.end_index = end_byte
                    attr_list.insert(underline_attr)
                
                if getattr(self.dragged_object, 'is_underline', False):
                    attr_list.insert(Pango.attr_underline_new(Pango.Underline.SINGLE))
                if getattr(self.dragged_object, 'is_strikethrough', False):
                    attr_list.insert(Pango.attr_strikethrough_new(True))
                
                layout.set_attributes(attr_list)
                
                cr.move_to(ghost_x, ghost_y)
                PangoCairo.show_layout(cr, layout)
            elif isinstance(self.dragged_object, EditableShape):
                if not self.dragged_object.is_transparent:
                    fill_r, fill_g, fill_b = self.dragged_object.fill_color
                    cr.set_source_rgba(fill_r, fill_g, fill_b, 0.4)
                    if self.dragged_object.shape_type == EditableShape.SHAPE_RECTANGLE:
                        cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                        cr.fill()
                    elif self.dragged_object.shape_type == EditableShape.SHAPE_ELLIPSE:
                        if ghost_w > 0 and ghost_h > 0:
                            cr.save()
                            cr.translate(ghost_x + ghost_w / 2.0, ghost_y + ghost_h / 2.0)
                            cr.scale(ghost_w / 2.0, ghost_h / 2.0)
                            cr.arc(0, 0, 1, 0, 2 * math.pi)
                            cr.restore()
                            cr.fill()
                stroke_r, stroke_g, stroke_b = self.dragged_object.stroke_color
                cr.set_source_rgba(stroke_r, stroke_g, stroke_b, 0.6)
                cr.set_line_width(self.dragged_object.stroke_width)
                if self.dragged_object.shape_type == EditableShape.SHAPE_RECTANGLE:
                    cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                    cr.stroke()
                elif self.dragged_object.shape_type == EditableShape.SHAPE_ELLIPSE:
                    if ghost_w > 0 and ghost_h > 0:
                        cr.save()
                        cr.translate(ghost_x + ghost_w / 2.0, ghost_y + ghost_h / 2.0)
                        cr.scale(ghost_w / 2.0, ghost_h / 2.0)
                        cr.arc(0, 0, 1, 0, 2 * math.pi)
                        cr.restore()
                        cr.stroke()
                elif self.dragged_object.shape_type == EditableShape.SHAPE_CHECKMARK:
                    pts = self.dragged_object.get_checkmark_points()
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_join(cairo.LINE_JOIN_ROUND)
                    cr.move_to(pts[0][0], pts[0][1])
                    for pt in pts[1:]:
                        cr.line_to(pt[0], pt[1])
                    cr.stroke()
                elif self.dragged_object.shape_type == EditableShape.SHAPE_CROSS:
                    lines = self.dragged_object.get_cross_lines()
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_join(cairo.LINE_JOIN_ROUND)
                    for (p1, p2) in lines:
                        cr.move_to(p1[0], p1[1])
                        cr.line_to(p2[0], p2[1])
                    cr.stroke()
            elif isinstance(self.dragged_object, EditableStroke):
                r, g, b = self.dragged_object.stroke_color
                cr.set_source_rgba(r, g, b, 0.6)
                cr.set_line_width(self.dragged_object.stroke_width)
                is_hl = getattr(self.dragged_object, 'tool_type', None) in ("highlighter", EditableStroke.TOOL_HIGHLIGHTER) or self.dragged_object.stroke_width >= 8.0
                if is_hl:
                    cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                    cr.set_line_join(cairo.LINE_JOIN_BEVEL)
                else:
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_join(cairo.LINE_JOIN_ROUND)
                if len(self.dragged_object.points) == 1:
                    px, py = self.dragged_object.points[0]
                    rad = max(self.dragged_object.stroke_width / 2.0, 1.0 / self.zoom_level)
                    if is_hl:
                        cr.rectangle(px - rad, py - rad, rad * 2.0, rad * 2.0)
                    else:
                        cr.arc(px, py, rad, 0, 2 * math.pi)
                    cr.fill()
                elif self.dragged_object.points:
                    p0 = self.dragged_object.points[0]
                    cr.move_to(p0[0], p0[1])
                    for pt in self.dragged_object.points[1:]:
                        cr.line_to(pt[0], pt[1])
                    cr.stroke()
            cr.restore()
            
        for text_obj in self.editable_texts:
            if text_obj.page_number != self.current_page_index:
                continue
            if not text_obj.is_new:
                continue 
            if getattr(text_obj, 'is_baked', False):
                continue
            if text_obj is self.dragged_object:
                continue
            if not text_obj.bbox or not text_obj.text:
                continue
            x1, y1, x2, y2 = text_obj.bbox
            draw_x = x1
            draw_y = y1
            cr.save()
            rot = getattr(text_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = draw_x + (x2 - x1) / 2.0
                cy = draw_y + (y2 - y1) / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            layout = PangoCairo.create_layout(cr)
            font_family = f"{text_obj.font_family_base}, DejaVu Sans, FreeSans, sans-serif"
            font_desc = Pango.FontDescription.from_string(font_family)
            if text_obj.is_bold: font_desc.set_weight(Pango.Weight.BOLD)
            if text_obj.is_italic: font_desc.set_style(Pango.Style.ITALIC)
            font_desc.set_absolute_size(int(text_obj.font_size * Pango.SCALE))
            layout.set_font_description(font_desc)
            layout.set_text(text_obj.text, -1)
            align = getattr(text_obj, 'alignment', 'left')
            box_w = (x2 - x1)
            if box_w > 0:
                nat_pw, _ = layout.get_size()
                w_to_set = max(box_w, nat_pw / Pango.SCALE)
                layout.set_width(int(w_to_set * Pango.SCALE))
                if align == 'center':
                    layout.set_alignment(Pango.Alignment.CENTER)
                elif align == 'right':
                    layout.set_alignment(Pango.Alignment.RIGHT)
                elif align == 'justify':
                    layout.set_justify(True)
            r, g, b = text_obj.color
            cr.set_source_rgba(r, g, b, 1.0)
            
            attr_list = Pango.AttrList()

            if getattr(text_obj, 'link_url', None):
                color_attr = Pango.attr_foreground_new(0, 0, int((238.0 / 255.0) * 65535))
                color_attr.start_index = 0
                color_attr.end_index = 65535
                attr_list.change(color_attr)
                u_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                u_attr.start_index = 0
                u_attr.end_index = 65535
                attr_list.change(u_attr)
            
            for match in re.finditer(r'(https?://[^\s]+|www\.[^\s]+)', text_obj.text):
                start_byte = len(text_obj.text[:match.start()].encode('utf-8'))
                end_byte = len(text_obj.text[:match.end()].encode('utf-8'))
                
                color_attr = Pango.attr_foreground_new(0, int(0.33*65535), int(0.8*65535))
                color_attr.start_index = start_byte
                color_attr.end_index = end_byte
                attr_list.change(color_attr)
                
                underline_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                underline_attr.start_index = start_byte
                underline_attr.end_index = end_byte
                attr_list.change(underline_attr)
            
            if getattr(text_obj, 'is_underline', False):
                u_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                u_attr.start_index = 0
                u_attr.end_index = 65535 
                attr_list.change(u_attr)
            if getattr(text_obj, 'is_strikethrough', False):
                s_attr = Pango.attr_strikethrough_new(True)
                s_attr.start_index = 0
                s_attr.end_index = 65535
                attr_list.change(s_attr)
            
            if not self.view_mode and self.selected_text == text_obj and getattr(self, 'word_selection_mode', False):
                if hasattr(self, 'selected_word_start_char') and hasattr(self, 'selected_word_end_char'):
                    start_byte = len(text_obj.text[:self.selected_word_start_char].encode('utf-8'))
                    end_byte = len(text_obj.text[:self.selected_word_end_char].encode('utf-8'))
                    
                    bg_attr = Pango.attr_background_new(int(0.2*65535), int(0.6*65535), int(1.0*65535))
                    bg_attr.start_index = start_byte
                    bg_attr.end_index = end_byte
                    attr_list.insert(bg_attr)
                    
                    fg_attr = Pango.attr_foreground_new(65535, 65535, 65535)
                    fg_attr.start_index = start_byte
                    fg_attr.end_index = end_byte
                    attr_list.insert(fg_attr)
            
            layout.set_attributes(attr_list)
            cr.move_to(draw_x, draw_y)
            PangoCairo.show_layout(cr, layout)
            cr.restore()

        for img_obj in getattr(self, 'editable_images', []):
            if getattr(img_obj, 'page_number', None) != self.current_page_index:
                continue
            if getattr(img_obj, 'is_baked', False):
                continue
            if img_obj is self.dragged_object:
                continue
            if not getattr(img_obj, 'bbox', None) or not getattr(img_obj, 'image_bytes', None):
                continue
            x1, y1, x2, y2 = img_obj.bbox
            draw_w = x2 - x1
            draw_h = y2 - y1
            if draw_w <= 0 or draw_h <= 0:
                continue
            cr.save()
            rot = getattr(img_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = x1 + draw_w / 2.0
                cy = y1 + draw_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            try:
                loader = GdkPixbuf.PixbufLoader.new()
                loader.write(img_obj.image_bytes)
                loader.close()
                pixbuf = loader.get_pixbuf()
                if pixbuf:
                    cr.save()
                    cr.translate(x1, y1)
                    cr.scale(draw_w / pixbuf.get_width(), draw_h / pixbuf.get_height())
                    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
                    cr.paint()
                    cr.restore()
            except Exception:
                pass
            cr.restore()

        for shape in self.editable_shapes:
            if shape.page_number != self.current_page_index:
                continue
            if getattr(shape, 'is_baked', False):
                continue
            if shape is self.dragged_object:
                continue
            
            x1, y1, x2, y2 = shape.bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1
            
            if abs(draw_w) < 1.0 or abs(draw_h) < 1.0:
                continue
            
            cr.save()
            rot = getattr(shape, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = draw_x + draw_w / 2.0
                cy = draw_y + draw_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            if not shape.is_transparent:
                fill_r, fill_g, fill_b = shape.fill_color
                cr.set_source_rgba(fill_r, fill_g, fill_b, 1.0)
                if shape.shape_type == EditableShape.SHAPE_RECTANGLE:
                    cr.rectangle(draw_x, draw_y, draw_w, draw_h)
                    cr.fill()
                elif shape.shape_type == EditableShape.SHAPE_ELLIPSE:
                    cr.save()
                    cr.translate(draw_x + draw_w / 2.0, draw_y + draw_h / 2.0)
                    cr.scale(draw_w / 2.0, draw_h / 2.0)
                    cr.arc(0, 0, 1, 0, 2 * math.pi)
                    cr.restore()
                    cr.fill()
            
            stroke_r, stroke_g, stroke_b = shape.stroke_color
            cr.set_source_rgba(stroke_r, stroke_g, stroke_b, 1.0)
            cr.set_line_width(shape.stroke_width)
            
            if shape.shape_type == EditableShape.SHAPE_RECTANGLE:
                cr.rectangle(draw_x, draw_y, draw_w, draw_h)
                cr.stroke()
            elif shape.shape_type == EditableShape.SHAPE_ELLIPSE:
                cr.save()
                cr.translate(draw_x + draw_w / 2.0, draw_y + draw_h / 2.0)
                cr.scale(draw_w / 2.0, draw_h / 2.0)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.stroke()
            elif shape.shape_type == EditableShape.SHAPE_CHECKMARK:
                pts = shape.get_checkmark_points()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.move_to(pts[0][0], pts[0][1])
                for pt in pts[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            elif shape.shape_type == EditableShape.SHAPE_CROSS:
                lines = shape.get_cross_lines()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                for (p1, p2) in lines:
                    cr.move_to(p1[0], p1[1])
                    cr.line_to(p2[0], p2[1])
                cr.stroke()
            cr.restore()

        
        if self.temp_shape:
            x1, y1, x2, y2 = self.temp_shape.bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1
            
            stroke_r, stroke_g, stroke_b = self.temp_shape.stroke_color
            cr.set_source_rgba(stroke_r, stroke_g, stroke_b, 0.7)  
            cr.set_line_width(self.temp_shape.stroke_width)
            
            if self.temp_shape.shape_type == EditableShape.SHAPE_RECTANGLE:
                cr.rectangle(draw_x, draw_y, draw_w, draw_h)
                cr.stroke()
            elif self.temp_shape.shape_type == EditableShape.SHAPE_ELLIPSE:
                cr.save()
                cr.translate(draw_x + draw_w / 2.0, draw_y + draw_h / 2.0)
                cr.scale(draw_w / 2.0, draw_h / 2.0)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.stroke()
            elif self.temp_shape.shape_type == EditableShape.SHAPE_CHECKMARK:
                pts = self.temp_shape.get_checkmark_points()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.move_to(pts[0][0], pts[0][1])
                for pt in pts[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            elif self.temp_shape.shape_type == EditableShape.SHAPE_CROSS:
                lines = self.temp_shape.get_cross_lines()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                for (p1, p2) in lines:
                    cr.move_to(p1[0], p1[1])
                    cr.line_to(p2[0], p2[1])
                cr.stroke()

        if self.temp_image_bbox:
            x1, y1, x2, y2 = self.temp_image_bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1

            style_context = area.get_style_context()
            found_img, img_rgba = style_context.lookup_color("accent_color")
            if not found_img:
                found_img, img_rgba = style_context.lookup_color("theme_selected_bg_color")
            if not found_img:
                img_rgba = Gdk.RGBA()
                img_rgba.parse("#3584e4")

            cr.set_source_rgba(img_rgba.red, img_rgba.green, img_rgba.blue, 0.25)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(img_rgba.red, img_rgba.green, img_rgba.blue, 0.85)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([5.0 / self.zoom_level, 4.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

        if getattr(self, 'temp_form_field_rect', None) is not None:
            x1, y1, x2, y2 = self.temp_form_field_rect
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1

            style_context = area.get_style_context()
            found_col, col_rgba = style_context.lookup_color("accent_color")
            if not found_col:
                found_col, col_rgba = style_context.lookup_color("theme_selected_bg_color")
            if not found_col:
                col_rgba = Gdk.RGBA()
                col_rgba.parse("#3584e4")

            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.20)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.90)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([5.0 / self.zoom_level, 3.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

            field_type_name = getattr(self, 'form_builder_field_type', 'text').capitalize()
            if field_type_name == 'Combobox':
                field_type_name = 'Dropdown'
            badge_text = f"[{field_type_name}]"
            cr.save()
            font_sz = max(10.0 / self.zoom_level, 8.0)
            cr.set_font_size(font_sz)
            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.95)
            cr.move_to(draw_x + 4.0 / self.zoom_level, draw_y + font_sz + 2.0 / self.zoom_level)
            cr.show_text(badge_text)
            cr.restore()

        # Render editable strokes on current page
        for stroke in getattr(self, 'editable_strokes', []):
            if getattr(stroke, 'page_number', None) != self.current_page_index:
                continue
            if getattr(stroke, 'is_baked', False):
                continue
            if stroke is self.dragged_object:
                continue
            cr.save()
            rot = getattr(stroke, 'rotation', 0.0) % 360.0
            if rot != 0.0 and stroke.bbox:
                sx1, sy1, sx2, sy2 = stroke.bbox
                cx = (sx1 + sx2) / 2.0
                cy = (sy1 + sy2) / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            r, g, b = stroke.stroke_color
            opacity = getattr(stroke, 'opacity', 1.0)
            cr.set_source_rgba(r, g, b, opacity)
            cr.set_line_width(stroke.stroke_width)
            is_hl = getattr(stroke, 'tool_type', None) in ("highlighter", EditableStroke.TOOL_HIGHLIGHTER) or stroke.stroke_width >= 8.0
            if is_hl:
                cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                cr.set_line_join(cairo.LINE_JOIN_BEVEL)
            else:
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)

            if len(stroke.points) == 1:
                px, py = stroke.points[0]
                rad = max(stroke.stroke_width / 2.0, 1.0 / self.zoom_level)
                if is_hl:
                    cr.rectangle(px - rad, py - rad, rad * 2.0, rad * 2.0)
                else:
                    cr.arc(px, py, rad, 0, 2 * math.pi)
                cr.fill()
            else:
                p0 = stroke.points[0]
                cr.move_to(p0[0], p0[1])
                for pt in stroke.points[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            cr.restore()

        # Render live drawing temp stroke
        if getattr(self, 'temp_stroke', None) and self.temp_stroke.points:
            cr.save()
            r, g, b = self.temp_stroke.stroke_color
            opacity = getattr(self.temp_stroke, 'opacity', 1.0)
            cr.set_source_rgba(r, g, b, opacity)
            cr.set_line_width(self.temp_stroke.stroke_width)
            is_hl = getattr(self.temp_stroke, 'tool_type', None) in ("highlighter", EditableStroke.TOOL_HIGHLIGHTER) or self.tool_mode == "highlighter" or self.temp_stroke.stroke_width >= 8.0
            if is_hl:
                cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                cr.set_line_join(cairo.LINE_JOIN_BEVEL)
            else:
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)

            if len(self.temp_stroke.points) == 1:
                px, py = self.temp_stroke.points[0]
                rad = max(self.temp_stroke.stroke_width / 2.0, 1.0 / self.zoom_level)
                if is_hl:
                    cr.rectangle(px - rad, py - rad, rad * 2.0, rad * 2.0)
                else:
                    cr.arc(px, py, rad, 0, 2 * math.pi)
                cr.fill()
            else:
                p0 = self.temp_stroke.points[0]
                cr.move_to(p0[0], p0[1])
                for pt in self.temp_stroke.points[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            cr.restore()

        # Render AcroForm field overlays
        current_fields = [f for f in getattr(self, 'form_fields', []) if getattr(f, 'page_number', self.current_page_index) == self.current_page_index]
        if current_fields:
            is_design = (not self.view_mode and getattr(self, 'tool_mode', '') == "form_builder")
            pdf_handler.draw_acroform_overlay(
                cr,
                current_fields,
                self.zoom_level,
                active_field=(self.selected_form_field if self.view_mode else None),
                is_design_mode=is_design
            )

        selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                        self.selected_stroke or getattr(self, 'selected_form_field', None))
        if selected_obj and not self.dragged_object and not (
            isinstance(selected_obj, AcroFormField) and getattr(self, '_active_editing_form_field', None) == selected_obj
        ) and not (self.inline_editor_widget is not None and selected_obj == getattr(self, 'inline_editor_text_obj', None)):
            is_image = isinstance(selected_obj, EditableImage)
            style_context = area.get_style_context()
            color_name = "accent_color"
            default_color = "#3584e4"

            found, rgba = style_context.lookup_color("accent_color")
            if not found:
                found, rgba = style_context.lookup_color("theme_selected_bg_color")
            if not found:
                rgba = Gdk.RGBA()
                rgba.parse("#3584e4")

            x1, y1, x2, y2 = selected_obj.bbox
            if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
                text = selected_obj.text
                r1 = self.selected_word_start_char / max(len(text), 1)
                r2 = self.selected_word_end_char / max(len(text), 1)
                x1_word = x1 + (x2 - x1) * r1
                x2_word = x1 + (x2 - x1) * r2
                x1, x2 = x1_word, x2_word

            padding = 3.0 / self.zoom_level
            rect_x = x1 - padding
            rect_y = y1 - padding
            rect_w = (x2 - x1) + (2 * padding)
            rect_h = (y2 - y1) + (2 * padding)

            cr.save()
            rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = rect_x + rect_w / 2.0
                cy = rect_y + rect_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)

            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.95)
            cr.set_line_width((2.5 if is_image else 2.0) / self.zoom_level)
            if is_image:
                cr.set_dash([4.0 / self.zoom_level, 4.0 / self.zoom_level])

            radius = min(5.0 / self.zoom_level, rect_w / 2.0, rect_h / 2.0)
            cr.new_sub_path()
            cr.arc(rect_x + radius, rect_y + radius, radius, math.pi, 1.5 * math.pi)
            cr.arc(rect_x + rect_w - radius, rect_y + radius, radius, 1.5 * math.pi, 2.0 * math.pi)
            cr.arc(rect_x + rect_w - radius, rect_y + rect_h - radius, radius, 0, 0.5 * math.pi)
            cr.arc(rect_x + radius, rect_y + rect_h - radius, radius, 0.5 * math.pi, math.pi)
            cr.close_path()
            cr.stroke()

            # Stalk rotation handle
            is_form = isinstance(selected_obj, AcroFormField) or hasattr(selected_obj, 'field_name')
            if not isinstance(selected_obj, EditableText) and not is_form:
                stalk_len = 22.0 / self.zoom_level
                stalk_x = rect_x + rect_w / 2.0
                stalk_base_y = rect_y
                stalk_tip_y = rect_y - stalk_len
                rot_handle_r = 5.0 / self.zoom_level

                cr.save()
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.9)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.set_dash([])
                cr.move_to(stalk_x, stalk_base_y)
                cr.line_to(stalk_x, stalk_tip_y)
                cr.stroke()

                cr.arc(stalk_x, stalk_tip_y, rot_handle_r, 0, 2 * math.pi)
                cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                cr.fill_preserve()
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.stroke()
                cr.restore()

            is_text = isinstance(selected_obj, EditableText)
            if not is_text:
                handle_size = 8.0 / self.zoom_level
                handle_color_rgba = rgba
                
                handles = [
                    ("nw", rect_x, rect_y),                                   # top-left
                    ("ne", rect_x + rect_w, rect_y),                          # top-right
                    ("sw", rect_x, rect_y + rect_h),                          # bottom-left
                    ("se", rect_x + rect_w, rect_y + rect_h),                 # bottom-right
                    ("n", rect_x + rect_w / 2.0, rect_y),                     # top
                    ("s", rect_x + rect_w / 2.0, rect_y + rect_h),            # bottom
                    ("w", rect_x, rect_y + rect_h / 2.0),                     # left
                    ("e", rect_x + rect_w, rect_y + rect_h / 2.0),            # right
                ]
                
                for handle_name, handle_x, handle_y in handles:
                    cr.set_source_rgba(handle_color_rgba.red, handle_color_rgba.green, handle_color_rgba.blue, 1.0)
                    cr.rectangle(handle_x - handle_size / 2.0, handle_y - handle_size / 2.0, handle_size, handle_size)
                    cr.fill()
                    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                    cr.rectangle(handle_x - handle_size / 2.0, handle_y - handle_size / 2.0, handle_size, handle_size)
                    cr.set_line_width(1.0 / self.zoom_level)
                    cr.stroke()
            cr.restore()

        # Draw active scale calibration reference line or saved reference line
        calib_line = getattr(self, 'temp_calibration_line', None)
        active_calib = self.get_scale_calibration(self.current_page_index) if hasattr(self, 'get_scale_calibration') else None
        is_calib_tool = getattr(self, 'tool_mode', None) == "calibrate"
        
        if calib_line or (is_calib_tool and active_calib and active_calib.reference_line):
            line_to_draw = calib_line or active_calib.reference_line
            sx, sy, ex, ey = line_to_draw
            pt_len = math.hypot(ex - sx, ey - sy)
            if pt_len > 1.0:
                cr.save()
                is_temp = (calib_line is not None)
                if is_temp:
                    cr.set_source_rgba(0.0, 0.65, 0.95, 0.95)
                    cr.set_line_width(2.0 / self.zoom_level)
                else:
                    cr.set_source_rgba(0.0, 0.50, 0.85, 0.70)
                    cr.set_line_width(1.5 / self.zoom_level)
                    cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])

                # Main reference line
                cr.move_to(sx, sy)
                cr.line_to(ex, ey)
                cr.stroke()
                cr.set_dash([])

                # Perpendicular end ticks
                theta = math.atan2(ey - sy, ex - sx)
                perp = theta + math.pi / 2.0
                tick_h = 7.0 / self.zoom_level
                dx_p = tick_h * math.cos(perp)
                dy_p = tick_h * math.sin(perp)

                cr.move_to(sx - dx_p, sy - dy_p)
                cr.line_to(sx + dx_p, sy + dy_p)
                cr.stroke()

                cr.move_to(ex - dx_p, ey - dy_p)
                cr.line_to(ex + dx_p, ey + dy_p)
                cr.stroke()

                # Endpoint crosshair circles
                rad = 3.0 / self.zoom_level
                cr.arc(sx, sy, rad, 0, 2 * math.pi)
                cr.stroke()
                cr.arc(ex, ey, rad, 0, 2 * math.pi)
                cr.stroke()

                # Midpoint readout pill badge
                mx = (sx + ex) / 2.0
                my = (sy + ey) / 2.0
                badge_str = f"{pt_len:.1f} pt"
                if active_calib and active_calib.points_per_unit > 0:
                    badge_str += f" ({active_calib.format_distance(pt_len)})"

                cr.set_font_size(max(10.0 / self.zoom_level, 9.0))
                ext = cr.text_extents(badge_str)
                pad_x = 6.0 / self.zoom_level
                pad_y = 3.0 / self.zoom_level
                bw = ext.width + pad_x * 2.0
                bh = ext.height + pad_y * 2.0
                bx = mx - bw / 2.0
                by = my - bh / 2.0 - (12.0 / self.zoom_level)

                # Background pill
                cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
                cr.rectangle(bx, by, bw, bh)
                cr.fill()

                cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                cr.set_line_width(1.0 / self.zoom_level)
                cr.rectangle(bx, by, bw, bh)
                cr.stroke()

                # Text
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
                cr.show_text(badge_str)
                cr.restore()

        cr.restore()

        if self.view_mode and self.view_sel_rect:
            sx1, sy1, sx2, sy2 = self.view_sel_rect
            sel_dx = page_offset_x + sx1 * self.zoom_level
            sel_dy = page_offset_y + sy1 * self.zoom_level
            sel_dw = (sx2 - sx1) * self.zoom_level
            sel_dh = (sy2 - sy1) * self.zoom_level
            cr.save()
            cr.set_source_rgba(0.12, 0.47, 0.9, 0.25)
            cr.rectangle(sel_dx, sel_dy, sel_dw, sel_dh)
            cr.fill()
            cr.set_source_rgba(0.12, 0.47, 0.9, 0.85)
            cr.set_line_width(1.5)
            cr.rectangle(sel_dx, sel_dy, sel_dw, sel_dh)
            cr.stroke()
            cr.restore()

    def _visual_to_unrotated_page_coords(self, vis_x, vis_y):
        """Convert visual page coordinates to unrotated PDF cropbox coordinates."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return vis_x, vis_y
        page = self.doc[self.current_page_index]
        if (page.rotation % 360) == 0:
            return vis_x, vis_y
        p = fitz.Point(vis_x, vis_y) * (~page.rotation_matrix)
        return p.x, p.y

    def _unrotated_to_visual_page_coords(self, unrot_x, unrot_y):
        """Convert unrotated PDF cropbox coordinates to visual page coordinates."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return unrot_x, unrot_y
        page = self.doc[self.current_page_index]
        if (page.rotation % 360) == 0:
            return unrot_x, unrot_y
        p = fitz.Point(unrot_x, unrot_y) * page.rotation_matrix
        return p.x, p.y

    def _visual_to_unrotated_delta(self, dx, dy):
        """Convert a visual delta vector to an unrotated page delta vector."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return dx, dy
        page = self.doc[self.current_page_index]
        if (page.rotation % 360) == 0:
            return dx, dy
        inv_mat = ~page.rotation_matrix
        p0 = fitz.Point(0, 0) * inv_mat
        p1 = fitz.Point(dx, dy) * inv_mat
        return p1.x - p0.x, p1.y - p0.y

    def _find_text_at_pos(self, page_x, page_y):
        """Find text at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        for text_obj in reversed(self.editable_texts):
            if getattr(text_obj, 'page_number', self.current_page_index) != self.current_page_index:
                continue
            if not text_obj.bbox: continue
            x1, y1, x2, y2 = text_obj.bbox
            rot = getattr(text_obj, 'rotation', 0.0) % 360.0
            px, py = page_x, page_y
            if rot != 0.0:
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
            tolerance = 2 / self.zoom_level
            if (x1 - tolerance) <= px <= (x2 + tolerance) and \
               (y1 - tolerance) <= py <= (y2 + tolerance):
                return text_obj
        return None

    def _find_image_at_pos(self, page_x, page_y):
        """Find image at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        for img_obj in reversed(self.editable_images):
            if getattr(img_obj, 'page_number', self.current_page_index) != self.current_page_index:
                continue
            if not img_obj.bbox: continue
            x1, y1, x2, y2 = img_obj.bbox
            rot = getattr(img_obj, 'rotation', 0.0) % 360.0
            px, py = page_x, page_y
            if rot != 0.0:
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
            if x1 <= px <= x2 and y1 <= py <= y2:
                return img_obj
        return None

    def _find_shape_at_pos(self, page_x, page_y):
        """Find shape at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        for shape_obj in reversed(self.editable_shapes):
            if shape_obj.page_number != self.current_page_index:
                continue
            if not shape_obj.bbox: 
                continue
            x1, y1, x2, y2 = shape_obj.bbox
            rot = getattr(shape_obj, 'rotation', 0.0) % 360.0
            px, py = page_x, page_y
            if rot != 0.0:
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
            tolerance = 3 / self.zoom_level
            if (x1 - tolerance) <= px <= (x2 + tolerance) and \
               (y1 - tolerance) <= py <= (y2 + tolerance):
                return shape_obj
        return None

    def _find_stroke_at_pos(self, page_x, page_y):
        """Find stroke at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        for stroke in reversed(getattr(self, 'editable_strokes', [])):
            if stroke.page_number != self.current_page_index:
                continue
            if not stroke.bbox:
                continue
            x1, y1, x2, y2 = stroke.bbox
            rot = getattr(stroke, 'rotation', 0.0) % 360.0
            px, py = page_x, page_y
            if rot != 0.0:
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
            tolerance = max(stroke.stroke_width, 8.0) / self.zoom_level
            if (x1 - tolerance) <= px <= (x2 + tolerance) and \
               (y1 - tolerance) <= py <= (y2 + tolerance):
                return stroke
        return None

    def _find_form_field_at_pos(self, page_x, page_y):
        """Find interactive form field at page position."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        for field in reversed(getattr(self, 'form_fields', [])):
            if getattr(field, 'page_number', self.current_page_index) != self.current_page_index:
                continue
            x1, y1, x2, y2 = field.rect
            min_x, max_x = min(x1, x2), max(x1, x2)
            min_y, max_y = min(y1, y2), max(y1, y2)
            tolerance = 3.0 / getattr(self, 'zoom_level', 1.0)
            if (min_x - tolerance) <= page_x <= (max_x + tolerance) and (min_y - tolerance) <= page_y <= (max_y + tolerance):
                return field
        return None

    def _compute_form_field_screen_geometry(self, field):
        """Compute pixel position and size for an AcroFormField on the overlay matching canvas centering."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return 0, 0, 0, 0
        alloc_w = self.pdf_view.get_allocated_width() if hasattr(self, 'pdf_view') and self.pdf_view else 0
        alloc_h = self.pdf_view.get_allocated_height() if hasattr(self, 'pdf_view') and self.pdf_view else 0
        da_w = alloc_w if alloc_w > 0 else self.current_pdf_page_width
        da_h = alloc_h if alloc_h > 0 else self.current_pdf_page_height
        page_offset_x = max(0.0, (da_w - self.current_pdf_page_width) / 2.0)
        page_offset_y = max(0.0, (da_h - self.current_pdf_page_height) / 2.0)

        try:
            page = self.doc[field.page_number]
            vis_rect = (fitz.Rect(field.rect) * page.rotation_matrix).normalize()
        except Exception:
            vis_rect = fitz.Rect(field.rect).normalize()

        wx = int(page_offset_x + vis_rect.x0 * self.zoom_level)
        wy = int(page_offset_y + vis_rect.y0 * self.zoom_level)
        ww = max(1, int(vis_rect.width * self.zoom_level))
        wh = max(1, int(vis_rect.height * self.zoom_level))

        if getattr(field, 'field_type', 'text') in ("checkbox", "radio"):
            ww = max(18, ww)
            wh = max(18, wh)
        else:
            ww = max(30, ww)
            wh = max(18, wh)

        return wx, wy, ww, wh

    def _clear_form_field_overlays(self):
        """Remove all existing interactive form field overlay widgets."""
        active_container = getattr(self, '_active_form_field_editor_container', None)
        if active_container and hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            try:
                self.pdf_overlay.remove_overlay(active_container)
            except Exception:
                pass
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None
        self._active_editing_form_field = None
        if hasattr(self, 'pdf_overlay') and self.pdf_overlay and hasattr(self, '_form_field_overlay_widgets'):
            for item in list(self._form_field_overlay_widgets.values()):
                container = item.get("container")
                if container:
                    try:
                        self.pdf_overlay.remove_overlay(container)
                    except Exception:
                        pass
        if hasattr(self, '_form_field_overlay_widgets'):
            self._form_field_overlay_widgets.clear()

    def _update_form_field_overlay_positions(self):
        """Recalculate and update position and size of active ephemeral or persistent form field overlay widgets."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return

        # Update active ephemeral editor if open
        if getattr(self, '_active_form_field_editor_container', None) and getattr(self, '_active_editing_form_field', None):
            field = self._active_editing_form_field
            container = self._active_form_field_editor_container
            wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)
            container.set_margin_start(wx)
            container.set_margin_top(wy)
            container.set_size_request(ww, wh)

        if not hasattr(self, '_form_field_overlay_widgets') or not self._form_field_overlay_widgets:
            return

        for entry_data in list(self._form_field_overlay_widgets.values()):
            field = entry_data.get("field")
            container = entry_data.get("container")
            if not field or not container or container == getattr(self, '_active_form_field_editor_container', None):
                continue
            wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)
            container.set_margin_start(wx)
            container.set_margin_top(wy)
            container.set_size_request(ww, wh)

    def _sync_form_field_value(self, field, new_value, record_undo=False, old_val_override=None):
        """Update field value in memory and in PyMuPDF doc, marking document modified."""
        if getattr(self, '_syncing_form_field', False):
            return
        old_val = old_val_override if old_val_override is not None else field.value
        if old_val == new_value:
            return

        self._syncing_form_field = True
        try:
            field.set_value(new_value)
            if self.doc:
                pdf_handler.update_acroform_field_value(
                    self.doc,
                    field.page_number,
                    field.xref,
                    new_value
                )
            self.document_modified = True
            if record_undo:
                cmd = EditFormFieldCommand(self, field, old_val, new_value)
                self.undo_manager.add_command(cmd)
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            self._update_ui_state()
        finally:
            self._syncing_form_field = False

    def _refresh_form_field_widget_value(self, field):
        """Update displayed value in overlay widget to match field.value without feedback loop."""
        if not hasattr(self, '_form_field_overlay_widgets') or not field:
            return
        fid = getattr(field, 'field_id', None)
        entry_data = self._form_field_overlay_widgets.get(fid)
        if not entry_data:
            for data in self._form_field_overlay_widgets.values():
                if getattr(data.get("field"), 'xref', -1) == getattr(field, 'xref', -2):
                    entry_data = data
                    break
        if not entry_data:
            return

        widget = entry_data.get("widget")
        if not widget:
            return

        self._syncing_form_field = True
        try:
            entry_data["current_val"] = field.value
            entry_data["initial_val"] = field.value
            if isinstance(widget, Gtk.Entry):
                val_str = str(field.value if field.value is not None else "")
                if widget.get_text() != val_str:
                    widget.set_text(val_str)
            elif isinstance(widget, Gtk.TextView):
                val_str = str(field.value if field.value is not None else "")
                buf = widget.get_buffer()
                start, end = buf.get_bounds()
                if buf.get_text(start, end, True) != val_str:
                    buf.set_text(val_str)
            elif isinstance(widget, Gtk.CheckButton):
                active_bool = bool(field.is_checked)
                if widget.get_active() != active_bool:
                    widget.set_active(active_bool)
            elif isinstance(widget, Gtk.DropDown):
                export_items = entry_data.get("export_items", [])
                display_items = entry_data.get("display_items", [])
                val_str = str(field.value if field.value is not None else "")
                target_idx = None
                if val_str in export_items:
                    target_idx = export_items.index(val_str)
                elif val_str in display_items:
                    target_idx = display_items.index(val_str)
                if target_idx is not None and widget.get_selected() != target_idx:
                    widget.set_selected(target_idx)
        finally:
            self._syncing_form_field = False

    def _commit_pending_form_field_edit(self):
        """Commit any uncommitted text changes in active form field overlays."""
        if not hasattr(self, '_form_field_overlay_widgets') or not self._form_field_overlay_widgets:
            return
        for entry_data in list(self._form_field_overlay_widgets.values()):
            field = entry_data.get("field")
            cur = entry_data.get("current_val")
            init = entry_data.get("initial_val")
            if field and cur is not None and cur != init:
                cmd = EditFormFieldCommand(self, field, init, cur)
                self.undo_manager.add_command(cmd)
                entry_data["initial_val"] = cur

    def _on_form_builder_type_changed(self, dropdown, pspec):
        """Update active form field type when selected in toolbar dropdown."""
        idx = dropdown.get_selected()
        mapping = ["text", "checkbox", "combobox"]
        if 0 <= idx < len(mapping):
            self.form_builder_field_type = mapping[idx]
        if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
            self.form_builder_multiline_check.set_visible(self.form_builder_field_type == "text")
        if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
            self.form_builder_options_box.set_visible(self.form_builder_field_type == "combobox")

    def _get_next_form_field_name(self, field_type: str) -> str:
        """Generate a guaranteed unique field name for a newly created form field."""
        prefix_map = {
            "text": "text_field",
            "checkbox": "check_box",
            "combobox": "combo_box",
            "choice": "combo_box",
            "listbox": "list_box",
            "signature": "signature_field"
        }
        prefix = prefix_map.get(field_type, "form_field")
        existing_names = set()
        if self.doc and not getattr(self.doc, "is_closed", False):
            for p in self.doc:
                for w in p.widgets():
                    if getattr(w, 'field_name', None):
                        existing_names.add(w.field_name)

        idx = 1
        while f"{prefix}_{idx}" in existing_names:
            idx += 1
        return f"{prefix}_{idx}"

    def _create_new_form_field(self, rect: tuple):
        """Create a new AcroForm interactive widget on current page and set up undo history."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            return

        field_type = getattr(self, 'form_builder_field_type', 'text')
        user_name = ""
        if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry:
            user_name = self.form_builder_name_entry.get_text().strip()

        field_name = user_name or self._get_next_form_field_name(field_type)

        if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry and user_name:
            self.form_builder_name_entry.set_text("")

        is_multiline = False
        default_val = None
        choices = None

        if field_type == "text":
            if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                is_multiline = self.form_builder_multiline_check.get_active()
            default_val = ""
        elif field_type == "checkbox":
            default_val = False
        elif field_type in ("combobox", "choice"):
            opt_str = ""
            if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
                opt_str = self.form_builder_options_entry.get_text().strip()
            if opt_str:
                choices = [c.strip() for c in opt_str.split(",") if c.strip()]
            if not choices:
                choices = ["Option 1", "Option 2", "Option 3"]
            default_val = choices[0] if choices else "Option 1"

        command = AddFormFieldCommand(
            self,
            self.current_page_index,
            field_type,
            rect,
            field_name,
            default_value=default_val,
            choice_values=choices,
            is_multiline=is_multiline
        )
        command.execute()
        self.undo_manager.add_command(command)
        self.document_modified = True

        add_label = (hasattr(self, 'form_builder_add_label_check') and 
                     self.form_builder_add_label_check and 
                     self.form_builder_add_label_check.get_active())
        label_text = ""
        if hasattr(self, 'form_builder_label_entry') and self.form_builder_label_entry:
            label_text = self.form_builder_label_entry.get_text().strip()

        if add_label or label_text:
            if not label_text:
                label_text = f"{field_name}:"
            x1, y1, x2, y2 = rect
            h = y2 - y1
            if field_type == "checkbox":
                lbl_x = x2 + 8.0
                lbl_y = y1 + (h / 2.0) - 7.0
            else:
                lbl_x = x1
                lbl_y = max(4.0, y1 - 18.0)

            font_size = 11.0
            lbl_obj = EditableText(
                x=lbl_x,
                y=lbl_y,
                text=label_text,
                font_size=font_size,
                color=(0.1, 0.1, 0.1),
                is_new=True,
                baseline=lbl_y + (font_size * 0.9)
            )
            lbl_obj.font_family_base = "Liberation Sans"
            lbl_obj.page_number = self.current_page_index
            lbl_cmd = AddObjectCommand(self, lbl_obj)
            lbl_cmd.execute()
            self.undo_manager.add_command(lbl_cmd)

        new_field = pdf_handler.get_acroform_field(self.doc, self.current_page_index, field_name)
        if new_field:
            self.selected_form_field = new_field
            self._update_form_builder_controls_for_selected()
            self._update_form_field_overlay_interactivity()

    def _update_form_builder_controls_for_selected(self):
        """Synchronize toolbar controls with selected form field or reset to defaults."""
        self._updating_form_builder_ui = True
        try:
            if getattr(self, 'selected_form_field', None):
                ftype = getattr(self.selected_form_field, 'field_type', 'text').lower()
                if ftype in ("text", "tx"):
                    if hasattr(self, 'form_builder_type_dropdown') and self.form_builder_type_dropdown:
                        self.form_builder_type_dropdown.set_selected(0)
                    self.form_builder_field_type = "text"
                    if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                        self.form_builder_multiline_check.set_visible(True)
                        self.form_builder_multiline_check.set_active(getattr(self.selected_form_field, 'is_multiline', False))
                    if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                        self.form_builder_options_box.set_visible(False)
                elif ftype in ("checkbox", "check", "cb"):
                    if hasattr(self, 'form_builder_type_dropdown') and self.form_builder_type_dropdown:
                        self.form_builder_type_dropdown.set_selected(1)
                    self.form_builder_field_type = "checkbox"
                    if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                        self.form_builder_multiline_check.set_visible(False)
                    if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                        self.form_builder_options_box.set_visible(False)
                elif ftype in ("combobox", "choice", "dropdown", "ch", "listbox"):
                    if hasattr(self, 'form_builder_type_dropdown') and self.form_builder_type_dropdown:
                        self.form_builder_type_dropdown.set_selected(2)
                    self.form_builder_field_type = "combobox"
                    if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                        self.form_builder_multiline_check.set_visible(False)
                    if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                        self.form_builder_options_box.set_visible(True)
                    if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
                        c_vals = getattr(self.selected_form_field, 'choice_values', []) or []
                        flat_choices = []
                        for c in c_vals:
                            if isinstance(c, (list, tuple)):
                                flat_choices.append(str(c[1] if len(c) > 1 else c[0]))
                            else:
                                flat_choices.append(str(c))
                        self.form_builder_options_entry.set_text(", ".join(flat_choices))
                if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry:
                    self.form_builder_name_entry.set_text(getattr(self.selected_form_field, 'field_name', ''))
                if hasattr(self, 'form_builder_delete_button') and self.form_builder_delete_button:
                    self.form_builder_delete_button.set_sensitive(True)
            else:
                next_name = self._get_next_form_field_name(getattr(self, 'form_builder_field_type', 'text'))
                if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry:
                    self.form_builder_name_entry.set_text(next_name)
                if hasattr(self, 'form_builder_delete_button') and self.form_builder_delete_button:
                    self.form_builder_delete_button.set_sensitive(False)
                if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                    self.form_builder_options_box.set_visible(getattr(self, 'form_builder_field_type', 'text') == 'combobox')
        finally:
            self._updating_form_builder_ui = False

    def _on_form_builder_options_changed(self, entry):
        """Handle editing comma-separated choices for selected combobox."""
        if getattr(self, '_updating_form_builder_ui', False):
            return
        if not getattr(self, 'selected_form_field', None) or not self.doc:
            return
        ftype = getattr(self.selected_form_field, 'field_type', '').lower()
        if ftype not in ("combobox", "choice", "dropdown", "ch", "listbox"):
            return
        text = entry.get_text()
        new_choices = [c.strip() for c in text.split(",") if c.strip()]
        if not new_choices:
            return
        old_choices = getattr(self.selected_form_field, 'choice_values', []) or []
        if new_choices == old_choices:
            return
        command = EditFormFieldChoicesCommand(self, self.selected_form_field, old_choices, new_choices)
        command.execute()
        self.undo_manager.add_command(command)
        self.document_modified = True
        self._update_tab_dirty_state()

    def _on_form_builder_edit_options_clicked(self, button):
        """Open a dialog allowing user to edit choices line by line."""
        current_text = ""
        if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
            current_text = self.form_builder_options_entry.get_text().strip()
        if not current_text and getattr(self, 'selected_form_field', None):
            c_vals = getattr(self.selected_form_field, 'choice_values', []) or []
            flat_choices = []
            for c in c_vals:
                if isinstance(c, (list, tuple)):
                    flat_choices.append(str(c[1] if len(c) > 1 else c[0]))
                else:
                    flat_choices.append(str(c))
            current_text = ", ".join(flat_choices)
        
        initial_lines = [s.strip() for s in current_text.split(",") if s.strip()] if current_text else ["Option 1", "Option 2", "Option 3"]

        dialog = Adw.Window()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_destroy_with_parent(True)

        clean_title = _("form_field_edit_options_title").replace(":", "").strip()
        dialog.set_title(clean_title)
        dialog.set_default_size(440, 420)
        dialog.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(main_box)

        header = Adw.HeaderBar()
        cancel_btn = Gtk.Button(label=_("btn_cancel"))
        cancel_btn.connect("clicked", lambda b: dialog.close())
        header.pack_start(cancel_btn)

        apply_btn = Gtk.Button(label=_("btn_apply"))
        apply_btn.add_css_class("suggested-action")
        header.pack_end(apply_btn)
        main_box.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=400)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        clamp.set_child(content_box)

        pref_group = Adw.PreferencesGroup()
        pref_group.set_title(_("form_field_options_label").replace(":", "").strip())
        pref_group.set_description(clean_title)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")

        inner_scroll = Gtk.ScrolledWindow()
        inner_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inner_scroll.set_min_content_height(200)
        inner_scroll.set_vexpand(True)

        tv = Gtk.TextView()
        tv.set_top_margin(12)
        tv.set_bottom_margin(12)
        tv.set_left_margin(14)
        tv.set_right_margin(14)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv_buf = tv.get_buffer()
        tv_buf.set_text("\n".join(initial_lines))
        inner_scroll.set_child(tv)
        card.append(inner_scroll)
        pref_group.add(card)
        content_box.append(pref_group)

        tip_lbl = Gtk.Label(label=_("form_field_options_tip"))
        tip_lbl.add_css_class("dim-label")
        tip_lbl.add_css_class("caption")
        tip_lbl.set_halign(Gtk.Align.START)
        content_box.append(tip_lbl)

        def _on_apply(b):
            start, end = tv_buf.get_bounds()
            text_val = tv_buf.get_text(start, end, True)
            new_opts = [line.strip() for line in text_val.splitlines() if line.strip()]
            if not new_opts:
                new_opts = ["Option 1"]
            joined = ", ".join(new_opts)
            if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
                self.form_builder_options_entry.set_text(joined)
            if getattr(self, 'selected_form_field', None):
                old_opts = getattr(self.selected_form_field, 'choice_values', []) or []
                if new_opts != old_opts:
                    cmd = EditFormFieldChoicesCommand(self, self.selected_form_field, old_opts, new_opts)
                    cmd.execute()
                    self.undo_manager.add_command(cmd)
                    self.document_modified = True
                    self._update_tab_dirty_state()
            dialog.close()

        apply_btn.connect("clicked", _on_apply)

        key_ctrl = Gtk.EventControllerKey()
        def _on_key(ctrl, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                dialog.close()
                return True
            elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and (state & Gdk.ModifierType.CONTROL_MASK):
                _on_apply(None)
                return True
            return False
        key_ctrl.connect("key-pressed", _on_key)
        dialog.add_controller(key_ctrl)

        dialog.present()

    def _on_form_builder_name_changed(self, entry):
        """Handle user editing the field name entry for the selected form field."""
        if getattr(self, '_updating_form_builder_ui', False):
            return
        if not getattr(self, 'selected_form_field', None) or not self.doc:
            return
        new_name = entry.get_text().strip()
        old_name = getattr(self.selected_form_field, 'field_name', '')
        if not new_name or new_name == old_name:
            return
        self.selected_form_field.field_name = new_name
        try:
            page = self.doc.load_page(getattr(self.selected_form_field, 'page_number', self.current_page_index))
            for w in page.widgets():
                if getattr(w, 'xref', None) == getattr(self.selected_form_field, 'xref', None) or getattr(w, 'field_name', None) == old_name:
                    w.field_name = new_name
                    w.update()
                    break
            self.document_modified = True
            self._update_tab_dirty_state()
        except Exception as e:
            print(f"Error updating form field name: {e}")

    def _on_form_builder_multiline_toggled(self, check):
        """Handle user toggling multiline checkbutton for selected form field."""
        if getattr(self, '_updating_form_builder_ui', False):
            return
        if not getattr(self, 'selected_form_field', None) or not self.doc:
            return
        if getattr(self.selected_form_field, 'field_type', 'text') != 'text':
            return
        is_multi = check.get_active()
        if getattr(self.selected_form_field, 'is_multiline', False) == is_multi:
            return
        self.selected_form_field.is_multiline = is_multi
        try:
            page = self.doc.load_page(getattr(self.selected_form_field, 'page_number', self.current_page_index))
            for w in page.widgets():
                if getattr(w, 'xref', None) == getattr(self.selected_form_field, 'xref', None) or getattr(w, 'field_name', None) == self.selected_form_field.field_name:
                    if is_multi:
                        w.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
                    else:
                        w.field_flags &= ~fitz.PDF_TX_FIELD_IS_MULTILINE
                    w.update()
                    break
            self.document_modified = True
            self._update_tab_dirty_state()
            self._load_acroform_fields_for_page(self.current_page_index)
        except Exception as e:
            print(f"Error updating multiline flag: {e}")

    def _on_form_builder_delete_clicked(self, button):
        """Handle clicking delete button in Form Builder toolbar."""
        self._delete_selected_form_field()

    def _delete_selected_form_field(self):
        """Delete currently selected form field with confirmation and undo support."""
        if not getattr(self, 'selected_form_field', None):
            return
        field = self.selected_form_field
        self._handle_delete_with_confirmation(field, "delete_form_field_confirm")

    def _get_overlay_for_field(self, field):
        """Retrieve overlay entry dictionary for a given field."""
        if not field or not hasattr(self, '_form_field_overlay_widgets'):
            return None
        fid = getattr(field, 'field_id', None)
        ed = self._form_field_overlay_widgets.get(fid)
        if not ed:
            for d in self._form_field_overlay_widgets.values():
                if (d.get("field") == field or 
                    getattr(d.get("field"), 'xref', None) == getattr(field, 'xref', -1) or
                    getattr(d.get("field"), 'field_name', None) == getattr(field, 'field_name', None)):
                    return d
        return ed

    def _open_form_field_editor(self, field):
        """Open in-place editor or toggle field upon view-mode activation."""
        if not field:
            return
        self.selected_form_field = field

        # Form filling is only enabled in View Mode!
        if not getattr(self, 'view_mode', False) and not getattr(self, '_enable_persistent_form_overlays', False):
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        ftype = getattr(field, 'field_type', 'text').lower()
        if ftype in ("checkbox", "check", "cb"):
            if not getattr(field, 'is_read_only', False):
                old_val = field.value
                new_val = not bool(field.is_checked)
                self._sync_form_field_value(field, new_val, record_undo=True, old_val_override=old_val)
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        if ftype == "radio":
            if not getattr(field, 'is_read_only', False):
                old_val = field.value
                self._sync_form_field_value(field, True, record_undo=True, old_val_override=old_val)
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        if ftype in ("combobox", "choice", "dropdown", "ch", "listbox"):
            if not getattr(field, 'is_read_only', False):
                self._open_form_field_dropdown_popover(field)
            self._update_form_builder_controls_for_selected()
            return

        # Handle persistent overlay if one exists in legacy mode
        entry_data = self._get_overlay_for_field(field)
        if entry_data and entry_data.get("widget") and entry_data.get("container") != getattr(self, '_active_form_field_editor_container', None):
            self._active_editing_form_field = field
            container = entry_data.get("container")
            if container and hasattr(container, "set_can_target"):
                container.set_can_target(True)
            w = entry_data["widget"]
            try:
                w.grab_focus()
                if isinstance(w, Gtk.Entry):
                    w.select_region(0, -1)
            except Exception:
                pass
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        # Text field: spawn ephemeral in-place editor over canvas
        if getattr(field, 'is_read_only', False):
            return

        self._close_active_form_field_editor()
        self._active_editing_form_field = field
        self._active_form_field_initial_val = field.value

        wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)

        if getattr(field, 'is_multiline', False):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.add_css_class("acroform-frame")
            scroll.set_halign(Gtk.Align.START)
            scroll.set_valign(Gtk.Align.START)
            scroll.set_margin_start(wx)
            scroll.set_margin_top(wy)
            scroll.set_size_request(ww, wh)

            tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
            tv.add_css_class("acroform-textview")
            buf = tv.get_buffer()
            buf.set_text(str(field.value if field.value is not None else ""))
            scroll.set_child(tv)
            container = scroll
            widget = tv
        else:
            entry = Gtk.Entry()
            entry.add_css_class("acroform-entry")
            if getattr(field, 'is_password', False):
                entry.set_visibility(False)
            if getattr(field, 'max_length', 0) > 0:
                entry.set_max_length(field.max_length)
            entry.set_text(str(field.value if field.value is not None else ""))
            entry.set_halign(Gtk.Align.START)
            entry.set_valign(Gtk.Align.START)
            entry.set_margin_start(wx)
            entry.set_margin_top(wy)
            entry.set_size_request(ww, wh)
            container = entry
            widget = entry

        entry_data = {
            "field": field,
            "container": container,
            "widget": widget,
            "initial_val": field.value,
            "current_val": field.value,
        }
        self._form_field_overlay_widgets[field.field_id] = entry_data
        self._active_form_field_editor_container = container
        self._active_form_field_editor_widget = widget

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", lambda *a: self._close_active_form_field_editor())
        widget.add_controller(focus_ctrl)

        key_ctrl = Gtk.EventControllerKey()
        def _on_key(ctrl, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                self._cancel_active_form_field_editor()
                return True
            elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not getattr(field, 'is_multiline', False):
                self._close_active_form_field_editor()
                return True
            return False
        key_ctrl.connect("key-pressed", _on_key)
        widget.add_controller(key_ctrl)

        if isinstance(widget, Gtk.Entry):
            widget.connect("activate", lambda *a: self._close_active_form_field_editor())

        if hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            self.pdf_overlay.add_overlay(container)

        try:
            widget.grab_focus()
            if isinstance(widget, Gtk.Entry):
                widget.select_region(0, -1)
        except Exception:
            pass

        self._update_form_builder_controls_for_selected()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _close_active_form_field_editor(self):
        """Close active in-place form field editor, save value, and remove ephemeral widget."""
        if getattr(self, '_active_editing_form_field', None) is None:
            return
        active_field = self._active_editing_form_field
        init_val = getattr(self, '_active_form_field_initial_val', active_field.value)
        widget = getattr(self, '_active_form_field_editor_widget', None)

        entry_data = self._get_overlay_for_field(active_field)
        if entry_data and not getattr(self, '_active_form_field_editor_container', None):
            cur = entry_data.get("current_val", active_field.value)
            init = entry_data.get("initial_val", active_field.value)
            if cur != init:
                cmd = EditFormFieldCommand(self, active_field, init, cur)
                self.undo_manager.add_command(cmd)
                entry_data["initial_val"] = cur
            for ed in getattr(self, '_form_field_overlay_widgets', {}).values():
                c = ed.get("container")
                if c and hasattr(c, "set_can_target"):
                    c.set_can_target(bool(getattr(self, 'view_mode', False)))
            self._active_editing_form_field = None
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.grab_focus()
                self.pdf_view.queue_draw()
            return

        new_val = active_field.value
        if isinstance(widget, Gtk.Entry):
            new_val = widget.get_text()
        elif isinstance(widget, Gtk.TextView):
            buf = widget.get_buffer()
            start, end = buf.get_bounds()
            new_val = buf.get_text(start, end, True)

        container = getattr(self, '_active_form_field_editor_container', None)
        if container and hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            try:
                self.pdf_overlay.remove_overlay(container)
            except Exception:
                pass

        fid = getattr(active_field, 'field_id', None)
        if fid and fid in self._form_field_overlay_widgets:
            del self._form_field_overlay_widgets[fid]

        self._active_editing_form_field = None
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None

        if new_val != init_val:
            self._sync_form_field_value(active_field, new_val, record_undo=True, old_val_override=init_val)

        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.grab_focus()
            self.pdf_view.queue_draw()

    def _cancel_active_form_field_editor(self):
        """Cancel active in-place editing without saving changes."""
        if getattr(self, '_active_editing_form_field', None) is None:
            return
        container = getattr(self, '_active_form_field_editor_container', None)
        if container and hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            try:
                self.pdf_overlay.remove_overlay(container)
            except Exception:
                pass
        fid = getattr(self._active_editing_form_field, 'field_id', None)
        if fid and fid in self._form_field_overlay_widgets:
            del self._form_field_overlay_widgets[fid]
        self._active_editing_form_field = None
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.grab_focus()
            self.pdf_view.queue_draw()

    def _open_form_field_dropdown_popover(self, field):
        """Open a native GTK Popover menu to select dropdown choices without permanent overlay widgets."""
        if not field:
            return
        self.selected_form_field = field

        wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)

        popover = Gtk.Popover()
        popover.set_parent(self.pdf_view)
        rect = Gdk.Rectangle()
        rect.x = wx
        rect.y = wy
        rect.width = ww
        rect.height = wh
        popover.set_pointing_to(rect)
        popover.set_position(Gtk.PositionType.BOTTOM)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)

        raw_choices = getattr(field, 'choice_values', []) or []
        if not raw_choices:
            raw_choices = ["Option 1", "Option 2", "Option 3"]

        for item in raw_choices:
            if isinstance(item, (list, tuple)):
                exp_val = str(item[0]) if len(item) > 0 else ""
                disp_val = str(item[1]) if len(item) > 1 else exp_val
            else:
                exp_val = str(item)
                disp_val = exp_val

            btn = Gtk.Button(label=disp_val)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            if exp_val == field.value:
                btn.add_css_class("suggested-action")

            def _on_choice_picked(b, val=exp_val):
                popover.popdown()
                old_val = field.value
                self._sync_form_field_value(field, val, record_undo=True, old_val_override=old_val)
                if hasattr(self, 'pdf_view') and self.pdf_view:
                    self.pdf_view.queue_draw()

            btn.connect("clicked", _on_choice_picked)
            box.append(btn)

        scroll.set_child(box)
        popover.set_child(scroll)

        def _on_closed(p):
            GLib.idle_add(p.unparent)

        popover.connect("closed", _on_closed)
        popover.popup()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _update_form_field_overlay_interactivity(self):
        """Update whether form field overlays capture mouse input or pass through to canvas."""
        for ed in getattr(self, '_form_field_overlay_widgets', {}).values():
            container = ed.get("container")
            if container and hasattr(container, "set_can_target"):
                if getattr(self, 'view_mode', False):
                    container.set_can_target(True)
                else:
                    is_active = (getattr(self, '_active_editing_form_field', None) is not None and
                                 (ed.get("field") == self._active_editing_form_field or
                                  getattr(ed.get("field"), 'xref', None) == getattr(self._active_editing_form_field, 'xref', -1)))
                    container.set_can_target(bool(is_active))

    def _load_acroform_fields_for_page(self, page_index=None):
        """Reload AcroForm fields and rebuild overlays for the specified or current page."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            self.form_fields = []
            if hasattr(self, '_create_form_field_overlays'):
                self._create_form_field_overlays()
            return
        if page_index is None:
            page_index = self.current_page_index
        fields, err = pdf_handler.extract_acroform_fields(self.doc, page_index)
        if not err:
            self.form_fields = fields
        else:
            self.form_fields = []
        if hasattr(self, '_create_form_field_overlays'):
            self._create_form_field_overlays()

    def _focus_form_field_overlay(self, field):
        """Focus the overlay widget corresponding to field if available, or open in-place editor."""
        if not field:
            return
        entry_data = self._get_overlay_for_field(field)
        if entry_data and entry_data.get("widget"):
            try:
                entry_data["widget"].grab_focus()
                return
            except Exception:
                pass
        self._open_form_field_editor(field)

    def _create_form_field_overlays(self):
        """Create and place GTK overlay widgets for form fields on current page."""
        self._clear_form_field_overlays()
        if not getattr(self, '_enable_persistent_form_overlays', False):
            return
        if not self.doc or not hasattr(self, 'pdf_overlay') or not self.pdf_overlay:
            return
        if not (0 <= self.current_page_index < len(self.doc)):
            return

        current_fields = [
            f for f in getattr(self, 'form_fields', [])
            if getattr(f, 'page_number', self.current_page_index) == self.current_page_index
        ]

        for field in current_fields:
            ftype = getattr(field, 'field_type', 'text')
            wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)

            if ftype == "text":
                if getattr(field, 'is_multiline', False):
                    scroll = Gtk.ScrolledWindow()
                    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
                    scroll.add_css_class("acroform-frame")
                    scroll.set_halign(Gtk.Align.START)
                    scroll.set_valign(Gtk.Align.START)
                    scroll.set_margin_start(wx)
                    scroll.set_margin_top(wy)
                    scroll.set_size_request(ww, wh)

                    tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
                    tv.add_css_class("acroform-textview")
                    if getattr(field, 'is_read_only', False):
                        tv.set_editable(False)
                    buf = tv.get_buffer()
                    buf.set_text(str(field.value if field.value is not None else ""))
                    scroll.set_child(tv)

                    container = scroll
                    input_widget = tv

                    entry_data = {
                        "field": field,
                        "container": container,
                        "widget": input_widget,
                        "initial_val": field.value,
                        "current_val": field.value,
                    }

                    def _on_tv_changed(b, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        start, end = b.get_bounds()
                        txt = b.get_text(start, end, True)
                        ed["current_val"] = txt
                        self._sync_form_field_value(ed["field"], txt, record_undo=False)

                    def _on_tv_focus_leave(ctrl, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        cur = ed.get("current_val", "")
                        init = ed.get("initial_val", "")
                        if cur != init:
                            cmd = EditFormFieldCommand(self, ed["field"], init, cur)
                            self.undo_manager.add_command(cmd)
                            ed["initial_val"] = cur
                        if getattr(self, '_active_editing_form_field', None) == ed.get("field"):
                            self._close_active_form_field_editor()

                    def _on_tv_focus_enter(ctrl, ed=entry_data):
                        ed["initial_val"] = ed.get("current_val", ed["field"].value)
                        self.selected_form_field = ed["field"]
                        if hasattr(self, 'pdf_view') and self.pdf_view:
                            self.pdf_view.queue_draw()
                        self._update_ui_state()

                    buf.connect("changed", _on_tv_changed)
                    focus_ctrl = Gtk.EventControllerFocus()
                    focus_ctrl.connect("enter", _on_tv_focus_enter)
                    focus_ctrl.connect("leave", _on_tv_focus_leave)
                    tv.add_controller(focus_ctrl)

                    key_ctrl = Gtk.EventControllerKey()
                    def _on_tv_key(ctrl, keyval, keycode, state):
                        if keyval == Gdk.KEY_Escape:
                            self._close_active_form_field_editor()
                            return True
                        return False
                    key_ctrl.connect("key-pressed", _on_tv_key)
                    tv.add_controller(key_ctrl)

                else:
                    entry = Gtk.Entry()
                    entry.add_css_class("acroform-entry")
                    if getattr(field, 'is_read_only', False):
                        entry.set_editable(False)
                        entry.add_css_class("readonly")
                    if getattr(field, 'is_password', False):
                        entry.set_visibility(False)
                    if getattr(field, 'max_length', 0) > 0:
                        entry.set_max_length(field.max_length)

                    entry.set_text(str(field.value if field.value is not None else ""))
                    entry.set_halign(Gtk.Align.START)
                    entry.set_valign(Gtk.Align.START)
                    entry.set_margin_start(wx)
                    entry.set_margin_top(wy)
                    entry.set_size_request(ww, wh)

                    container = entry
                    input_widget = entry

                    entry_data = {
                        "field": field,
                        "container": container,
                        "widget": input_widget,
                        "initial_val": field.value,
                        "current_val": field.value,
                    }

                    def _on_entry_changed(w, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        txt = w.get_text()
                        ed["current_val"] = txt
                        self._sync_form_field_value(ed["field"], txt, record_undo=False)

                    def _on_entry_focus_leave(ctrl, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        cur = ed.get("current_val", "")
                        init = ed.get("initial_val", "")
                        if cur != init:
                            cmd = EditFormFieldCommand(self, ed["field"], init, cur)
                            self.undo_manager.add_command(cmd)
                            ed["initial_val"] = cur
                        if getattr(self, '_active_editing_form_field', None) == ed.get("field"):
                            self._close_active_form_field_editor()

                    def _on_entry_focus_enter(ctrl, ed=entry_data):
                        ed["initial_val"] = ed.get("current_val", ed["field"].value)
                        self.selected_form_field = ed["field"]
                        if hasattr(self, 'pdf_view') and self.pdf_view:
                            self.pdf_view.queue_draw()
                        self._update_ui_state()

                    entry.connect("changed", _on_entry_changed)
                    entry.connect("activate", lambda w, ed=entry_data: self._close_active_form_field_editor())
                    focus_ctrl = Gtk.EventControllerFocus()
                    focus_ctrl.connect("enter", _on_entry_focus_enter)
                    focus_ctrl.connect("leave", _on_entry_focus_leave)
                    entry.add_controller(focus_ctrl)

                    key_ctrl = Gtk.EventControllerKey()
                    def _on_entry_key(ctrl, keyval, keycode, state):
                        if keyval == Gdk.KEY_Escape:
                            self._close_active_form_field_editor()
                            return True
                        return False
                    key_ctrl.connect("key-pressed", _on_entry_key)
                    entry.add_controller(key_ctrl)

                self.pdf_overlay.add_overlay(container)
                self._form_field_overlay_widgets[field.field_id] = entry_data

            elif ftype in ("checkbox", "radio"):
                chk = Gtk.CheckButton()
                chk.add_css_class("acroform-check")
                chk.set_active(bool(field.is_checked))
                if getattr(field, 'is_read_only', False):
                    chk.set_sensitive(False)
                chk.set_halign(Gtk.Align.START)
                chk.set_valign(Gtk.Align.START)
                chk.set_margin_start(wx)
                chk.set_margin_top(wy)
                chk.set_size_request(ww, wh)

                container = chk
                input_widget = chk

                entry_data = {
                    "field": field,
                    "container": container,
                    "widget": input_widget,
                    "initial_val": field.value,
                    "current_val": field.value,
                }

                def _on_check_toggled(btn, ed=entry_data):
                    if getattr(self, '_syncing_form_field', False):
                        return
                    new_val = btn.get_active()
                    old_val = ed["field"].value
                    ed["current_val"] = new_val
                    ed["initial_val"] = new_val
                    self._sync_form_field_value(ed["field"], new_val, record_undo=True, old_val_override=old_val)

                def _on_check_focus_enter(ctrl, ed=entry_data):
                    self.selected_form_field = ed["field"]
                    if hasattr(self, 'pdf_view') and self.pdf_view:
                        self.pdf_view.queue_draw()
                    self._update_ui_state()

                chk.connect("toggled", _on_check_toggled)
                focus_ctrl = Gtk.EventControllerFocus()
                focus_ctrl.connect("enter", _on_check_focus_enter)
                chk.add_controller(focus_ctrl)

                self.pdf_overlay.add_overlay(container)
                self._form_field_overlay_widgets[field.field_id] = entry_data

            elif ftype in ("combobox", "listbox", "choice"):
                raw_choices = getattr(field, 'choice_values', []) or []
                display_items = []
                export_items = []
                for item in raw_choices:
                    if isinstance(item, (list, tuple)):
                        exp = str(item[0]) if len(item) > 0 else ""
                        disp = str(item[1]) if len(item) > 1 else exp
                    else:
                        exp = str(item)
                        disp = str(item)
                    display_items.append(disp)
                    export_items.append(exp)

                if not display_items:
                    init_str = str(field.value if field.value is not None else "")
                    display_items = [init_str] if init_str else [""]
                    export_items = [init_str] if init_str else [""]

                dropdown = Gtk.DropDown.new_from_strings(display_items)
                dropdown.add_css_class("acroform-dropdown")
                if getattr(field, 'is_read_only', False):
                    dropdown.set_sensitive(False)

                val_str = str(field.value if field.value is not None else "")
                selected_idx = 0
                if val_str in export_items:
                    selected_idx = export_items.index(val_str)
                elif val_str in display_items:
                    selected_idx = display_items.index(val_str)
                dropdown.set_selected(selected_idx)

                dropdown.set_halign(Gtk.Align.START)
                dropdown.set_valign(Gtk.Align.START)
                dropdown.set_margin_start(wx)
                dropdown.set_margin_top(wy)
                dropdown.set_size_request(ww, wh)

                container = dropdown
                input_widget = dropdown

                entry_data = {
                    "field": field,
                    "container": container,
                    "widget": input_widget,
                    "initial_val": field.value,
                    "current_val": field.value,
                    "display_items": display_items,
                    "export_items": export_items,
                }

                def _on_dropdown_selected(dd, pspec, ed=entry_data):
                    if getattr(self, '_syncing_form_field', False):
                        return
                    sel_idx = dd.get_selected()
                    exp_items = ed.get("export_items", [])
                    if sel_idx < 0 or sel_idx >= len(exp_items):
                        return
                    new_val = exp_items[sel_idx]
                    old_val = ed["field"].value
                    if new_val == old_val:
                        return
                    ed["current_val"] = new_val
                    ed["initial_val"] = new_val
                    self._sync_form_field_value(ed["field"], new_val, record_undo=True, old_val_override=old_val)

                def _on_dropdown_focus_enter(ctrl, ed=entry_data):
                    self.selected_form_field = ed["field"]
                    if hasattr(self, 'pdf_view') and self.pdf_view:
                        self.pdf_view.queue_draw()
                    self._update_ui_state()

                dropdown.connect("notify::selected", _on_dropdown_selected)
                focus_ctrl = Gtk.EventControllerFocus()
                focus_ctrl.connect("enter", _on_dropdown_focus_enter)
                dropdown.add_controller(focus_ctrl)

                self.pdf_overlay.add_overlay(container)
                self._form_field_overlay_widgets[field.field_id] = entry_data

        if hasattr(self, "_update_form_field_overlay_interactivity"):
            self._update_form_field_overlay_interactivity()

    def _find_resize_handle_at_pos(self, drawn_x, drawn_y, selected_obj):
        """Find resize handle or rotation stalk handle at pos."""
        if not selected_obj or not selected_obj.bbox:
            return None
        if isinstance(selected_obj, AcroFormField) and getattr(self, '_active_editing_form_field', None) == selected_obj:
            return None
        
        x1, y1, x2, y2 = selected_obj.bbox
        page_offset_x = max(0, (self.pdf_view.get_allocated_width() - self.current_pdf_page_width) / 2)
        page_offset_y = max(0, (self.pdf_view.get_allocated_height() - self.current_pdf_page_height) / 2)
        
        vis_x = (drawn_x - page_offset_x) / self.zoom_level
        vis_y = (drawn_y - page_offset_y) / self.zoom_level
        unrot_x, unrot_y = vis_x, vis_y
        try:
            coords = self._visual_to_unrotated_page_coords(vis_x, vis_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                unrot_x, unrot_y = coords
        except Exception:
            pass

        padding = 3.0 / self.zoom_level
        rect_x = x1 - padding
        rect_y = y1 - padding
        rect_w = (x2 - x1) + (2 * padding)
        rect_h = (y2 - y1) + (2 * padding)

        rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        cx = rect_x + rect_w / 2.0
        cy = rect_y + rect_h / 2.0

        if rot != 0.0:
            px, py = pdf_handler.rotate_point(unrot_x, unrot_y, cx, cy, -rot)
        else:
            px, py = unrot_x, unrot_y

        is_form_field = isinstance(selected_obj, AcroFormField) or hasattr(selected_obj, 'field_name')
        if not is_form_field:
            stalk_len = 22.0 / self.zoom_level
            rot_hx = cx
            rot_hy = rect_y - stalk_len
            rot_tolerance = 8.0 / self.zoom_level
            if math.hypot(px - rot_hx, py - rot_hy) <= rot_tolerance:
                return "rotate"
        
        if isinstance(selected_obj, EditableText):
            return None
        
        handle_size = 8.0 / self.zoom_level
        handle_tolerance = (6.0 if is_form_field else (4.0 if getattr(self, 'tool_mode', None) in ("pen", "highlighter") else 4.5)) / self.zoom_level
        
        handles = [
            ("nw", rect_x, rect_y),
            ("ne", rect_x + rect_w, rect_y),
            ("sw", rect_x, rect_y + rect_h),
            ("se", rect_x + rect_w, rect_y + rect_h),
            ("n", rect_x + rect_w / 2.0, rect_y),
            ("s", rect_x + rect_w / 2.0, rect_y + rect_h),
            ("w", rect_x, rect_y + rect_h / 2.0),
            ("e", rect_x + rect_w, rect_y + rect_h / 2.0),
        ]
        
        for handle_name, handle_x, handle_y in handles:
            if abs(px - handle_x) <= handle_tolerance and abs(py - handle_y) <= handle_tolerance:
                return handle_name
        
        return None

    def _handle_add_image_action(self, page_x_unzoomed, page_y_unzoomed):
        """Handle add image action."""
        filter_img = Gtk.FileFilter(name=_("image_filter_label"))
        for mime in ["image/png", "image/jpeg", "image/gif", "image/bmp"]:
            filter_img.add_mime_type(mime)

        def on_open_finish(file):
            if file:
                image_path = file.get_path()
                try:
                    with open(image_path, 'rb') as f:
                        image_bytes = f.read()

                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
                    img_w, img_h = pixbuf.get_width(), pixbuf.get_height()

                    target_w = 150.0
                    target_h = (img_h / img_w) * target_w if img_w > 0 else 150.0
                    unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x_unzoomed, page_y_unzoomed)
                    rect = (unrot_x, unrot_y,
                            unrot_x + target_w, unrot_y + target_h)

                    new_image_obj = EditableImage(
                        bbox=rect,
                        page_number=self.current_page_index,
                        xref=None,
                        image_bytes=image_bytes,
                        is_new=True
                    )

                    command = AddObjectCommand(self, new_image_obj)
                    command.execute()
                    self.undo_manager.add_command(command)

                except Exception as e:
                    show_error_dialog(self, _("image_add_error", e), _("image_error_title"))

        show_open_file_dialog(self, _("image_select_title"), filters=[filter_img], callback=on_open_finish)

    def _update_text_format_controls(self, text_obj):
        """Update text format controls."""
        if not text_obj or self.font_scan_in_progress:
            if self.tool_mode == "add_text":
                return
            if not self.font_scan_in_progress and self.font_combo.get_sensitive():
                self.font_combo.handler_block_by_func(self.on_text_format_changed)
                self.font_combo.set_active(0)
                self.font_combo.handler_unblock_by_func(self.on_text_format_changed)

            self.font_size_spin.handler_block_by_func(self.on_text_format_changed)
            self.font_size_spin.set_value(11)
            self.font_size_spin.handler_unblock_by_func(self.on_text_format_changed)

            default_rgba = Gdk.RGBA(); default_rgba.parse("black")
            self.color_button.handler_block_by_func(self.on_text_format_changed)
            self.color_button.set_rgba(default_rgba)
            self.color_button.handler_unblock_by_func(self.on_text_format_changed)

            if self.bold_button:
                self.bold_button.handler_block_by_func(self.on_text_format_changed)
                self.bold_button.set_active(False)
                self.bold_button.handler_unblock_by_func(self.on_text_format_changed)
            if self.italic_button:
                self.italic_button.handler_block_by_func(self.on_text_format_changed)
                self.italic_button.set_active(False)
                self.italic_button.handler_unblock_by_func(self.on_text_format_changed)
            if hasattr(self, 'underline_button') and self.underline_button:
                self.underline_button.handler_block_by_func(self.on_text_format_changed)
                self.underline_button.set_active(False)
                self.underline_button.handler_unblock_by_func(self.on_text_format_changed)
            if hasattr(self, 'strikethrough_button') and self.strikethrough_button:
                self.strikethrough_button.handler_block_by_func(self.on_text_format_changed)
                self.strikethrough_button.set_active(False)
                self.strikethrough_button.handler_unblock_by_func(self.on_text_format_changed)
            if hasattr(self, 'link_button') and self.link_button:
                self.link_button.set_sensitive(False)
                self.link_button.set_tooltip_text(_("insert_link_tip"))
            align_btns = [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                          getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]
            for b in align_btns:
                if b:
                    b.handler_block_by_func(self.on_text_format_changed)
            cur_align = getattr(self, '_last_alignment', 'left')
            target_btn = getattr(self, 'align_left_button', None)
            if cur_align == 'center' and getattr(self, 'align_center_button', None):
                target_btn = self.align_center_button
            elif cur_align == 'right' and getattr(self, 'align_right_button', None):
                target_btn = self.align_right_button
            elif cur_align == 'justify' and getattr(self, 'align_justify_button', None):
                target_btn = self.align_justify_button

            for b in align_btns:
                if b and b != target_btn and b.get_active():
                    b.set_active(False)
            if target_btn and not target_btn.get_active():
                target_btn.set_active(True)

            for b in align_btns:
                if b:
                    b.handler_unblock_by_func(self.on_text_format_changed)
            return

        signals_blocked = False
        align_btns = [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                      getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]
        try:
            widgets_to_block = [self.font_combo, self.font_size_spin, self.color_button, self.bold_button,
                                self.italic_button, getattr(self, 'underline_button', None),
                                getattr(self, 'strikethrough_button', None)] + [b for b in align_btns if b]
            for widget in widgets_to_block:
                if widget: widget.handler_block_by_func(self.on_text_format_changed)
            signals_blocked = True

            active_font_index = -1
            target_family_base = text_obj.font_family_base 
            normalized_target_family_base = target_family_base.replace(" ", "").lower() if target_family_base else ""

            if target_family_base and utils.FONT_FAMILY_LIST_SORTED:
                model = self.font_combo.get_model()
                if model:
                    for i, row in enumerate(model):
                        combo_family_key = row[1]
                        normalized_combo_key = combo_family_key.replace(" ", "").lower()
                        if normalized_combo_key == normalized_target_family_base:
                            active_font_index = i
                            break
                
                if active_font_index == -1 and model:
                    for i, row in enumerate(model):
                        combo_family_key = row[1]
                        if target_family_base and combo_family_key and target_family_base.lower() in combo_family_key.lower():
                            active_font_index = i
                            break
                        elif target_family_base and combo_family_key and combo_family_key.lower() in target_family_base.lower():
                            active_font_index = i
                            break
                    if active_font_index == -1 and target_family_base:
                        # Register embedded/document font into combo store
                        self.font_store.append([target_family_base, target_family_base])
                        active_font_index = len(self.font_store) - 1
                    elif active_font_index == -1 and len(model) > 0:
                        active_font_index = 0


            if active_font_index != -1 and active_font_index < len(self.font_store):
                 self.font_combo.set_active(active_font_index)
            elif len(self.font_store) > 0:
                 self.font_combo.set_active(0)
            
            self.font_combo.set_tooltip_text(_("font_tip_original", text_obj.font_family_original))

            self.font_size_spin.set_value(text_obj.font_size)
            rgba = Gdk.RGBA(); rgba.red, rgba.green, rgba.blue = text_obj.color; rgba.alpha = 1.0
            self.color_button.set_rgba(rgba)
            if self.bold_button: self.bold_button.set_active(text_obj.is_bold)
            if self.italic_button: self.italic_button.set_active(text_obj.is_italic)
            if hasattr(self, 'underline_button') and self.underline_button:
                self.underline_button.set_active(getattr(text_obj, 'is_underline', False))
            if hasattr(self, 'strikethrough_button') and self.strikethrough_button:
                self.strikethrough_button.set_active(getattr(text_obj, 'is_strikethrough', False))
            if hasattr(self, 'link_button') and self.link_button:
                self.link_button.set_sensitive(True)
                eff_url = getattr(text_obj, 'link_url', None) or (text_obj.get_link_url() if hasattr(text_obj, 'get_link_url') else None)
                if eff_url:
                    self.link_button.set_tooltip_text(_("edit_link_tip", eff_url))
                else:
                    self.link_button.set_tooltip_text(_("insert_link_tip"))

            cur_align = getattr(text_obj, 'alignment', 'left')
            target_btn = getattr(self, 'align_left_button', None)
            if cur_align == 'center' and getattr(self, 'align_center_button', None):
                target_btn = self.align_center_button
            elif cur_align == 'right' and getattr(self, 'align_right_button', None):
                target_btn = self.align_right_button
            elif cur_align == 'justify' and getattr(self, 'align_justify_button', None):
                target_btn = self.align_justify_button

            for b in align_btns:
                if b and b != target_btn and b.get_active():
                    b.set_active(False)
            if target_btn and not target_btn.get_active():
                target_btn.set_active(True)

            self._last_font_family = target_family_base
            self._last_font_size = text_obj.font_size
            self._last_color = text_obj.color
            self._last_is_bold = text_obj.is_bold
            self._last_is_italic = text_obj.is_italic
            self._last_is_strikethrough = getattr(text_obj, 'is_strikethrough', False)
            self._last_alignment = cur_align

        finally:
            if signals_blocked:
                widgets_to_unblock = [self.font_combo, self.font_size_spin, self.color_button, self.bold_button,
                                      self.italic_button, getattr(self, 'underline_button', None),
                                      getattr(self, 'strikethrough_button', None)] + [b for b in align_btns if b]
                for widget in widgets_to_unblock:
                    if widget: widget.handler_unblock_by_func(self.on_text_format_changed)

    def _get_current_alignment(self):
        """Get the current alignment string."""
        if hasattr(self, 'align_center_button') and self.align_center_button and self.align_center_button.get_active():
            return 'center'
        if hasattr(self, 'align_right_button') and self.align_right_button and self.align_right_button.get_active():
            return 'right'
        if hasattr(self, 'align_justify_button') and self.align_justify_button and self.align_justify_button.get_active():
            return 'justify'
        return 'left'

    def _get_current_format_settings(self):
        """Get the current format settings."""
        font_family_display = "Sans"
        font_pdf_name = "helv"
        iter = self.font_combo.get_active_iter()
        if iter:
            font_family_display = self.font_store[iter][0]
            font_pdf_name = self.font_store[iter][1]

        font_size = self.font_size_spin.get_value()

        rgba = self.color_button.get_rgba()
        color = (rgba.red, rgba.green, rgba.blue)

        is_bold = self.bold_button.get_active() if self.bold_button else False
        is_italic = self.italic_button.get_active() if self.italic_button else False
        is_underline = self.underline_button.get_active() if hasattr(self, 'underline_button') and self.underline_button else False
        is_strikethrough = self.strikethrough_button.get_active() if hasattr(self, 'strikethrough_button') and self.strikethrough_button else False
        alignment = self._get_current_alignment()

        return font_family_display, font_pdf_name, font_size, color, is_bold, is_italic, is_underline, is_strikethrough, alignment

    def _update_shape_format_controls(self, shape_obj):
        """Update shape format controls."""
        try:
            self.shape_fill_button.handler_block_by_func(self.on_shape_format_changed)
            self.shape_stroke_button.handler_block_by_func(self.on_shape_format_changed)
            self.shape_stroke_width_spin.handler_block_by_func(self.on_shape_format_changed)

            if not shape_obj:
                fill_rgba = Gdk.RGBA()
                fill_rgba.parse("white")
                self.shape_fill_button.set_rgba(fill_rgba)

                stroke_rgba = Gdk.RGBA()
                stroke_rgba.parse("black")
                self.shape_stroke_button.set_rgba(stroke_rgba)

                self.shape_stroke_width_spin.set_value(2.0)
            else:
                fill_r, fill_g, fill_b = shape_obj.fill_color
                fill_rgba = Gdk.RGBA()
                fill_rgba.red, fill_rgba.green, fill_rgba.blue = fill_r, fill_g, fill_b
                fill_rgba.alpha = 1.0
                self.shape_fill_button.set_rgba(fill_rgba)

                stroke_r, stroke_g, stroke_b = shape_obj.stroke_color
                stroke_rgba = Gdk.RGBA()
                stroke_rgba.red, stroke_rgba.green, stroke_rgba.blue = stroke_r, stroke_g, stroke_b
                stroke_rgba.alpha = 1.0
                self.shape_stroke_button.set_rgba(stroke_rgba)

                self.shape_stroke_width_spin.set_value(shape_obj.stroke_width)

        finally:
            self.shape_fill_button.handler_unblock_by_func(self.on_shape_format_changed)
            self.shape_stroke_button.handler_unblock_by_func(self.on_shape_format_changed)
            self.shape_stroke_width_spin.handler_unblock_by_func(self.on_shape_format_changed)

    def _update_stroke_format_controls(self, stroke_obj):
        """Update stroke format controls."""
        try:
            self.stroke_color_button.handler_block_by_func(self.on_stroke_format_changed)
            self.stroke_width_spin.handler_block_by_func(self.on_stroke_format_changed)

            if not stroke_obj:
                if self.tool_mode == "highlighter":
                    r, g, b = self.highlighter_color
                    w = self.highlighter_width
                else:
                    r, g, b = self.pen_color
                    w = self.pen_width
            else:
                r, g, b = stroke_obj.stroke_color
                w = stroke_obj.stroke_width

            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = r, g, b, 1.0
            self.stroke_color_button.set_rgba(rgba)
            self.stroke_width_spin.set_value(w)
        finally:
            self.stroke_color_button.handler_unblock_by_func(self.on_stroke_format_changed)
            self.stroke_width_spin.handler_unblock_by_func(self.on_stroke_format_changed)

    def _update_rotation_controls(self, selected_obj):
        """Sync rotation spin button and reset button with selected object's rotation angle."""
        if not hasattr(self, 'rotation_spin'):
            return

        self.rotation_spin.handler_block_by_func(self.on_object_rotation_spin_changed)
        try:
            if selected_obj:
                rot = round(getattr(selected_obj, 'rotation', 0.0)) % 360
                self.rotation_spin.set_value(rot)
                if hasattr(self, 'rotate_obj_reset_button'):
                    self.rotate_obj_reset_button.set_sensitive(rot != 0)
                if hasattr(self, 'rotate_obj_cw_button'):
                    self.rotate_obj_cw_button.set_sensitive(True)
                if hasattr(self, 'rotate_obj_ccw_button'):
                    self.rotate_obj_ccw_button.set_sensitive(True)
            else:
                self.rotation_spin.set_value(0)
                if hasattr(self, 'rotate_obj_reset_button'):
                    self.rotate_obj_reset_button.set_sensitive(False)
                if hasattr(self, 'rotate_obj_cw_button'):
                    self.rotate_obj_cw_button.set_sensitive(False)
                if hasattr(self, 'rotate_obj_ccw_button'):
                    self.rotate_obj_ccw_button.set_sensitive(False)
        finally:
            self.rotation_spin.handler_unblock_by_func(self.on_object_rotation_spin_changed)

    def on_rotate_object_cw_clicked(self, button=None):
        """Rotate the currently selected object 90 degrees clockwise."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        new_rot = (old_rot + 90.0) % 360.0

        command = RotateObjectCommand(self, selected_obj, old_rot, new_rot)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = copy.deepcopy(selected_obj.__dict__)
            self._update_text_format_controls(selected_obj)

    def on_rotate_object_ccw_clicked(self, button=None):
        """Rotate the currently selected object 90 degrees counterclockwise."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        new_rot = (old_rot - 90.0) % 360.0

        command = RotateObjectCommand(self, selected_obj, old_rot, new_rot)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = copy.deepcopy(selected_obj.__dict__)
            self._update_text_format_controls(selected_obj)

    def on_rotate_object_reset_clicked(self, button=None):
        """Reset rotation of selected object to 0 degrees."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        if old_rot == 0.0:
            return

        command = RotateObjectCommand(self, selected_obj, old_rot, 0.0)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = copy.deepcopy(selected_obj.__dict__)
            self._update_text_format_controls(selected_obj)

    def on_object_rotation_spin_changed(self, spin_button):
        """Handle numeric spin button changes for object rotation."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        new_rot = float(spin_button.get_value()) % 360.0

        if abs(old_rot - new_rot) < 0.1:
            return

        command = RotateObjectCommand(self, selected_obj, old_rot, new_rot)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = copy.deepcopy(selected_obj.__dict__)
            self._update_text_format_controls(selected_obj)

    def _apply_inline_editor_style(self):
        """Apply dynamic typography styling and Adwaita theme colors to the inline text editor."""
        if not getattr(self, 'inline_editor_widget', None) or not getattr(self, 'inline_editor_tv', None):
            return
        text_obj = getattr(self, 'inline_editor_text_obj', None)
        if not text_obj:
            return

        if hasattr(self, '_inline_editor_css_provider') and self._inline_editor_css_provider:
            try:
                self.inline_editor_tv.get_style_context().remove_provider(self._inline_editor_css_provider)
                self.inline_editor_widget.get_style_context().remove_provider(self._inline_editor_css_provider)
            except Exception:
                pass
            self._inline_editor_css_provider = None

        family = getattr(text_obj, 'font_family_base', 'Liberation Sans') or 'Liberation Sans'
        scaled_font_size = max(9, int(round(text_obj.font_size * self.zoom_level)))
        weight_css = "bold" if getattr(text_obj, 'is_bold', False) else "normal"
        style_css = "italic" if getattr(text_obj, 'is_italic', False) else "normal"

        col = getattr(text_obj, 'color', (0, 0, 0))
        if isinstance(col, (tuple, list)) and len(col) >= 3:
            r = max(0, min(255, int(round(col[0] * 255))))
            g = max(0, min(255, int(round(col[1] * 255))))
            b = max(0, min(255, int(round(col[2] * 255))))
        else:
            r, g, b = 0, 0, 0
        color_css = f"rgb({r}, {g}, {b})"

        css_str = f"""
            .inline-editor-tv {{
                min-height: 0px;
                min-width: 0px;
                margin: 0px;
                padding: 1px 3px;
                background-color: #ffffff;
                border: none;
                box-shadow: none;
                font-family: '{family}', 'Liberation Sans', 'DejaVu Sans', sans-serif;
                font-size: {scaled_font_size}px;
                font-weight: {weight_css};
                font-style: {style_css};
                color: {color_css};
            }}
            .inline-editor-frame {{
                min-height: 0px;
                min-width: 0px;
                padding: 0px;
                margin: 0px;
                border: 1.5px solid @accent_color;
                border-radius: 4px;
                background-color: #ffffff;
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
            }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css_str.encode('utf-8'))
        self._inline_editor_css_provider = provider

        self.inline_editor_tv.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self.inline_editor_widget.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def _on_inline_editor_text_changed(self, buffer):
        """Dynamically expand inline editor width and height as text is typed."""
        if not getattr(self, 'inline_editor_widget', None) or not getattr(self, 'inline_editor_tv', None):
            return
        text_obj = getattr(self, 'inline_editor_text_obj', None)
        if not text_obj:
            return

        buf = self.inline_editor_tv.get_buffer()
        current_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

        try:
            pango_ctx = self.inline_editor_tv.get_pango_context()
            layout = Pango.Layout(pango_ctx)
            family = getattr(text_obj, 'font_family_base', 'Liberation Sans') or 'Liberation Sans'
            font_desc = Pango.FontDescription.from_string(family)
            if getattr(text_obj, 'is_bold', False):
                font_desc.set_weight(Pango.Weight.BOLD)
            if getattr(text_obj, 'is_italic', False):
                font_desc.set_style(Pango.Style.ITALIC)
            scaled_font_size = max(9.0, text_obj.font_size * self.zoom_level)
            font_desc.set_absolute_size(int(scaled_font_size * Pango.SCALE))
            layout.set_font_description(font_desc)
            layout.set_text(current_text or " ", -1)
            pw, ph = layout.get_size()
            calc_w = int(pw / Pango.SCALE) + 14
            calc_h = int(ph / Pango.SCALE) + 6
        except Exception:
            calc_w = getattr(self, '_inline_editor_base_w', 60)
            calc_h = getattr(self, '_inline_editor_base_h', 24)

        base_w = getattr(self, '_inline_editor_base_w', 60)
        base_h = getattr(self, '_inline_editor_base_h', 24)

        new_w = max(base_w, calc_w)
        new_h = max(base_h, calc_h)

        da_w = max(self.pdf_view.get_allocated_width(), self.current_pdf_page_width)
        max_w = max(base_w, int(da_w - getattr(self, '_inline_editor_base_x', 0) - 20))
        clamped_w = min(new_w, max_w)

        self.inline_editor_widget.set_size_request(clamped_w, new_h)

    def _show_inline_editor(self, text_obj, click_x=None, click_y=None, target_rect=None):
        """Show inline editor overlay exactly positioned over target text."""
        self._hide_inline_editor()
        if not text_obj or not self.doc or not (0 <= self.current_page_index < pdf_handler.get_page_count(self.doc)):
            return

        self.inline_editor_text_obj = text_obj
        self._inline_editor_target_rect = target_rect
        self._inline_editor_initial_text = text_obj.text

        da_w = max(self.pdf_view.get_allocated_width(), self.current_pdf_page_width)
        da_h = max(self.pdf_view.get_allocated_height(), self.current_pdf_page_height)
        page_w = self.current_pdf_page_width
        page_h = self.current_pdf_page_height
        page_offset_x = max(0.0, (da_w - page_w) / 2.0)
        page_offset_y = max(0.0, (da_h - page_h) / 2.0)

        target_box = target_rect or getattr(text_obj, 'bbox', None)
        if target_box:
            page = self.doc[self.current_page_index]
            vis_rect = (fitz.Rect(target_box) * page.rotation_matrix).normalize()
            ed_x = int(page_offset_x + vis_rect.x0 * self.zoom_level) - 2
            ed_y = int(page_offset_y + vis_rect.y0 * self.zoom_level) - 2
            scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
            ed_w = max(60, int(vis_rect.width * self.zoom_level) + 14)
            ed_h = max(int(scaled_font * 1.3) + 6, int(vis_rect.height * self.zoom_level) + 6)
        elif click_x is not None and click_y is not None:
            ed_x = int(click_x) - 2
            ed_y = int(click_y) - 2
            scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
            ed_w = 140
            ed_h = max(int(scaled_font * 1.3) + 6, 28)
        else:
            ed_x = int(page_offset_x + 10)
            ed_y = int(page_offset_y + 10)
            scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
            ed_w = 140
            ed_h = 28

        self._inline_editor_base_x = ed_x
        self._inline_editor_base_y = ed_y
        self._inline_editor_base_w = ed_w
        self._inline_editor_base_h = ed_h

        frame = Gtk.Frame()
        frame.add_css_class("inline-editor-frame")
        frame.set_halign(Gtk.Align.START)
        frame.set_valign(Gtk.Align.START)
        frame.set_margin_start(ed_x)
        frame.set_margin_top(ed_y)
        frame.set_size_request(ed_w, ed_h)

        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(3)
        tv.set_right_margin(3)
        tv.set_top_margin(1)
        tv.set_bottom_margin(1)
        align_val = getattr(text_obj, 'alignment', 'left')
        if align_val == 'center':
            tv.set_justification(Gtk.Justification.CENTER)
        elif align_val == 'right':
            tv.set_justification(Gtk.Justification.RIGHT)
        elif align_val == 'justify':
            tv.set_justification(Gtk.Justification.FILL)
        else:
            tv.set_justification(Gtk.Justification.LEFT)

        buf = tv.get_buffer()
        buf.set_text(text_obj.text or "")
        buf.select_range(buf.get_start_iter(), buf.get_end_iter())
        buf.connect("changed", self._on_inline_editor_text_changed)

        tv.add_css_class("inline-editor-tv")
        frame.set_child(tv)

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", self._on_inline_editor_focus_leave)
        tv.add_controller(focus_ctrl)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_inline_editor_key)
        tv.add_controller(key_ctrl)

        self.pdf_overlay.add_overlay(frame)
        self.inline_editor_widget = frame
        self.inline_editor_tv = tv
        self._apply_inline_editor_style()
        self._on_inline_editor_text_changed(buf)

        GLib.idle_add(tv.grab_focus)
        self.pdf_view.queue_draw()

    def _cancel_inline_editor(self):
        """Cancel inline editing and revert text changes."""
        if not getattr(self, 'inline_editor_widget', None):
            return
        text_obj = getattr(self, 'inline_editor_text_obj', None)
        if text_obj:
            if getattr(text_obj, 'is_new', False):
                if text_obj in getattr(self, 'editable_texts', []):
                    self.editable_texts.remove(text_obj)
                self.selected_text = None
            else:
                init_text = getattr(self, '_inline_editor_initial_text', None)
                if init_text is not None:
                    text_obj.text = init_text
        self._hide_inline_editor()
        self._update_ui_state()
        self.pdf_view.queue_draw()

    def _hide_inline_editor(self):
        """Hide inline editor and clean up references."""
        if hasattr(self, '_inline_editor_css_provider') and self._inline_editor_css_provider:
            try:
                if self.inline_editor_tv:
                    self.inline_editor_tv.get_style_context().remove_provider(self._inline_editor_css_provider)
                if self.inline_editor_widget:
                    self.inline_editor_widget.get_style_context().remove_provider(self._inline_editor_css_provider)
            except Exception:
                pass
            self._inline_editor_css_provider = None

        if self.inline_editor_widget:
            if hasattr(self, 'pdf_overlay') and self.pdf_overlay:
                try:
                    self.pdf_overlay.remove_overlay(self.inline_editor_widget)
                except Exception:
                    pass
            self.inline_editor_widget = None
            self.inline_editor_tv = None
            self.inline_editor_text_obj = None
            self._inline_editor_target_rect = None
            self._inline_editor_initial_text = None

    def _commit_inline_edit(self):
        """Commit inline edit."""
        if not getattr(self, 'inline_editor_tv', None) or not getattr(self, 'inline_editor_text_obj', None) or not getattr(self, 'inline_editor_widget', None):
            self._hide_inline_editor()
            return

        text_obj_to_apply = self.inline_editor_text_obj
        old_properties = copy.deepcopy(text_obj_to_apply.__dict__)

        buf = self.inline_editor_tv.get_buffer()
        new_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

        self._hide_inline_editor()

        def _calc_bbox(obj, text):
            """Calculate updated bounding box after text modification."""
            x1, y1 = obj.x, obj.y
            _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
            _cr = cairo.Context(_surf)
            layout = PangoCairo.create_layout(_cr)
            family = getattr(obj, 'font_family_base', 'Liberation Sans') or 'Liberation Sans'
            desc = Pango.FontDescription.from_string(family)
            if getattr(obj, 'is_bold', False): desc.set_weight(Pango.Weight.BOLD)
            if getattr(obj, 'is_italic', False): desc.set_style(Pango.Style.ITALIC)
            desc.set_absolute_size(int(obj.font_size * Pango.SCALE))
            layout.set_font_description(desc)
            layout.set_text(text or "A", -1)
            pw, ph = layout.get_size()
            calc_w = pw / Pango.SCALE
            if getattr(obj, 'bbox', None):
                old_w = obj.bbox[2] - obj.bbox[0]
                final_w = max(calc_w, old_w) if getattr(obj, 'alignment', 'left') != 'left' else calc_w
            else:
                final_w = calc_w
            return (x1, y1, x1 + final_w, y1 + ph / Pango.SCALE)

        if text_obj_to_apply.is_new:
            if not new_text.strip():
                if text_obj_to_apply in getattr(self, 'editable_texts', []):
                    self.editable_texts.remove(text_obj_to_apply)
                self.selected_text = None
                self._update_ui_state()
                self.pdf_view.queue_draw()
                return

            text_obj_to_apply.text = new_text
            text_obj_to_apply.is_baked = True
            text_obj_to_apply.bbox = _calc_bbox(text_obj_to_apply, new_text)
            command = AddObjectCommand(self, text_obj_to_apply)
            command.execute()
            self.undo_manager.add_command(command)
            self._refresh_thumbnail(self.current_page_index)
        else:
            if not new_text.strip():
                command = DeleteObjectCommand(self, text_obj_to_apply)
                command.execute()
                self.undo_manager.add_command(command)
                self.selected_text = None
                self._update_ui_state()
                self.pdf_view.queue_draw()
                return

            new_properties = copy.deepcopy(text_obj_to_apply.__dict__)
            new_properties['text'] = new_text
            if not getattr(text_obj_to_apply, 'original_bbox', None):
                text_obj_to_apply.original_bbox = old_properties.get('original_bbox', old_properties.get('bbox'))
            new_properties['original_bbox'] = text_obj_to_apply.original_bbox
            if old_properties['text'] != new_text:
                x1, y1 = new_properties['bbox'][0], new_properties['bbox'][1]
                _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
                _cr = cairo.Context(_surf)
                layout = PangoCairo.create_layout(_cr)
                family = new_properties.get('font_family_base', 'Liberation Sans') or 'Liberation Sans'
                desc = Pango.FontDescription.from_string(family)
                if new_properties.get('is_bold'): desc.set_weight(Pango.Weight.BOLD)
                if new_properties.get('is_italic'): desc.set_style(Pango.Style.ITALIC)
                desc.set_absolute_size(int(new_properties['font_size'] * Pango.SCALE))
                layout.set_font_description(desc)
                layout.set_text(new_text or "A", -1)
                pw, ph = layout.get_size()
                calc_w = pw / Pango.SCALE
                if old_properties.get('bbox'):
                    old_w = old_properties['bbox'][2] - old_properties['bbox'][0]
                    final_w = max(calc_w, old_w) if new_properties.get('alignment', 'left') != 'left' else calc_w
                else:
                    final_w = calc_w
                new_properties['bbox'] = (x1, y1, x1 + final_w, y1 + ph / Pango.SCALE)
                command = EditObjectCommand(self, text_obj_to_apply, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self._refresh_thumbnail(self.current_page_index)

        if text_obj_to_apply:
            self.selected_text = text_obj_to_apply
            self.pending_format_change_obj = text_obj_to_apply
            self.before_format_change_state = copy.deepcopy(text_obj_to_apply.__dict__)
            self._update_text_format_controls(text_obj_to_apply)

        self._update_ui_state()
        self.pdf_view.queue_draw()

    def _on_inline_editor_focus_leave(self, controller):
        """Commit active inline text edit when editor widget loses focus."""
        if not getattr(self, 'inline_editor_widget', None):
            return
        focus_widget = self.get_focus()
        if focus_widget:
            curr = focus_widget
            while curr:
                if curr == getattr(self, 'main_toolbar', None):
                    return
                curr = curr.get_parent()

        GLib.idle_add(self._commit_inline_edit)

    def _on_inline_editor_key(self, controller, keyval, keycode, state):
        """Handle keyboard shortcuts inside inline editor: Escape, Enter, Ctrl+Enter, Shift+Enter."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if keyval == Gdk.KEY_Escape:
            self._cancel_inline_editor()
            return True

        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if shift:
                if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
                    buf = self.inline_editor_tv.get_buffer()
                    buf.insert_at_cursor("\n")
                return True
            elif ctrl:
                self._commit_inline_edit()
                return True
            else:
                if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
                    buf = self.inline_editor_tv.get_buffer()
                    current_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
                    if "\n" not in current_text:
                        self._commit_inline_edit()
                        return True
                    else:
                        return False

        return False

    def hide_text_editor(self):
        """Dismiss the inline text editing widget."""
        self._hide_inline_editor()

    def _apply_and_hide_editor(self, force_apply=False):
        """Commit pending changes and dismiss inline text editor."""
        self._commit_inline_edit()

    def check_unsaved_changes(self, session: Optional[DocumentSession] = None):
        """Prompt user to save pending modifications. Returns True if cancelled."""
        target_session = session or getattr(self, '_active_session', None)
        if not target_session or not target_session.is_modified:
            return False

        if target_session != self._active_session:
            self.set_active_session(target_session)

        response = show_save_changes_dialog(self)
        
        if response == Gtk.ResponseType.ACCEPT:
            if target_session.pdf_path:
                self.save_document(target_session.pdf_path, incremental=False)
                return False
            else:
                self.on_save_as(None, None)
                return target_session.is_modified
        elif response == Gtk.ResponseType.REJECT:
            print(_("dbg_discarding_unsaved"))
            target_session.is_modified = False
            return False
        else:
            return True

        return False

    def on_drop(self, drop_target, value, x, y):
        """Handle drag-and-drop of PDF documents into the main viewer."""
        if isinstance(value, Gio.File):
            filepath = value.get_path()
            if filepath and filepath.lower().endswith('.pdf'):
                if self.doc:
                    self._offer_merge_or_open(filepath)
                else:
                    GLib.idle_add(self.load_document, filepath)
                return True
        return False

    def _offer_merge_or_open(self, filepath):
        """Prompt whether to append dropped PDF pages or open as a separate document."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("import_pdf_title"),
            secondary_text=_("import_pdf_confirm", os.path.basename(filepath))
        )
        
        dialog.add_buttons(
            _("btn_cancel"), Gtk.ResponseType.CANCEL,
            _("btn_confirm"), Gtk.ResponseType.ACCEPT
        )
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        
        def on_response(d, resp_id):
            d.destroy()
            if resp_id == Gtk.ResponseType.ACCEPT:
                self._merge_pdf_at_position(filepath, self.current_page_index + 1)
            elif resp_id == Gtk.ResponseType.CANCEL:
                GLib.idle_add(self.load_document, filepath, 0, True)
        
        dialog.connect("response", on_response)
        dialog.present()

    def _merge_pdf_at_position(self, source_pdf_path, insert_position):
        """Insert pages from another PDF file into the active document at insert_position."""
        success, message, pages_inserted = pdf_handler.merge_pdf_pages(
            self.doc, source_pdf_path, insert_position
        )
        
        if success:
            self.document_modified = True
            self.status_label.set_text(message)
            self._load_thumbnails()
            self._load_page(insert_position)
            self._update_ui_state()
        else:
            show_error_dialog(self, message, _("err_merge_title"))

    def on_thumbnail_drop(self, drop_target, value, x, y):
        """Handle drag-and-drop of a PDF onto the thumbnail sidebar to append pages."""
        if isinstance(value, Gio.File):
            filepath = value.get_path()
            if filepath and filepath.lower().endswith('.pdf'):
                insert_position = pdf_handler.get_page_count(self.doc)
                self._merge_pdf_at_position(filepath, insert_position)
                return True
        
        return False

    def on_open_clicked(self, button=None):
        """Prompt open file dialog to load an existing PDF into active or new tab."""
        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")
        filter_all = Gtk.FileFilter(name=_("filter_all"))
        filter_all.add_pattern("*")

        def on_open_finish(file):
            if file:
                GLib.idle_add(self.load_document, file.get_path())

        show_open_file_dialog(
            self,
            _("open_pdf_title"),
            filters=[filter_pdf, filter_all],
            default_filter=filter_pdf,
            callback=on_open_finish
        )

    def on_save_clicked(self, button):
        """Save active document to current path or prompt Save As if untitled."""
        if not self.doc:
            return
        if self.current_file_path:
            self.commit_pending_format_change()
            self.save_document(self.current_file_path, incremental=False)
        else:
            self.on_save_as(None, None)

    def on_save_as(self, action, param):
        """Prompt save file dialog to write PDF to a new destination."""
        self.commit_pending_format_change()
        if not self.doc: return

        initial_name = os.path.basename(self.current_file_path or "edited_document.pdf")
        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")

        def on_save_finish(file):
            if file:
                path = file.get_path()
                if not path.lower().endswith('.pdf'): path += '.pdf'
                self.save_document(path, incremental=False)

        show_save_file_dialog(
            self,
            _("save_as_title"),
            initial_name=initial_name,
            filters=[filter_pdf],
            default_filter=filter_pdf,
            callback=on_save_finish
        )

    def on_merge_documents(self, _action=None, _param=None):
        from .merge_dialog import MergeDialog
        if getattr(self, "_merge_dialog", None) is not None:
            self._merge_dialog.present()
            return
        self._merge_dialog = MergeDialog(parent_window=self)
        self._merge_dialog.connect("close-request", self._on_merge_dialog_closed)
        self._merge_dialog.present()

    def _on_merge_dialog_closed(self, dialog):
        if hasattr(dialog, "cleanup"):
            dialog.cleanup()
        self._merge_dialog = None
        return False

    def on_export_as(self, action=None, param=None):
        """Show modern export dialog with format and layout mode options."""
        self.show_export_dialog(initial_format="DOCX")

    def on_export_docx(self, action=None, param=None):
        """Direct export to DOCX: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("DOCX", mode="canvas")

    def on_export_pptx(self, action=None, param=None):
        """Direct export to PPTX: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("PPTX", mode="canvas")

    def on_export_odt(self, action=None, param=None):
        """Direct export to ODT: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("ODT", mode="canvas")

    def on_export_odp(self, action=None, param=None):
        """Direct export to ODP: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("ODP", mode="canvas")

    def on_export_txt(self, action=None, param=None):
        """Direct export to TXT: prompt destination directly."""
        self._prompt_export_destination("TXT", mode="canvas")

    def show_export_dialog(self, initial_format="DOCX"):
        """Show modern Libadwaita ExportDialog for document export settings."""
        if not self.doc:
            return
        from .export_dialog import ExportDialog
        dialog = ExportDialog(
            parent_window=self,
            initial_format=initial_format,
            initial_mode="canvas",
            on_confirm_callback=self._on_export_dialog_confirmed
        )
        dialog.present()

    def _on_export_dialog_confirmed(self, format_name, mode):
        """Handle confirmed format and mode selection from ExportDialog."""
        self._prompt_export_destination(format_name, mode=mode)

    def _prompt_export_destination(self, format_name, mode="canvas"):
        """Prompt file save dialog for chosen format and mode, then execute export."""
        if not self.doc:
            return

        base_name = Path(self.current_file_path).stem if self.current_file_path else "document"
        fmt_upper = str(format_name).upper().strip()
        fmt_lower = fmt_upper.lower()

        export_filters = {
            "DOCX": (_("filter_word"), "*.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "PPTX": (_("filter_pptx"), "*.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            "ODT": (_("filter_odt"), "*.odt", "application/vnd.oasis.opendocument.text"),
            "ODP": (_("filter_odp"), "*.odp", "application/vnd.oasis.opendocument.presentation"),
            "TXT": (_("filter_txt"), "*.txt", "text/plain"),
        }

        filter_list = []
        default_ff = None
        for name, (pattern_name, pattern, mime) in export_filters.items():
            ff = Gtk.FileFilter()
            ff.set_name(f"{name} - {pattern_name}")
            ff.add_pattern(pattern)
            if mime:
                ff.add_mime_type(mime)
            filter_list.append(ff)
            if name == fmt_upper:
                default_ff = ff

        def on_export_finish(file, selected_filter=None):
            if not file:
                return
            path = file.get_path()
            if not path:
                return
            self._execute_export(fmt_upper, path, mode=mode)

        show_save_file_dialog(
            self,
            _("export_as_title"),
            initial_name=f"{base_name}.{fmt_lower}",
            filters=filter_list,
            default_filter=default_ff,
            callback=on_export_finish
        )

    def _execute_export(self, format_name, output_path, mode="canvas", on_finish=None):
        """Execute export asynchronously in a background worker thread."""
        if not self.doc:
            if on_finish and callable(on_finish):
                on_finish(False, _("err_no_doc_msg"))
            return

        fmt_upper = str(format_name).upper().strip()
        fmt_lower = fmt_upper.lower()

        if not output_path.lower().endswith(f".{fmt_lower}"):
            output_path = f"{output_path}.{fmt_lower}"

        self.status_label.set_text(_("status_exporting", fmt_upper))

        try:
            pdf_bytes = self.doc.tobytes(garbage=4, clean=True, deflate=True)
        except Exception:
            try:
                pdf_bytes = self.doc.tobytes()
            except Exception:
                pdf_bytes = None

        doc_payload = pdf_bytes if pdf_bytes is not None else self.doc
        src_path = self.current_file_path

        def worker():
            success = False
            error_msg = _("err_unknown_export_format")
            try:
                if fmt_lower == "docx":
                    success, error_msg = pdf_handler.export_pdf_as_docx(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "odt":
                    success, error_msg = pdf_handler.export_pdf_as_odt(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "pptx":
                    success, error_msg = pdf_handler.export_pdf_as_pptx(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "odp":
                    success, error_msg = pdf_handler.export_pdf_as_odp(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "txt":
                    success, error_msg = pdf_handler.export_pdf_as_text(
                        doc_payload, output_path, mode=mode
                    )
                elif fmt_lower == "pdf":
                    success, error_msg = pdf_handler.save_document(
                        self.doc, output_path, incremental=False
                    )
                else:
                    success, error_msg = False, _("err_unknown_export_format")
            except Exception as e:
                success = False
                error_msg = str(e)

            GLib.idle_add(self._on_export_finished, success, error_msg, fmt_upper, output_path, on_finish)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_export_finished(self, success, error_msg, format_name, output_path, on_finish=None):
        """Handle export completion on the main GTK thread."""
        try:
            if success:
                self.status_label.set_text(_("status_exported", format_name, os.path.basename(output_path)))
                if format_name.lower() == "pdf":
                    self._update_ui_state()
            else:
                self.status_label.set_text(_("status_export_failed"))
                show_error_dialog(self, _("err_export_failed_msg", error_msg or _("status_export_failed")))
        finally:
            if on_finish and callable(on_finish):
                try:
                    on_finish(success, error_msg)
                except Exception:
                    pass
        return False

    def on_print_activated(self, action, param):
        """Initiate standard GTK print dialog workflow for the current document."""
        if not self.doc:
            show_error_dialog(self, _("print_no_doc"), _("print_no_doc_title"))
            return
        
        success, message = print_handler.print_document(self, self.doc)
        
        if success:
            if message:
                self.status_label.set_text(message)
        else:
            if message:
                show_error_dialog(self, message, _("print_error_title"))
                self.status_label.set_text(_("print_failed"))
            else:
                self.status_label.set_text(_("print_cancelled"))

    def _update_cursor_for_tool(self):
        """Restore cursor based on active tool mode."""
        if getattr(self, 'view_mode', False):
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))
        elif self.tool_mode == "select":
            self.pdf_view.set_cursor(None)
        elif self.tool_mode in ("add_text", "add_ellipse", "add_rectangle", "add_checkmark", "add_cross", "pen", "highlighter", "form_builder", "calibrate"):
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_image":
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("cell"))
        elif self.tool_mode == "drag":
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("move"))
        else:
            self.pdf_view.set_cursor(None)

    def _on_pointer_motion(self, controller, x, y):
        """Track last pointer position on pdf_view for focal zoom and update handle cursor."""
        self._last_pointer_pos = (x, y)
        if getattr(self, 'view_mode', False):
            page_offset_x = max(0, (self.pdf_view.get_allocated_width() - self.current_pdf_page_width) / 2)
            page_offset_y = max(0, (self.pdf_view.get_allocated_height() - self.current_pdf_page_height) / 2)
            vis_x = (x - page_offset_x) / self.zoom_level
            vis_y = (y - page_offset_y) / self.zoom_level
            unrot_x, unrot_y = self._visual_to_unrotated_page_coords(vis_x, vis_y)
            url = self._get_link_url_at_pos(unrot_x, unrot_y)
            if url:
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("pointer"))
                self.pdf_view.set_tooltip_text(url)
            else:
                self.pdf_view.set_tooltip_text(None)
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))
            return

        modifiers = controller.get_current_event_state() if controller else 0
        ctrl_pressed = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)
        if ctrl_pressed:
            page_offset_x = max(0, (self.pdf_view.get_allocated_width() - self.current_pdf_page_width) / 2)
            page_offset_y = max(0, (self.pdf_view.get_allocated_height() - self.current_pdf_page_height) / 2)
            vis_x = (x - page_offset_x) / self.zoom_level
            vis_y = (y - page_offset_y) / self.zoom_level
            unrot_x, unrot_y = self._visual_to_unrotated_page_coords(vis_x, vis_y)
            url = self._get_link_url_at_pos(unrot_x, unrot_y)
            if url:
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("pointer"))
                self.pdf_view.set_tooltip_text(url)
                return

        self.pdf_view.set_tooltip_text(None)

        if not getattr(self, 'dragged_object', None):
            selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                            getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None))
            if selected_obj:
                handle = self._find_resize_handle_at_pos(x, y, selected_obj)
                if handle == "rotate":
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
                    return
                elif handle in ("nw", "se"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("nwse-resize"))
                    return
                elif handle in ("ne", "sw"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("nesw-resize"))
                    return
                elif handle in ("n", "s"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("ns-resize"))
                    return
                elif handle in ("w", "e"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("ew-resize"))
                    return
                elif isinstance(selected_obj, AcroFormField) and getattr(self, 'tool_mode', None) in ("form_builder", "drag", "select"):
                    page_offset_x = max(0, (self.pdf_view.get_allocated_width() - self.current_pdf_page_width) / 2)
                    page_offset_y = max(0, (self.pdf_view.get_allocated_height() - self.current_pdf_page_height) / 2)
                    vis_x = (x - page_offset_x) / self.zoom_level
                    vis_y = (y - page_offset_y) / self.zoom_level
                    unrot_x, unrot_y = self._visual_to_unrotated_page_coords(vis_x, vis_y)
                    bx1, by1, bx2, by2 = selected_obj.bbox
                    if min(bx1, bx2) <= unrot_x <= max(bx1, bx2) and min(by1, by2) <= unrot_y <= max(by1, by2):
                        self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("grab"))
                        return
            self._update_cursor_for_tool()

    def _update_inline_editor_position(self):
        """Update inline editor position, size, and font scaling after zoom changes."""
        if not getattr(self, 'inline_editor_widget', None) or not getattr(self, 'inline_editor_text_obj', None):
            return
        text_obj = self.inline_editor_text_obj
        if not text_obj.bbox:
            return
        da_w = max(self.pdf_view.get_allocated_width(), self.current_pdf_page_width)
        da_h = max(self.pdf_view.get_allocated_height(), self.current_pdf_page_height)
        page_offset_x = max(0.0, (da_w - self.current_pdf_page_width) / 2.0)
        page_offset_y = max(0.0, (da_h - self.current_pdf_page_height) / 2.0)
        page = self.doc[self.current_page_index]
        target_box = getattr(self, '_inline_editor_target_rect', None) or text_obj.bbox
        vis_rect = (fitz.Rect(target_box) * page.rotation_matrix).normalize()
        ed_x = int(page_offset_x + vis_rect.x0 * self.zoom_level) - 2
        ed_y = int(page_offset_y + vis_rect.y0 * self.zoom_level) - 2
        scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
        ed_w = max(60, int(vis_rect.width * self.zoom_level) + 14)
        ed_h = max(int(scaled_font * 1.3) + 6, int(vis_rect.height * self.zoom_level) + 6)

        self._inline_editor_base_x = ed_x
        self._inline_editor_base_y = ed_y
        self._inline_editor_base_w = ed_w
        self._inline_editor_base_h = ed_h

        self.inline_editor_widget.set_margin_start(ed_x)
        self.inline_editor_widget.set_margin_top(ed_y)
        self._apply_inline_editor_style()
        if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
            self._on_inline_editor_text_changed(self.inline_editor_tv.get_buffer())
        else:
            self.inline_editor_widget.set_size_request(ed_w, ed_h)

    def _set_zoom(self, new_zoom, focal_point=None):
        """Set zoom level smoothly with focal point anchoring, without reloading page."""
        if not self.doc or not (0 <= self.current_page_index < pdf_handler.get_page_count(self.doc)):
            return

        clamped_zoom = max(0.1, min(8.0, new_zoom))
        if abs(clamped_zoom - self.zoom_level) < 0.001:
            return

        old_zoom = self.zoom_level
        self.zoom_level = clamped_zoom
        self.update_zoom_label()

        page = self.doc.load_page(self.current_page_index)
        new_page_w = int(page.rect.width * self.zoom_level)
        new_page_h = int(page.rect.height * self.zoom_level)

        h_adj = self.pdf_scroll.get_hadjustment()
        v_adj = self.pdf_scroll.get_vadjustment()

        # Viewport dimensions
        vp_w = h_adj.get_page_size() if h_adj and h_adj.get_page_size() > 0 else float(self.pdf_scroll.get_allocated_width())
        vp_h = v_adj.get_page_size() if v_adj and v_adj.get_page_size() > 0 else float(self.pdf_scroll.get_allocated_height())

        scroll_x = h_adj.get_value() if h_adj else 0.0
        scroll_y = v_adj.get_value() if v_adj else 0.0

        # Current allocated drawing area dimensions
        da_w = max(self.pdf_view.get_allocated_width(), self.current_pdf_page_width)
        da_h = max(self.pdf_view.get_allocated_height(), self.current_pdf_page_height)
        page_offset_x = max(0.0, (da_w - self.current_pdf_page_width) / 2.0)
        page_offset_y = max(0.0, (da_h - self.current_pdf_page_height) / 2.0)

        # Determine focal anchor on the PDF page and screen viewport
        if focal_point is not None:
            focus_x, focus_y = focal_point
            doc_x = (focus_x - page_offset_x) / old_zoom
            doc_y = (focus_y - page_offset_y) / old_zoom
            vp_x = focus_x - scroll_x
            vp_y = focus_y - scroll_y
        else:
            center_x = scroll_x + (vp_w / 2.0)
            center_y = scroll_y + (vp_h / 2.0)
            doc_x = (center_x - page_offset_x) / old_zoom
            doc_y = (center_y - page_offset_y) / old_zoom
            vp_x = vp_w / 2.0
            vp_y = vp_h / 2.0

        # Update content dimensions
        self.current_pdf_page_width = new_page_w
        self.current_pdf_page_height = new_page_h
        self.pdf_view.set_content_width(new_page_w)
        self.pdf_view.set_content_height(new_page_h)

        # Reposition active inline editor if open
        self._update_inline_editor_position()
        self._update_form_field_overlay_positions()

        # Calculate new offsets for new page size vs viewport
        new_da_w = max(new_page_w, int(vp_w))
        new_da_h = max(new_page_h, int(vp_h))
        new_offset_x = max(0.0, (new_da_w - new_page_w) / 2.0)
        new_offset_y = max(0.0, (new_da_h - new_page_h) / 2.0)

        new_focus_x = new_offset_x + (doc_x * self.zoom_level)
        new_focus_y = new_offset_y + (doc_y * self.zoom_level)

        new_scroll_x = new_focus_x - vp_x
        new_scroll_y = new_focus_y - vp_y

        def _apply_scroll():
            if h_adj:
                max_x = max(0.0, h_adj.get_upper() - h_adj.get_page_size())
                h_adj.set_value(max(0.0, min(new_scroll_x, max_x)))
            if v_adj:
                max_y = max(0.0, v_adj.get_upper() - v_adj.get_page_size())
                v_adj.set_value(max(0.0, min(new_scroll_y, max_y)))
            return False

        _apply_scroll()
        GLib.idle_add(_apply_scroll)

        self.pdf_view.queue_draw()

    def on_zoom_in(self, button=None, focal_point=None):
        if not self.doc: return
        self._set_zoom(self.zoom_level * 1.2, focal_point=focal_point)

    def on_zoom_out(self, button=None, focal_point=None):
        if not self.doc: return
        self._set_zoom(self.zoom_level / 1.2, focal_point=focal_point)

    def on_scroll_zoom(self, controller, dx, dy):
        """Zoom canvas in or out when Ctrl key is held during mouse scroll."""
        if controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            focal_point = getattr(self, '_last_pointer_pos', None)
            if dy < 0:
                self.on_zoom_in(focal_point=focal_point)
            elif dy > 0:
                self.on_zoom_out(focal_point=focal_point)
            return True
        return False

    def on_prev_page(self, button):
        if self.doc and self.current_page_index > 0:
            self._load_page(self.current_page_index - 1)

    def on_next_page(self, button):
        if self.doc and self.current_page_index < pdf_handler.get_page_count(self.doc) - 1:
            self._load_page(self.current_page_index + 1)

    def on_add_page(self, button):
        """Insert a new blank page with matching dimensions after current page."""
        if not self.doc:
            show_error_dialog(self, _("err_no_doc_msg"), _("err_no_doc_title"))
            return

        current_page = self.doc.load_page(self.current_page_index)
        page_width = current_page.rect.width
        page_height = current_page.rect.height
        insert_position = self.current_page_index + 1
        success, message = pdf_handler.insert_blank_page(self.doc, insert_position, page_width, page_height)

        if success:
            self.document_modified = True
            self.status_label.set_text(message)
            self._load_thumbnails()
            self._load_page(insert_position)
            self._update_ui_state()
        else:
            show_error_dialog(self, message, _("err_add_page_title"))

    def on_delete_page(self, button):
        self._delete_page_at_index(self.current_page_index)

    def _delete_page_at_index(self, page_to_delete):
        """Delete the specified page index with confirmation."""
        if not self.doc:
            show_error_dialog(self, _("err_no_doc_open_msg"), _("err_no_doc_title"))
            return

        page_count = pdf_handler.get_page_count(self.doc)
        if page_count <= 1:
            show_error_dialog(self, _("err_cannot_delete_last_page"), _("err_cannot_delete_last_page_title"))
            return

        confirmed = show_confirm_dialog(
            self,
            _("delete_page_warn_msg", page_to_delete + 1),
            _("delete_page_warn_title"),
            destructive=True
        )

        if not confirmed:
            self.status_label.set_text("Sayfa silme iptal edildi.")
            return

        success, message = pdf_handler.delete_page(self.doc, page_to_delete)

        if success:
            self.document_modified = True
            self.status_label.set_text(message)
            new_page_count = pdf_handler.get_page_count(self.doc)
            new_page_index = min(page_to_delete, new_page_count - 1)
            self._load_thumbnails()
            self._load_page(new_page_index)
            self._update_ui_state()
        else:
            show_error_dialog(self, message, _("err_delete_page_title"))

    def rotate_current_page(self, angle_delta, page_index=None):
        """Rotate the specified or current page by angle_delta degrees (+90 or -90)."""
        if not self.doc:
            return
        target_idx = self.current_page_index if page_index is None else page_index
        if not (0 <= target_idx < pdf_handler.get_page_count(self.doc)):
            return
        from .undo_manager import RotatePageCommand
        cmd = RotatePageCommand(self, target_idx, angle_delta)
        cmd.execute()
        self.undo_manager.add_command(cmd)
        msg_key = "status_page_rotated_cw" if angle_delta > 0 else "status_page_rotated_ccw"
        self.status_label.set_text(_(msg_key, target_idx + 1))

    def show_thumbnail_context_menu(self, parent_widget, x, y, page_index):
        """Show context menu for a page thumbnail with rotation and deletion options."""
        if not self.doc:
            return

        if hasattr(self, '_thumb_context_popover') and self._thumb_context_popover:
            self._thumb_context_popover.popdown()
            self._thumb_context_popover.unparent()
            self._thumb_context_popover = None

        popover = Gtk.Popover(autohide=True, has_arrow=True)
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        popover_box.set_margin_start(6)
        popover_box.set_margin_end(6)
        popover_box.set_margin_top(6)
        popover_box.set_margin_bottom(6)

        btn_cw = Gtk.Button(label=_("rotate_cw"))
        btn_cw.add_css_class("flat")
        btn_cw.set_tooltip_text("Ctrl+Shift+R")
        def on_cw(b):
            popover.popdown()
            self.rotate_current_page(90, page_index=page_index)
        btn_cw.connect("clicked", on_cw)
        popover_box.append(btn_cw)

        btn_ccw = Gtk.Button(label=_("rotate_ccw"))
        btn_ccw.add_css_class("flat")
        btn_ccw.set_tooltip_text("Ctrl+Shift+L")
        def on_ccw(b):
            popover.popdown()
            self.rotate_current_page(-90, page_index=page_index)
        btn_ccw.connect("clicked", on_ccw)
        popover_box.append(btn_ccw)

        in_edit = not getattr(self, 'view_mode', False)
        page_count = pdf_handler.get_page_count(self.doc) if self.doc else 0
        if in_edit and page_count > 1:
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            btn_del = Gtk.Button(label=_("delete_page_title"))
            btn_del.add_css_class("flat")
            btn_del.add_css_class("destructive-action")
            def on_del(b):
                popover.popdown()
                self._delete_page_at_index(page_index)
            btn_del.connect("clicked", on_del)
            popover_box.append(btn_del)

        popover.set_child(popover_box)
        popover.set_parent(parent_widget)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        self._thumb_context_popover = popover
        popover.popup()

    def update_page_label(self):
        """Update the page indicator label with current page number and total count."""
        count = pdf_handler.get_page_count(self.doc)
        self.page_label.set_text(_("page_info_count").format(self.current_page_index + 1, count) if count > 0 else _("page_info_count").format(0, 0))

    def update_zoom_label(self):
        """Update the zoom indicator label with current active session zoom level."""
        zoom = getattr(self, 'zoom_level', 1.0)
        if hasattr(self, 'zoom_label') and self.zoom_label is not None:
            self.zoom_label.set_text(f"{int(round(zoom * 100))}%")

    def on_thumbnail_selected(self, selection_model, position, n_items):
         """Navigate to page selected in the thumbnail sidebar."""
         selected_index = selection_model.get_selected()
         if selected_index != Gtk.INVALID_LIST_POSITION and selected_index != self.current_page_index:
              if hasattr(self, '_syncing_thumb') and self._syncing_thumb: return
              self._load_page(selected_index)

    def _sync_thumbnail_selection(self):
         """Update sidebar thumbnail selection without re-triggering navigation."""
         if not self.doc or not self.thumbnail_selection_model: return
         self._syncing_thumb = True
         self.thumbnail_selection_model.set_selected(self.current_page_index)
         self._syncing_thumb = False

    @property
    def edit_mode(self):
        """Return True if currently in edit mode."""
        return not getattr(self, 'view_mode', True)

    def on_page_reorder(self, from_index, to_index):
         """Move a page in the document when reordered via drag-and-drop in thumbnail list."""
         if getattr(self, 'view_mode', False) or not self.edit_mode:
             return
         if from_index == to_index or from_index < 0 or to_index < 0:
             return
         
         success, message = pdf_handler.move_page(self.doc, from_index, to_index)
         
         if success:
             self.document_modified = True
             self.status_label.set_text(message)
             self._load_thumbnails()
             self._load_page(to_index)
             self._update_ui_state()
         else:
             show_error_dialog(self, message, _("err_move_page_title"))


    def on_pdf_view_pressed(self, gesture, n_press, x, y):
        """Handle primary mouse button press for object selection, links, or tool starts."""
        if not self.doc or self.current_pdf_page_width == 0 or self.current_pdf_page_height == 0:
            return

        drawing_area_width = self.pdf_view.get_allocated_width()
        drawing_area_height = self.pdf_view.get_allocated_height()
        page_offset_x = max(0, (drawing_area_width - self.current_pdf_page_width) / 2)
        page_offset_y = max(0, (drawing_area_height - self.current_pdf_page_height) / 2)

        page_x_unzoomed = (x - page_offset_x) / self.zoom_level
        page_y_unzoomed = (y - page_offset_y) / self.zoom_level

        modifiers = Gtk.EventController.get_current_event_state(gesture) if gesture is not None else 0
        ctrl_pressed = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)

        clicked_text = self._find_text_at_pos(page_x_unzoomed, page_y_unzoomed)
        
        if ctrl_pressed:
            url = self._get_link_url_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_get_link_url_at_pos') else None
            if url:
                self._open_url(url)
                return

        if self.view_mode:
            if n_press == 1:
                url = self._get_link_url_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_get_link_url_at_pos') else None
                if url:
                    self._open_url(url)
                    return
                clicked_form_field = self._find_form_field_at_pos(page_x_unzoomed, page_y_unzoomed)
                if clicked_form_field:
                    self.selected_form_field = clicked_form_field
                    self._open_form_field_editor(clicked_form_field)
                    self.view_sel_start = None
                    self.view_sel_rect = None
                    self.view_selected_text = ""
                    self.word_selection_mode = False
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
                    return
                else:
                    self._close_active_form_field_editor()

                clicked_block = pdf_handler.get_block_at_pos(self.doc, self.current_page_index, (page_x_unzoomed, page_y_unzoomed))
                if clicked_block:
                    self.selected_form_field = None
                    self.view_sel_rect = clicked_block['bbox']
                    self.view_selected_text = clicked_block['text']
                    self.word_selection_mode = False
                else:
                    self.selected_form_field = None
                    self.view_sel_start = None
                    self.view_sel_rect = None
                    self.view_selected_text = ""
                    self.word_selection_mode = False
                self.pdf_view.queue_draw()
                self._update_ui_state()
            return

        if self.font_scan_in_progress:
            show_error_dialog(self, _("err_fonts_scanning_msg"), _("err_fonts_scanning_title"))
            return

        drawing_area_width = self.pdf_view.get_allocated_width()
        drawing_area_height = self.pdf_view.get_allocated_height()

        page_w_zoomed = self.current_pdf_page_width
        page_h_zoomed = self.current_pdf_page_height

        page_offset_x = max(0, (drawing_area_width - page_w_zoomed) / 2)
        page_offset_y = max(0, (drawing_area_height - page_h_zoomed) / 2)

        click_x_on_page_zoomed = x - page_offset_x
        click_y_on_page_zoomed = y - page_offset_y

        is_on_page = (0 <= click_x_on_page_zoomed < page_w_zoomed and
                    0 <= click_y_on_page_zoomed < page_h_zoomed)
        
        self.commit_pending_format_change()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.grab_focus()

        if not is_on_page:
            if self.inline_editor_widget is not None:
                self._apply_and_hide_editor()
            if getattr(self, '_active_editing_form_field', None) is not None:
                self._close_active_form_field_editor()
            self.selected_text = None
            self.selected_image = None
            self.selected_form_field = None
            self.pdf_view.queue_draw()
            self._update_ui_state()
            return

        page_x_unzoomed = click_x_on_page_zoomed / self.zoom_level
        page_y_unzoomed = click_y_on_page_zoomed / self.zoom_level


        if self.tool_mode == "select":
            if self.inline_editor_widget is not None:
                self._apply_and_hide_editor()

            clicked_image = self._find_image_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_text = self._find_text_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_shape = self._find_shape_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_stroke = self._find_stroke_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_form_field = self._find_form_field_at_pos(page_x_unzoomed, page_y_unzoomed)

            if clicked_image:
                self._close_active_form_field_editor()
                self.selected_image = clicked_image
                self.selected_text = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = None
            elif clicked_text:
                self._close_active_form_field_editor()
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = None
                self.selected_text = clicked_text
                self.word_selection_mode = False
                self.pending_format_change_obj = self.selected_text
                self.before_format_change_state = copy.deepcopy(self.selected_text.__dict__)
                self._update_text_format_controls(self.selected_text)
                if n_press >= 2 and not self.view_mode:
                    self._show_inline_editor(clicked_text, click_x=x, click_y=y)
            elif clicked_shape:
                self._close_active_form_field_editor()
                self.selected_shape = clicked_shape
                self.selected_text = None
                self.selected_image = None
                self.selected_stroke = None
                self.selected_form_field = None
            elif clicked_stroke:
                self._close_active_form_field_editor()
                self.selected_stroke = clicked_stroke
                self.selected_shape = None
                self.selected_text = None
                self.selected_image = None
                self.selected_form_field = None
                self._update_stroke_format_controls(self.selected_stroke)
            elif clicked_form_field:
                self._close_active_form_field_editor()
                self.selected_text = None
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = clicked_form_field
                self._update_form_builder_controls_for_selected()
            else:
                self._close_active_form_field_editor()
                if not self.view_mode and self.doc and 0 <= self.current_page_index < pdf_handler.get_page_count(self.doc):
                    hit_word = pdf_handler.hit_test_text_word_at_pos(
                        self.doc, (page_x_unzoomed, page_y_unzoomed), page_index=self.current_page_index, visual_coords=True
                    )
                    if hit_word:
                        found_text = None
                        wb = hit_word["bbox"]
                        for et in self.editable_texts:
                            if getattr(et, 'page_number', self.current_page_index) == self.current_page_index and getattr(et, 'bbox', None):
                                eb = et.bbox
                                if not (wb[2] < eb[0] or wb[0] > eb[2] or wb[3] < eb[1] or wb[1] > eb[3]):
                                    found_text = et
                                    break
                        if not found_text:
                            span_hit = hit_word.get("span", {})
                            span_text = span_hit.get("text", hit_word["word"])
                            span_bbox = span_hit.get("bbox", hit_word["bbox"])
                            span_origin = span_hit.get("origin", (span_bbox[0], span_bbox[3]))
                            found_text = EditableText(
                                x=span_bbox[0],
                                y=span_bbox[1],
                                text=span_text,
                                font_size=span_hit.get("size", 11),
                                font_family=span_hit.get("font", "Liberation Sans"),
                                color=span_hit.get("color", (0, 0, 0)),
                                span_data=span_hit,
                                baseline=span_origin[1],
                                rotation=span_hit.get("rotation", 0.0),
                                page_number=self.current_page_index
                            )
                            found_text.bbox = tuple(span_bbox)
                            found_text.original_bbox = tuple(span_bbox)
                            found_text.char_boxes = hit_word.get("char_boxes", [])
                            self.editable_texts.append(found_text)

                        self.selected_text = found_text
                        self.selected_image = None
                        self.selected_shape = None
                        self.selected_stroke = None
                        self.selected_form_field = None
                        self.word_selection_mode = False
                        self.pending_format_change_obj = found_text
                        self.before_format_change_state = copy.deepcopy(found_text.__dict__)
                        self._update_text_format_controls(found_text)
                        if n_press >= 2:
                            self._show_inline_editor(found_text, click_x=x, click_y=y)
                        self.pdf_view.queue_draw()
                        self._update_ui_state()
                        return

                self.selected_text = None
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = None

            self.pdf_view.queue_draw()
            self._update_ui_state()

        elif self.tool_mode == "add_text":
            if self.inline_editor_widget is not None:
                self._apply_and_hide_editor()
                return

            font_fam_display, font_pdf_name, font_size, color, is_bold, is_italic, is_underline, is_strikethrough, alignment = self._get_current_format_settings()
            if self._last_font_family is not None:
                font_fam_display = self._last_font_family
                font_size = self._last_font_size
                is_bold = self._last_is_bold
                is_italic = self._last_is_italic
                is_underline = getattr(self, 'underline_button', None).get_active() if hasattr(self, 'underline_button') else False
                is_strikethrough = getattr(self, 'strikethrough_button', None).get_active() if hasattr(self, 'strikethrough_button') else False
                alignment = self._get_current_alignment()
                color = self._last_color
            unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x_unzoomed, page_y_unzoomed)
            baseline_y_unzoomed = unrot_y + (font_size * 0.9)

            target_family_key = font_fam_display
            target_base14 = 'helv'
            iter = self.font_combo.get_active_iter()
            if iter:
                model_key = self.font_store[iter][1]
                normalized_for_base14 = re.sub(r'[^a-zA-Z0-9]', '', model_key).lower()
                for name_key, base14_val in BASE14_FALLBACK_MAP.items():
                    if name_key in normalized_for_base14:
                        target_base14 = base14_val
                        break

            new_text_obj = EditableText(
                x=unrot_x,
                y=unrot_y,
                text=_("default_new_text"),
                font_size=font_size,
                color=color,
                is_new=True,
                baseline=baseline_y_unzoomed
            )
            new_text_obj.font_family_base = target_family_key
            new_text_obj.font_family_original = _("font_user_added", target_family_key)
            new_text_obj.is_bold = is_bold
            new_text_obj.is_italic = is_italic
            new_text_obj.is_underline = is_underline
            new_text_obj.is_strikethrough = is_strikethrough
            new_text_obj.alignment = alignment
            new_text_obj.pdf_fontname_base14 = target_base14
            new_text_obj.page_number = self.current_page_index

            self.selected_text = new_text_obj
            self.selected_image = None
            self._update_text_format_controls(self.selected_text)
            self._show_inline_editor(new_text_obj, click_x=x, click_y=y)
            self._update_ui_state()

        elif self.tool_mode == "add_image":
            # patched
            pass

        elif self.tool_mode == "add_ellipse":
            # patched
            pass

        elif self.tool_mode == "add_rectangle":
            # patched
            pass

        elif self.tool_mode == "form_builder":
            clicked_form_field = self._find_form_field_at_pos(page_x_unzoomed, page_y_unzoomed)
            if clicked_form_field:
                self._close_active_form_field_editor()
                self.selected_text = None
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = clicked_form_field
                self._update_form_builder_controls_for_selected()
                if n_press >= 2 and hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry and self.form_builder_name_entry.get_visible():
                    self.form_builder_name_entry.grab_focus()
                    self.form_builder_name_entry.select_region(0, -1)
            else:
                self._close_active_form_field_editor()
                self.selected_form_field = None
                self._update_form_builder_controls_for_selected()
            self.pdf_view.queue_draw()
            self._update_ui_state()
            return

    def on_text_format_changed(self, widget, *args):
        """Apply typography updates (font family, size, style, color, alignment) to selected text."""
        if self.font_scan_in_progress:
            return

        iter = self.font_combo.get_active_iter()
        if iter:
            self._last_font_family = self.font_store[iter][1]
        self._last_font_size = self.font_size_spin.get_value()
        self._last_is_bold = self.bold_button.get_active() if self.bold_button else False
        self._last_is_italic = self.italic_button.get_active() if self.italic_button else False
        self._last_is_strikethrough = getattr(self, 'strikethrough_button', None).get_active() if hasattr(self, 'strikethrough_button') else False
        rgba = self.color_button.get_rgba()
        self._last_color = (rgba.red, rgba.green, rgba.blue)
        
        font_family_key = self._last_font_family
        font_size = self._last_font_size
        color = self._last_color
        is_bold = self._last_is_bold
        is_italic = self._last_is_italic
        is_underline = getattr(self, 'underline_button', None).get_active() if hasattr(self, 'underline_button') else False
        is_strikethrough = getattr(self, 'strikethrough_button', None).get_active() if hasattr(self, 'strikethrough_button') else False
        align_btns = [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                      getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]
        if widget in align_btns and not widget.get_active():
            def check_restore_active(deactivated_btn):
                if all(b and not b.get_active() for b in align_btns if b):
                    deactivated_btn.handler_block_by_func(self.on_text_format_changed)
                    deactivated_btn.set_active(True)
                    deactivated_btn.handler_unblock_by_func(self.on_text_format_changed)
                return False
            GLib.idle_add(check_restore_active, widget)
            return

        if widget in align_btns and widget.get_active():
            for b in align_btns:
                if b and b != widget and b.get_active():
                    b.handler_block_by_func(self.on_text_format_changed)
                    b.set_active(False)
                    b.handler_unblock_by_func(self.on_text_format_changed)

        alignment = self._get_current_alignment()
        self._last_alignment = alignment
        
        if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
            if alignment == 'center':
                self.inline_editor_tv.set_justification(Gtk.Justification.CENTER)
            elif alignment == 'right':
                self.inline_editor_tv.set_justification(Gtk.Justification.RIGHT)
            elif alignment == 'justify':
                self.inline_editor_tv.set_justification(Gtk.Justification.FILL)
            else:
                self.inline_editor_tv.set_justification(Gtk.Justification.LEFT)
        
        if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv and self.inline_editor_text_obj:
            buf = self.inline_editor_tv.get_buffer()
            has_sel, start_iter, end_iter = buf.get_selection_bounds()
            if has_sel:
                start_char = start_iter.get_offset()
                end_char = end_iter.get_offset()
                current_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
                
                self._hide_inline_editor()
                
                target_obj = self.inline_editor_text_obj
                target_obj.text = current_text
                spans = target_obj.split_at_range(start_char, end_char)
                
                if len(spans) > 1:
                    mid_index = 0 if start_char == 0 else 1
                    mid_span = spans[mid_index]
                    mid_span.font_family_base = font_family_key
                    mid_span.font_size = font_size
                    mid_span.color = color
                    mid_span.is_bold = is_bold
                    mid_span.is_italic = is_italic
                    mid_span.is_underline = is_underline
                    mid_span.is_strikethrough = is_strikethrough
                    mid_span.alignment = alignment
                    
                    from .undo_manager import DeleteObjectCommand, AddObjectCommand, CompositeCommand
                    commands = [DeleteObjectCommand(self, target_obj)]
                    for span in spans:
                        commands.append(AddObjectCommand(self, span))
                    
                    batch_cmd = CompositeCommand(self, commands)
                    batch_cmd.execute()
                    self.undo_manager.add_command(batch_cmd)
                    self.selected_text = mid_span
                    self.pending_format_change_obj = mid_span
                    self._update_ui_state()
                    self.pdf_view.queue_draw()
                    return

        if getattr(self, 'word_selection_mode', False) and self.selected_text and hasattr(self, 'selected_word_start_char') and hasattr(self, 'selected_word_end_char'):
            start_char = self.selected_word_start_char
            end_char = self.selected_word_end_char
            target_obj = self.selected_text
            spans = target_obj.split_at_range(start_char, end_char)
            
            if len(spans) > 1:
                mid_index = 0 if start_char == 0 else 1
                mid_span = spans[mid_index]
                if self._last_font_family: mid_span.font_family_base = self._last_font_family
                mid_span.font_size = self._last_font_size
                mid_span.is_bold = is_bold
                mid_span.is_italic = is_italic
                mid_span.is_underline = is_underline
                mid_span.is_strikethrough = is_strikethrough
                mid_span.alignment = alignment
                mid_span.color = color
                
                from .undo_manager import DeleteObjectCommand, AddObjectCommand, CompositeCommand
                commands = [DeleteObjectCommand(self, target_obj)]
                for span in spans:
                    commands.append(AddObjectCommand(self, span))
                
                batch_cmd = CompositeCommand(self, commands)
                batch_cmd.execute()
                self.undo_manager.add_command(batch_cmd)
                
                self.selected_text = mid_span
                self.pending_format_change_obj = mid_span
                self.selected_text = mid_span
                self.pending_format_change_obj = mid_span
                self.before_format_change_state = copy.deepcopy(mid_span.__dict__)
                
                self.selected_word_start_char = 0
                self.selected_word_end_char = len(mid_span.text)
                
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return

        target_text = self.pending_format_change_obj or self.selected_text
        if target_text:
            if not self.pending_format_change_obj:
                self.pending_format_change_obj = target_text
                self.before_format_change_state = copy.deepcopy(target_text.__dict__)
            changed = False

            if font_family_key and self.pending_format_change_obj.font_family_base != font_family_key:
                self.pending_format_change_obj.font_family_base = font_family_key
                changed = True
            
            if self.pending_format_change_obj.font_size != font_size:
                self.pending_format_change_obj.font_size = font_size
                changed = True
                obj = self.pending_format_change_obj
                if obj.bbox:
                    x1, y1, x2, y2 = obj.bbox
                    old_h = y2 - y1
                    old_w = x2 - x1
                    try:
                        _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
                        _cr = cairo.Context(_surf)
                        _layout = PangoCairo.create_layout(_cr)
                        _fd_str = f"{obj.font_family_base} {font_size}"
                        if obj.is_bold: _fd_str += " Bold"
                        if obj.is_italic: _fd_str += " Italic"
                        _layout.set_font_description(Pango.FontDescription.from_string(_fd_str))
                        _layout.set_text(obj.text if obj.text else "Ay", -1)
                        _p_w, _p_h = _layout.get_size()
                        
                        _w = (_p_w / Pango.SCALE) * 0.75
                        _h = (_p_h / Pango.SCALE) * 0.75
                        
                        new_w = max(_w, old_w) if _w > 0 else old_w
                        new_h = _h if _h > 0 else old_h
                        obj.bbox = (x1, y1, x1 + new_w, y1 + new_h)
                    except Exception as e:
                        print(f"DEBUG: Error recalculating text bbox: {e}")
                        pass
                
            if self.pending_format_change_obj.is_bold != is_bold:
                self.pending_format_change_obj.is_bold = is_bold
                changed = True
            if self.pending_format_change_obj.is_italic != is_italic:
                self.pending_format_change_obj.is_italic = is_italic
                changed = True
            if getattr(self.pending_format_change_obj, 'is_underline', False) != is_underline:
                self.pending_format_change_obj.is_underline = is_underline
                changed = True
            if getattr(self.pending_format_change_obj, 'is_strikethrough', False) != is_strikethrough:
                self.pending_format_change_obj.is_strikethrough = is_strikethrough
                changed = True
            if getattr(self.pending_format_change_obj, 'alignment', 'left') != alignment:
                self.pending_format_change_obj.alignment = alignment
                changed = True

            if self.pending_format_change_obj.color != color:
                self.pending_format_change_obj.color = color
                changed = True
                
            if changed and self.pending_format_change_obj.bbox:
                obj = self.pending_format_change_obj
                x1, y1, x2, y2 = obj.bbox
                try:
                    _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
                    _cr = cairo.Context(_surf)
                    _layout = PangoCairo.create_layout(_cr)
                    font_desc = Pango.FontDescription.from_string(obj.font_family_base)
                    if obj.is_bold: font_desc.set_weight(Pango.Weight.BOLD)
                    if obj.is_italic: font_desc.set_style(Pango.Style.ITALIC)
                    font_desc.set_absolute_size(int(obj.font_size * Pango.SCALE))
                    _layout.set_font_description(font_desc)
                    _layout.set_text(obj.text if obj.text else "Ay", -1)
                    _p_w, _p_h = _layout.get_size()
                    _w = (_p_w / Pango.SCALE)
                    _h = (_p_h / Pango.SCALE)
                    if _w > 0 and _h > 0:
                        old_w = x2 - x1
                        final_w = max(_w, old_w) if getattr(obj, 'alignment', 'left') != 'left' else _w
                        obj.bbox = (x1, y1, x1 + final_w, y1 + _h)
                except Exception as e:
                    print(f"DEBUG: Error recalculating text bbox on format change: {e}")

            if changed:
                obj = self.pending_format_change_obj
                if self.inline_editor_widget is not None:
                    self._apply_and_hide_editor(force_apply=True)
                else:
                    new_properties = copy.deepcopy(obj.__dict__)
                    obj.__dict__.update(self.before_format_change_state)
                    command = EditObjectCommand(self, obj, self.before_format_change_state, new_properties)
                    command.execute()
                    self.undo_manager.add_command(command)
                    self.before_format_change_state = copy.deepcopy(obj.__dict__)
                    self.pdf_view.queue_draw()
                    self._update_ui_state()

    def on_shape_format_changed(self, widget, *args):
        """Apply shape fill, stroke color, and line width updates to selection or next shape."""
        fill_rgba = self.shape_fill_button.get_rgba()
        fill_color = (fill_rgba.red, fill_rgba.green, fill_rgba.blue)
        stroke_rgba = self.shape_stroke_button.get_rgba()
        stroke_color = (stroke_rgba.red, stroke_rgba.green, stroke_rgba.blue)
        stroke_width = self.shape_stroke_width_spin.get_value()
        is_transparent = self.shape_transparent_toggle.get_active()
        self.next_shape_fill = fill_color
        self.next_shape_stroke = stroke_color
        self.next_shape_stroke_width = stroke_width
        self.next_shape_transparent = is_transparent

        if self.selected_shape:
            old_properties = copy.deepcopy(self.selected_shape.__dict__)
            changed = False
            if self.selected_shape.fill_color != fill_color:
                self.selected_shape.fill_color = fill_color
                changed = True
            if self.selected_shape.stroke_color != stroke_color:
                self.selected_shape.stroke_color = stroke_color
                changed = True
            if self.selected_shape.stroke_width != stroke_width:
                self.selected_shape.stroke_width = stroke_width
                changed = True
            if self.selected_shape.is_transparent != is_transparent:
                self.selected_shape.is_transparent = is_transparent
                changed = True

            if changed:
                new_properties = copy.deepcopy(self.selected_shape.__dict__)
                self.selected_shape.__dict__.update(old_properties)
                
                command = EditObjectCommand(self, self.selected_shape, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.pdf_view.queue_draw()
                self._update_ui_state()

    def on_stroke_format_changed(self, widget, *args):
        """Apply stroke color or line width updates to active drawing tool or selected stroke."""
        stroke_rgba = self.stroke_color_button.get_rgba()
        stroke_color = (stroke_rgba.red, stroke_rgba.green, stroke_rgba.blue)
        stroke_width = self.stroke_width_spin.get_value()

        if self.tool_mode == "highlighter" or (self.selected_stroke and self.selected_stroke.tool_type == "highlighter"):
            self.highlighter_color = stroke_color
            self.highlighter_width = stroke_width
        else:
            self.pen_color = stroke_color
            self.pen_width = stroke_width

        if self.selected_stroke:
            old_properties = copy.deepcopy(self.selected_stroke.__dict__)
            changed = False
            if self.selected_stroke.stroke_color != stroke_color:
                self.selected_stroke.stroke_color = stroke_color
                changed = True
            if self.selected_stroke.stroke_width != stroke_width:
                self.selected_stroke.stroke_width = stroke_width
                self.selected_stroke.recalculate_bbox()
                changed = True

            if changed:
                new_properties = copy.deepcopy(self.selected_stroke.__dict__)
                self.selected_stroke.__dict__.update(old_properties)

                command = EditObjectCommand(self, self.selected_stroke, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.pdf_view.queue_draw()
                self._update_ui_state()

    def on_text_edit_done(self, button):
        """Explicitly commit pending inline text edits and dismiss the editor."""
        self._apply_and_hide_editor(force_apply=True)

    def on_key_pressed(self, controller, keyval, keycode, state):
        """Handle global keyboard shortcuts (undo/redo, delete, zoom, navigation, escape)."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if self.view_mode:
            if keyval == Gdk.KEY_Escape:
                self.view_sel_rect = None
                self.view_sel_start = None
                self.view_selected_text = ""
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return True
            if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
                if self.view_selected_text:
                    clipboard = self.get_clipboard()
                    clipboard.set(self.view_selected_text)
                return True
            if ctrl and keyval in (Gdk.KEY_n, Gdk.KEY_N):
                self.on_new_clicked(None)
                return True
            if ctrl and keyval in (Gdk.KEY_o, Gdk.KEY_O):
                self.on_open_clicked(None)
                return True
            if ctrl and keyval in (Gdk.KEY_w, Gdk.KEY_W):
                self.on_close_tab()
                return True
            if ctrl and keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Tab):
                self.on_next_tab()
                return True
            if ctrl and keyval in (Gdk.KEY_Page_Up, Gdk.KEY_ISO_Left_Tab):
                self.on_prev_tab()
                return True
            return False

        if keyval == Gdk.KEY_Escape:
            if getattr(self, '_active_editing_form_field', None) is not None:
                self._close_active_form_field_editor()
                return True
            elif self.inline_editor_widget is not None:
                 self.hide_text_editor()
                 if self.selected_text and self.selected_text.is_new:
                      self.selected_text = None
                      self.pdf_view.queue_draw()
                 elif self.selected_text:
                      self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif self.selected_text:
                 self.selected_text = None
                 self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif getattr(self, 'selected_form_field', None):
                 self.selected_form_field = None
                 self._update_form_builder_controls_for_selected()
                 self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif getattr(self, 'selected_stroke', None):
                 self.selected_stroke = None
                 self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif self.tool_mode in ("add_text", "pen", "highlighter"):
                 self.on_tool_selected(None, "select")
                 return True

        if keyval == Gdk.KEY_F1:
            self.activate_action("quick_guide", None)
            return True

        if ctrl and keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self.on_new_clicked(None)
            return True
        elif ctrl and keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self.on_open_clicked(None)
            return True
        elif ctrl and keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self.on_close_tab()
            return True
        elif ctrl and keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Tab):
            self.on_next_tab()
            return True
        elif ctrl and keyval in (Gdk.KEY_Page_Up, Gdk.KEY_ISO_Left_Tab):
            self.on_prev_tab()
            return True
        elif ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.on_save_clicked(None)
            return True
        elif ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.on_zoom_in(focal_point=getattr(self, '_last_pointer_pos', None))
            return True
        elif ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.on_zoom_out(focal_point=getattr(self, '_last_pointer_pos', None))
            return True
        elif ctrl and keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self._set_zoom(1.0, focal_point=getattr(self, '_last_pointer_pos', None))
            return True

        focus_w = self.get_focus()
        is_editing_form = (getattr(self, '_active_editing_form_field', None) is not None)
        is_editing_entry = (
            (self.inline_editor_widget is not None)
            or is_editing_form
            or (focus_w is not None and focus_w is getattr(self, 'form_builder_name_entry', None))
            or (focus_w is not None and focus_w is getattr(self, 'form_builder_label_entry', None))
            or (focus_w is not None and focus_w is getattr(self, 'form_builder_options_entry', None))
        )
        is_input_focused = is_editing_entry or isinstance(focus_w, (Gtk.Editable, Gtk.TextView, Gtk.DropDown))

        if getattr(self, 'selected_text', None) and not is_input_focused and not getattr(self, 'view_mode', False):
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_F2):
                self._show_inline_editor(self.selected_text)
                return True

        if getattr(self, 'selected_form_field', None) and not is_input_focused:
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_F2):
                if getattr(self, 'view_mode', False):
                    self._open_form_field_editor(self.selected_form_field)
                    return True
                elif getattr(self, 'tool_mode', '') == "form_builder" and hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry and self.form_builder_name_entry.get_visible():
                    self.form_builder_name_entry.grab_focus()
                    self.form_builder_name_entry.select_region(0, -1)
                    return True

        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if getattr(self, 'selected_form_field', None) and not is_editing_entry:
                self._delete_selected_form_field()
                return True

        if keyval == Gdk.KEY_Delete:
            self.commit_pending_format_change()
            obj_to_delete = (self.selected_text or self.selected_image or self.selected_shape or 
                             getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None))
            if obj_to_delete and not is_input_focused:
                self._handle_delete_with_confirmation(obj_to_delete, "delete_confirm_title")
                return True
            elif self.selected_image:
                confirm = show_confirm_dialog(self, _("image_delete_confirm_msg"), _("image_delete_confirm_title"))
                if confirm:
                    self.status_label.set_text("Resim siliniyor...")
                    success, error_msg = pdf_handler.delete_image_from_page(self.doc, self.selected_image)
                    if success:
                        self.document_modified = True
                        self._load_page(self.current_page_index)
                        self.status_label.set_text("Resim silindi.")
                    else:
                        show_error_dialog(self, _("err_image_delete_msg", error_msg), _("err_image_delete_title"))
                    self.selected_image = None
                    self._update_ui_state()
        # Arrow key nudge movement (1pt normal / 10pt with Shift) for selected objects
        if not is_input_focused and keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
            selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                            getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None))
            if selected_obj:
                step = 10.0 if bool(state & Gdk.ModifierType.SHIFT_MASK) else 1.0
                dx, dy = 0.0, 0.0
                if keyval == Gdk.KEY_Left:
                    dx = -step
                elif keyval == Gdk.KEY_Right:
                    dx = step
                elif keyval == Gdk.KEY_Up:
                    dy = -step
                elif keyval == Gdk.KEY_Down:
                    dy = step

                old_properties = copy.deepcopy(selected_obj.__dict__)

                if isinstance(selected_obj, EditableText):
                    selected_obj.x += dx
                    selected_obj.y += dy
                    if getattr(selected_obj, 'baseline', None) is not None:
                        selected_obj.baseline += dy
                    if selected_obj.bbox:
                        x1, y1, x2, y2 = selected_obj.bbox
                        selected_obj.bbox = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                elif isinstance(selected_obj, EditableStroke):
                    selected_obj.points = [(p[0] + dx, p[1] + dy) for p in selected_obj.points]
                    selected_obj.recalculate_bbox()
                    selected_obj.original_bbox = selected_obj.bbox
                elif isinstance(selected_obj, AcroFormField):
                    x1, y1, x2, y2 = selected_obj.rect
                    new_rect = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                    selected_obj.rect = new_rect
                    command = MoveResizeFormFieldCommand(self, selected_obj, (x1, y1, x2, y2), new_rect)
                    command.execute()
                    self.undo_manager.add_command(command)
                    self.document_modified = True
                    self._update_tab_dirty_state()
                    self._update_form_field_overlay_positions()
                    self._refresh_thumbnail(self.current_page_index)
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
                    return True
                elif isinstance(selected_obj, (EditableShape, EditableImage)):
                    x1, y1, x2, y2 = selected_obj.bbox
                    selected_obj.bbox = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                    selected_obj.x = selected_obj.bbox[0]
                    selected_obj.y = selected_obj.bbox[1]

                new_properties = copy.deepcopy(selected_obj.__dict__)
                selected_obj.__dict__.update(old_properties)

                command = EditObjectCommand(self, selected_obj, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._refresh_thumbnail(self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return True

        # Single-key tool selection shortcuts (when not editing text)
        if not ctrl and not (state & Gdk.ModifierType.ALT_MASK) and not is_input_focused:
            tool_shortcuts = {
                Gdk.KEY_v: "add_checkmark",
                Gdk.KEY_V: "add_checkmark",
                Gdk.KEY_x: "add_cross",
                Gdk.KEY_X: "add_cross",
                Gdk.KEY_p: "pen",
                Gdk.KEY_P: "pen",
                Gdk.KEY_h: "highlighter",
                Gdk.KEY_H: "highlighter",
                Gdk.KEY_s: "select",
                Gdk.KEY_S: "select",
                Gdk.KEY_t: "add_text",
                Gdk.KEY_T: "add_text",
                Gdk.KEY_i: "add_image",
                Gdk.KEY_I: "add_image",
                Gdk.KEY_m: "drag",
                Gdk.KEY_M: "drag",
                Gdk.KEY_c: "add_ellipse",
                Gdk.KEY_C: "add_ellipse",
                Gdk.KEY_r: "add_rectangle",
                Gdk.KEY_R: "add_rectangle",
                Gdk.KEY_f: "form_builder",
                Gdk.KEY_F: "form_builder",
            }
            if keyval in tool_shortcuts:
                self.on_tool_selected(None, tool_shortcuts[keyval])
                return True

        return False

    def on_tool_selected(self, button, tool_name):
        """Switch active editor tool mode (select, text, shapes, pen, highlighter)."""
        if self.inline_editor_widget is not None:
             print(_("dbg_applying_changes_before_tool"))
             self._apply_and_hide_editor(force_apply=True)

        if self.selected_text:
            self.selected_text = None

        if self.selected_image:
            self.selected_image = None

        if self.selected_shape:
            self.selected_shape = None

        if hasattr(self, 'selected_stroke') and self.selected_stroke:
            self.selected_stroke = None

        self.pdf_view.queue_draw()

        self.tool_mode = tool_name
        print(_("dbg_tool_changed", self.tool_mode))
        self.temp_calibration_line = None
        self._update_ui_state()
        if self.tool_mode in ("pen", "highlighter"):
            self._update_stroke_format_controls(None)
        elif self.tool_mode == "calibrate":
            self._update_calibration_controls()

    def get_scale_calibration(self, page_index: Optional[int] = None) -> Optional[ScaleCalibration]:
        """Return the active scale calibration for the specified page or whole document."""
        if not self._active_session:
            return None
        idx = page_index if page_index is not None else self.current_page_index
        page_calib = self._active_session.scale_calibrations.get(idx)
        if page_calib:
            return page_calib
        return self._active_session.scale_calibration

    def set_scale_calibration(self, calibration: Optional[ScaleCalibration],
                              page_index: Optional[int] = None, entire_document: bool = True):
        """Set or update scale calibration recording an undoable action in the history stack."""
        if not self._active_session:
            return
        old_calib = self.get_scale_calibration(page_index)
        cmd = CalibrateScaleCommand(self, old_calib, calibration, page_index=page_index, entire_document=entire_document)
        cmd.execute()
        self.undo_manager.add_command(cmd)

    def _apply_scale_calibration_state(self, calibration: Optional[ScaleCalibration],
                                       page_index: Optional[int] = None, entire_document: bool = True):
        """Apply scale calibration directly to the active session and synchronize UI components."""
        if not self._active_session:
            return
        idx = page_index if page_index is not None else self.current_page_index
        if entire_document:
            self._active_session.scale_calibration = calibration
            self._active_session.scale_calibrations.clear()
        else:
            if calibration is not None:
                self._active_session.scale_calibrations[idx] = calibration
            else:
                self._active_session.scale_calibrations.pop(idx, None)

        self.document_modified = True
        self._update_calibration_controls()
        if hasattr(self, 'status_label') and self.status_label:
            if calibration:
                self.status_label.set_text(_("scale_applied_success", calibration.unit, calibration.points_per_unit))
            else:
                self.status_label.set_text(_("scale_reset_success"))
        self.pdf_view.queue_draw()

    def _update_calibration_controls(self):
        """Update scale label, preset dropdown, and buttons in calibration toolbar."""
        if not hasattr(self, 'calibration_toolbar_box') or not self.calibration_toolbar_box:
            return
        calib = self.get_scale_calibration(self.current_page_index)
        if calib:
            summary = calib.format_scale_ratio()
            self.calibration_scale_label.set_text(summary)
            self.calibration_scale_label.remove_css_class("dim-label")
            self.calibration_scale_label.add_css_class("accent")
            self.calibrate_reset_btn.set_sensitive(True)
        else:
            self.calibration_scale_label.set_text(_("scale_uncalibrated"))
            self.calibration_scale_label.remove_css_class("accent")
            self.calibration_scale_label.add_css_class("dim-label")
            self.calibrate_reset_btn.set_sensitive(False)

    def on_calibration_preset_changed(self, dropdown, param):
        """Apply selected preset scale from dropdown."""
        sel_idx = dropdown.get_selected()
        if sel_idx == 0:
            return  # Custom / Reference Line item
        preset_keys = list(PRESET_SCALES.keys())
        if 1 <= sel_idx <= len(preset_keys):
            key = preset_keys[sel_idx - 1]
            try:
                new_calib = ScaleCalibration.from_preset(key)
                self.set_scale_calibration(new_calib, page_index=self.current_page_index, entire_document=True)
            except Exception as e:
                print(f"Error applying preset scale {key}: {e}")

    def on_calibration_reset_clicked(self, button=None):
        """Reset active scale calibration."""
        if hasattr(self, 'calibration_preset_dropdown') and self.calibration_preset_dropdown:
            self.calibration_preset_dropdown.set_selected(0)
        self.set_scale_calibration(None, page_index=self.current_page_index, entire_document=True)

    def on_calibrate_dialog_clicked(self, button=None):
        """Open calibration dialog using default or current reference dimensions."""
        calib = self.get_scale_calibration(self.current_page_index)
        pt_len = calib.points_len if (calib and calib.points_len > 0) else 100.0
        ref_line = calib.reference_line if calib else None
        self.show_scale_calibration_dialog(pt_len, reference_line=ref_line)

    def show_scale_calibration_dialog(self, measured_points: float, reference_line=None):
        """Display popover dialog allowing user to set known real-world distance and unit."""
        if not self.doc:
            return

        dialog = Gtk.Popover(autohide=True, has_arrow=True)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)

        title_lbl = Gtk.Label(label=_("dialog_calibrate_title"))
        title_lbl.add_css_class("title-4")
        title_lbl.set_halign(Gtk.Align.START)
        content_box.append(title_lbl)

        desc_lbl = Gtk.Label(label=_("dialog_calibrate_desc"))
        desc_lbl.add_css_class("dim-label")
        desc_lbl.set_halign(Gtk.Align.START)
        content_box.append(desc_lbl)

        # Measured points display
        meas_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        meas_lbl = Gtk.Label(label=_("label_reference_length"))
        meas_lbl.set_halign(Gtk.Align.START)
        meas_box.append(meas_lbl)

        mm_len = (measured_points * 25.4) / 72.0
        meas_val_lbl = Gtk.Label(label=f"{measured_points:.2f} pt ({mm_len:.1f} mm)")
        meas_val_lbl.add_css_class("heading")
        meas_box.append(meas_val_lbl)
        content_box.append(meas_box)

        # Input grid: Known Distance and Unit
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)

        dist_lbl = Gtk.Label(label=_("label_known_distance"))
        dist_lbl.set_halign(Gtk.Align.START)
        grid.attach(dist_lbl, 0, 0, 1, 1)

        # Initial distance and unit from existing calibration if any
        current_calib = self.get_scale_calibration(self.current_page_index)
        init_dist = current_calib.known_distance if current_calib else 5.0
        init_unit = current_calib.unit if current_calib else "m"

        dist_spin = Gtk.SpinButton.new_with_range(0.001, 1000000.0, 0.5)
        dist_spin.set_digits(2)
        dist_spin.set_value(init_dist)
        dist_spin.set_hexpand(True)
        grid.attach(dist_spin, 1, 0, 1, 1)

        unit_lbl = Gtk.Label(label=_("label_unit"))
        unit_lbl.set_halign(Gtk.Align.START)
        grid.attach(unit_lbl, 0, 1, 1, 1)

        unit_keys = ["m", "cm", "mm", "ft", "in", "yd"]
        unit_names = [
            _("unit_meter"), _("unit_centimeter"), _("unit_millimeter"),
            _("unit_foot"), _("unit_inch"), _("unit_yard")
        ]
        unit_dropdown = Gtk.DropDown.new_from_strings(unit_names)
        if init_unit in unit_keys:
            unit_dropdown.set_selected(unit_keys.index(init_unit))
        else:
            unit_dropdown.set_selected(0)
        grid.attach(unit_dropdown, 1, 1, 1, 1)

        content_box.append(grid)

        # Scope options: Entire Document vs Current Page
        scope_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        doc_radio = Gtk.CheckButton(label=_("opt_entire_document"))
        doc_radio.set_active(True)
        page_radio = Gtk.CheckButton(label=_("opt_current_page"))
        page_radio.set_group(doc_radio)
        scope_box.append(doc_radio)
        scope_box.append(page_radio)
        content_box.append(scope_box)

        # Live preview label
        preview_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prev_title = Gtk.Label(label=_("label_calculated_scale"))
        prev_title.set_halign(Gtk.Align.START)
        preview_box.append(prev_title)

        prev_val_lbl = Gtk.Label(label="")
        prev_val_lbl.add_css_class("accent")
        preview_box.append(prev_val_lbl)
        content_box.append(preview_box)

        def update_preview(*a):
            dist = max(dist_spin.get_value(), 1e-9)
            u_idx = unit_dropdown.get_selected()
            u_key = unit_keys[u_idx] if 0 <= u_idx < len(unit_keys) else "m"
            ppu = measured_points / dist
            prev_val_lbl.set_text(f"1 {u_key} = {ppu:.2f} pt")

        dist_spin.connect("value-changed", update_preview)
        unit_dropdown.connect("notify::selected", update_preview)
        update_preview()

        # Action Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)

        def on_cancel(b):
            dialog.popdown()
            self.temp_calibration_line = None
            self.pdf_view.queue_draw()

        def on_apply(b):
            dist = max(dist_spin.get_value(), 1e-9)
            u_idx = unit_dropdown.get_selected()
            u_key = unit_keys[u_idx] if 0 <= u_idx < len(unit_keys) else "m"
            entire_doc = doc_radio.get_active()

            rl = reference_line
            if rl:
                new_calib = ScaleCalibration.from_reference_line(
                    rl[0], rl[1], rl[2], rl[3],
                    known_distance=dist, unit=u_key,
                    page_index=(None if entire_doc else self.current_page_index)
                )
            else:
                ppu = measured_points / dist
                new_calib = ScaleCalibration(
                    points_per_unit=ppu,
                    unit=u_key,
                    known_distance=dist,
                    points_len=measured_points,
                    reference_line=reference_line,
                    page_index=(None if entire_doc else self.current_page_index)
                )

            dialog.popdown()
            self.temp_calibration_line = None
            self.set_scale_calibration(new_calib, page_index=self.current_page_index, entire_document=entire_doc)
            if hasattr(self, 'calibration_preset_dropdown') and self.calibration_preset_dropdown:
                self.calibration_preset_dropdown.set_selected(0)

        cancel_btn = Gtk.Button(label=_("btn_cancel"))
        cancel_btn.connect("clicked", on_cancel)
        btn_box.append(cancel_btn)

        apply_btn = Gtk.Button(label=_("btn_apply"))
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", on_apply)
        btn_box.append(apply_btn)

        content_box.append(btn_box)
        dialog.set_child(content_box)

        anchor = getattr(self, 'calibrate_dialog_btn', self.pdf_view)
        dialog.set_parent(anchor)
        dialog.popup()

    def on_drag_begin(self, gesture, start_x, start_y):
        """Initiate canvas drag gesture for selection, movement, resizing, or freehand drawing."""
        if not self.doc:
            return

        page_w, page_h = self.current_pdf_page_width, self.current_pdf_page_height
        page_offset_x = max(0, (self.pdf_view.get_allocated_width() - page_w) / 2)
        page_offset_y = max(0, (self.pdf_view.get_allocated_height() - page_h) / 2)

        page_x = (start_x - page_offset_x) / self.zoom_level
        page_y = (start_y - page_offset_y) / self.zoom_level

        if self.view_mode:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.view_drag_active = True
            self.view_sel_start = (page_x, page_y)
            self.view_sel_rect = (page_x, page_y, page_x, page_y)
            self.view_selected_text = ""
            self.pdf_view.queue_draw()
            return

        # Allow direct resize handle interaction on already selected objects regardless of active tool
        selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                        getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None))
        if selected_obj:
            resize_handle = self._find_resize_handle_at_pos(start_x, start_y, selected_obj)
            if resize_handle:
                self.resize_handle = resize_handle
                self.resize_start_bbox = selected_obj.bbox
                self.dragged_object = selected_obj
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self.drag_start_pos = (start_x, start_y)
                self.drag_begin_state = copy.deepcopy(selected_obj.__dict__)

                if resize_handle == "rotate" and not isinstance(selected_obj, AcroFormField) and not hasattr(selected_obj, 'field_name'):
                    x1, y1, x2, y2 = selected_obj.bbox
                    unrot_cx = (x1 + x2) / 2.0
                    unrot_cy = (y1 + y2) / 2.0
                    vis_cx, vis_cy = self._unrotated_to_visual_page_coords(unrot_cx, unrot_cy)
                    cx = page_offset_x + vis_cx * self.zoom_level
                    cy = page_offset_y + vis_cy * self.zoom_level
                    self.rotate_center = (cx, cy)
                    self.rotate_start_angle = getattr(selected_obj, 'rotation', 0.0) % 360.0
                    start_dx = start_x - cx
                    start_dy = start_y - cy
                    self.rotate_pointer_start_angle = math.degrees(math.atan2(start_dy, start_dx))
                return

        unrot_px, unrot_py = self._visual_to_unrotated_page_coords(page_x, page_y)

        if self.tool_mode in ("pen", "highlighter"):
            self.selected_stroke = None
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            color = self.pen_color if self.tool_mode == "pen" else self.highlighter_color
            width = self.pen_width if self.tool_mode == "pen" else self.highlighter_width
            opacity = 1.0 if self.tool_mode == "pen" else self.highlighter_opacity
            self.temp_stroke = EditableStroke(
                points=[(unrot_px, unrot_py)],
                stroke_color=color,
                stroke_width=width,
                opacity=opacity,
                tool_type=self.tool_mode,
                page_number=self.current_page_index,
                is_new=True
            )
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "add_ellipse":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_ELLIPSE,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=self.next_shape_fill,
                stroke_color=self.next_shape_stroke,
                stroke_width=self.next_shape_stroke_width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=self.next_shape_transparent
            )
            return
        elif self.tool_mode == "add_rectangle":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_RECTANGLE,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=self.next_shape_fill,
                stroke_color=self.next_shape_stroke,
                stroke_width=self.next_shape_stroke_width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=self.next_shape_transparent
            )
            return
        elif self.tool_mode == "add_checkmark":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            color = self.next_shape_stroke if hasattr(self, 'next_shape_stroke') else (0.1, 0.65, 0.25)
            width = max(getattr(self, 'next_shape_stroke_width', 2.5), 2.0)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_CHECKMARK,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=(1, 1, 1),
                stroke_color=color,
                stroke_width=width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=True
            )
            return
        elif self.tool_mode == "add_cross":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            color = self.next_shape_stroke if hasattr(self, 'next_shape_stroke') else (0.85, 0.15, 0.15)
            width = max(getattr(self, 'next_shape_stroke_width', 2.5), 2.0)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_CROSS,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=(1, 1, 1),
                stroke_color=color,
                stroke_width=width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=True
            )
            return
        elif self.tool_mode == "add_image":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_image_bbox = (unrot_px, unrot_py, unrot_px, unrot_py)
            return
        elif self.tool_mode == "form_builder":
            self._close_active_form_field_editor()
            clicked_form_field = self._find_form_field_at_pos(unrot_px, unrot_py)
            if clicked_form_field:
                self.selected_form_field = clicked_form_field
                self.selected_text = None
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self._update_form_builder_controls_for_selected()
                
                self.dragged_object = clicked_form_field
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self.drag_start_pos = (start_x, start_y)
                self.drag_begin_state = copy.deepcopy(clicked_form_field.__dict__)
                if not hasattr(clicked_form_field, 'original_bbox') or not clicked_form_field.original_bbox:
                    clicked_form_field.original_bbox = clicked_form_field.bbox
                x1, y1, _, _ = clicked_form_field.bbox
                self.drag_object_start_pos = (x1, y1)
                self.pdf_view.queue_draw()
                return

            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_form_field_rect = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.selected_form_field = None
            self._update_form_builder_controls_for_selected()
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "calibrate":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_calibration_line = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.pdf_view.queue_draw()
            return

        if self.tool_mode == "drag":
            self._close_active_form_field_editor()
            self.dragged_object = (self._find_image_at_pos(page_x, page_y) or 
                                   self._find_text_at_pos(page_x, page_y) or 
                                   self._find_shape_at_pos(page_x, page_y) or 
                                   self._find_stroke_at_pos(page_x, page_y) or
                                   self._find_form_field_at_pos(page_x, page_y))
            if not self.dragged_object:
                gesture.set_state(Gtk.EventSequenceState.DENIED)
                return
        elif self.tool_mode == "select":
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        else:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return

        if self.dragged_object:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.drag_start_pos = (start_x, start_y)
            self.drag_begin_state = copy.deepcopy(self.dragged_object.__dict__)

        if self.dragged_object:
            if not hasattr(self.dragged_object, 'original_bbox') or not self.dragged_object.original_bbox:
                self.dragged_object.original_bbox = self.dragged_object.bbox
            if not hasattr(self.dragged_object, 'original_baseline') or self.dragged_object.original_baseline is None:
                self.dragged_object.original_baseline = getattr(self.dragged_object, 'baseline', None)

            x1, y1, _, _ = self.dragged_object.bbox
            self.drag_object_start_pos = (x1, y1)
        else:
            gesture.set_state(Gtk.EventSequenceState.DENIED)

    def on_drag_update(self, gesture, offset_x, offset_y):
        """Update canvas interaction during drag (move/resize objects, text select, or draw strokes)."""
        if self.view_mode:
            if self.view_sel_start and self.view_drag_active:
                sx, sy = self.view_sel_start
                dx = offset_x / self.zoom_level
                dy = offset_y / self.zoom_level
                cx = sx + dx
                cy = sy + dy
                self.view_sel_rect = (min(sx, cx), min(sy, cy), max(sx, cx), max(sy, cy))
                self.pdf_view.queue_draw()
            return

        if self.inline_editor_widget is not None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
            
        if self.dragging_to_create:
            delta_x, delta_y = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)
            if getattr(self, 'temp_stroke', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                self.temp_stroke.add_point(current_x, current_y)
                self.pdf_view.queue_draw()
                return
            if self.temp_image_bbox is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                
                if x2 - x1 < 20:
                    x2 = x1 + 20
                if y2 - y1 < 20:
                    y2 = y1 + 20
                    
                self.temp_image_bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if self.temp_shape:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                
                if x2 - x1 < 10:
                    x2 = x1 + 10
                if y2 - y1 < 10:
                    y2 = y1 + 10
                    
                self.temp_shape.bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_form_field_rect', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                if getattr(self, 'form_builder_field_type', 'text') == 'checkbox':
                    side = max(abs(delta_x), abs(delta_y))
                    if side < 16.0:
                        side = 20.0
                    current_x = start_x + (side if delta_x >= 0 else -side)
                    current_y = start_y + (side if delta_y >= 0 else -side)
                
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                
                self.temp_form_field_rect = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_calibration_line', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y

                shift_pressed = False
                try:
                    state = gesture.get_current_event_state()
                    shift_pressed = bool(state & Gdk.ModifierType.SHIFT_MASK)
                except Exception:
                    pass

                if shift_pressed and (abs(delta_x) > 2 or abs(delta_y) > 2):
                    angle = math.atan2(delta_y, delta_x)
                    snap_angle = round(angle / (math.pi / 4)) * (math.pi / 4)
                    dist = math.hypot(delta_x, delta_y)
                    current_x = start_x + dist * math.cos(snap_angle)
                    current_y = start_y + dist * math.sin(snap_angle)

                self.temp_calibration_line = (start_x, start_y, current_x, current_y)
                self.pdf_view.queue_draw()
                return
            return
        
        if not self.dragged_object:
            return

        if self.resize_handle:
            if self.resize_handle == "rotate":
                self._handle_rotate_update(gesture, offset_x, offset_y)
            else:
                self._handle_resize_update(offset_x, offset_y)
            return
        if self.tool_mode not in ("drag", "form_builder"):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
            
        delta_x, delta_y = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)

        start_obj_x, start_obj_y = self.drag_object_start_pos
        new_x = start_obj_x + delta_x
        new_y = start_obj_y + delta_y

        orig_bbox = getattr(self.dragged_object, 'original_bbox', self.dragged_object.bbox)
        w = orig_bbox[2] - orig_bbox[0]
        h = orig_bbox[3] - orig_bbox[1]
        
        if isinstance(self.dragged_object, AcroFormField):
            self.dragged_object.rect = (new_x, new_y, new_x + w, new_y + h)
            self._update_form_field_overlay_positions()
            self.selected_form_field = self.dragged_object
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.pdf_view.queue_draw()
            return
        
        self.dragged_object.x = new_x
        self.dragged_object.y = new_y
        self.dragged_object.bbox = (new_x, new_y, new_x + w, new_y + h)
        
        if isinstance(self.dragged_object, EditableText):
            self.dragged_object.baseline = new_y + getattr(self.dragged_object, 'baseline_offset', self.dragged_object.font_size * 0.9)

            self.selected_text = self.dragged_object
            self.selected_image = None
            self.selected_shape = None
        
        elif isinstance(self.dragged_object, EditableImage):
            self.selected_image = self.dragged_object
            self.selected_text = None
            self.selected_shape = None
            
        elif isinstance(self.dragged_object, EditableShape):
            self.selected_shape = self.dragged_object
            self.selected_image = None
            self.selected_text = None
            self.selected_stroke = None

        elif isinstance(self.dragged_object, EditableStroke):
            start_points = self.drag_begin_state.get('points', [])
            self.dragged_object.points = [(p[0] + delta_x, p[1] + delta_y) for p in start_points]
            self.dragged_object.recalculate_bbox()
            self.selected_stroke = self.dragged_object
            self.selected_shape = None
            self.selected_image = None
            self.selected_text = None

        self.pdf_view.queue_draw()

    def _handle_rotate_update(self, gesture, offset_x, offset_y):
        """Handle dynamic rotation update while dragging the stalk rotation handle."""
        if not self.dragged_object or not hasattr(self, 'rotate_center') or not hasattr(self, 'rotate_pointer_start_angle'):
            return

        current_x = self.drag_start_pos[0] + offset_x
        current_y = self.drag_start_pos[1] + offset_y
        cx, cy = self.rotate_center

        cur_dx = current_x - cx
        cur_dy = current_y - cy

        if math.hypot(cur_dx, cur_dy) < 2.0:
            return

        cur_pointer_angle = math.degrees(math.atan2(cur_dy, cur_dx))
        angle_delta = cur_pointer_angle - self.rotate_pointer_start_angle
        new_rot = (self.rotate_start_angle + angle_delta) % 360.0

        # Check Shift key modifier for 15-degree increment snapping
        shift_pressed = False
        try:
            state = gesture.get_current_event_state()
            shift_pressed = bool(state & Gdk.ModifierType.SHIFT_MASK)
        except Exception:
            pass

        if shift_pressed:
            new_rot = round(new_rot / 15.0) * 15.0 % 360.0
        else:
            new_rot = round(new_rot, 1) % 360.0

        if hasattr(self.dragged_object, 'set_rotation'):
            self.dragged_object.set_rotation(new_rot)
        else:
            self.dragged_object.rotation = new_rot

        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("status_object_rotation", f"{new_rot:.1f}°"))

        if hasattr(self, '_update_rotation_controls'):
            self._update_rotation_controls(self.dragged_object)

        self.pdf_view.queue_draw()

    def _handle_resize_update(self, offset_x, offset_y):
        """Handle resize update."""
        if not self.resize_handle or not self.resize_start_bbox or not self.dragged_object:
            return

        x1, y1, x2, y2 = self.resize_start_bbox
        delta_x, delta_y = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)

        new_x1, new_y1, new_x2, new_y2 = x1, y1, x2, y2

        if "w" in self.resize_handle:  # Left handles
            new_x1 = x1 + delta_x
        if "e" in self.resize_handle:  # Right handles
            new_x2 = x2 + delta_x
        if "n" in self.resize_handle:  # Top handles
            new_y1 = y1 + delta_y
        if "s" in self.resize_handle:  # Bottom handles
            new_y2 = y2 + delta_y

        min_size = 10
        if new_x2 - new_x1 < min_size:
            if "e" in self.resize_handle:
                new_x2 = new_x1 + min_size
            else:
                new_x1 = new_x2 - min_size
        if new_y2 - new_y1 < min_size:
            if "s" in self.resize_handle:
                new_y2 = new_y1 + min_size
            else:
                new_y1 = new_y2 - min_size

        if isinstance(self.dragged_object, EditableStroke):
            start_points = self.drag_begin_state.get('points', self.dragged_object.points)
            self.dragged_object.scale_to_bbox((new_x1, new_y1, new_x2, new_y2), self.resize_start_bbox, start_points)
        elif isinstance(self.dragged_object, AcroFormField):
            if getattr(self.dragged_object, 'field_type', None) in ("checkbox", "radio"):
                w = new_x2 - new_x1
                h = new_y2 - new_y1
                side = max(w, h, 16.0)
                if "w" in self.resize_handle:
                    new_x1 = new_x2 - side
                else:
                    new_x2 = new_x1 + side
                if "n" in self.resize_handle:
                    new_y1 = new_y2 - side
                else:
                    new_y2 = new_y1 + side
            self.dragged_object.rect = (new_x1, new_y1, new_x2, new_y2)
            self._update_form_field_overlay_positions()
        else:
            self.dragged_object.bbox = (new_x1, new_y1, new_x2, new_y2)
            self.dragged_object.x = new_x1
            self.dragged_object.y = new_y1

        self.pdf_view.queue_draw()

    def on_drag_end(self, gesture, offset_x, offset_y):
        """Finalize canvas drag interaction, committing created or modified objects to undo history."""
        if self.view_mode:
            self.view_drag_active = False
            if self.view_sel_rect:
                x1, y1, x2, y2 = self.view_sel_rect
                if (x2 - x1) > 2 and (y2 - y1) > 2:
                    self.view_selected_text = pdf_handler.get_text_in_rect(
                        self.doc, self.current_page_index, (x1, y1, x2, y2))
                else:
                    self.view_sel_rect = None
                    self.view_selected_text = ""
            self._update_ui_state()
            self.pdf_view.queue_draw()
            return

        if self.dragging_to_create:
            self.dragging_to_create = False
            if getattr(self, 'temp_stroke', None) is not None:
                stroke_to_add = self.temp_stroke
                self.temp_stroke = None
                if stroke_to_add.points:
                    stroke_to_add.recalculate_bbox()
                    stroke_to_add.original_bbox = stroke_to_add.bbox
                    self.selected_stroke = stroke_to_add
                    self.selected_text = None
                    self.selected_image = None
                    self.selected_shape = None

                    command = AddObjectCommand(self, stroke_to_add)
                    command.execute()
                    self.undo_manager.add_command(command)
                    self.document_modified = True
                    self._refresh_thumbnail(self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return

            if self.temp_shape:
                x1, y1, x2, y2 = self.temp_shape.bbox
                if (x2 - x1) < 10 or (y2 - y1) < 10:
                    if self.temp_shape.shape_type in (EditableShape.SHAPE_CHECKMARK, EditableShape.SHAPE_CROSS):
                        cx, cy = self.drag_start_page_pos
                        size = 24.0
                        self.temp_shape.bbox = (cx - size / 2.0, cy - size / 2.0, cx + size / 2.0, cy + size / 2.0)
                        self.temp_shape.x = self.temp_shape.bbox[0]
                        self.temp_shape.y = self.temp_shape.bbox[1]
                    else:
                        self.temp_shape = None
                        self.pdf_view.queue_draw()
                        return
                
                self.temp_shape.original_bbox = self.temp_shape.bbox
                self.selected_shape = self.temp_shape
                self.selected_text = None
                self.selected_image = None
                self.selected_stroke = None
                
                command = AddObjectCommand(self, self.temp_shape)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                
                self.temp_shape.is_baked = True
                self.temp_shape = None
                self._refresh_thumbnail(self.current_page_index)
                
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif self.temp_image_bbox:
                x1, y1, x2, y2 = self.temp_image_bbox
                if (x2 - x1) < 20 or (y2 - y1) < 20:
                    self.temp_image_bbox = None
                    self.pdf_view.queue_draw()
                    return
                
                filter_img = Gtk.FileFilter(name=_("image_filter_label"))
                for mime in ["image/png", "image/jpeg", "image/gif", "image/bmp"]:
                    filter_img.add_mime_type(mime)

                def on_image_selected(file):
                    if file:
                        try:
                            with open(file.get_path(), 'rb') as f:
                                image_bytes = f.read()

                            image_obj = EditableImage(
                                bbox=self.temp_image_bbox,
                                page_number=self.current_page_index,
                                xref=None,
                                image_bytes=image_bytes,
                                is_new=True
                            )

                            self.selected_image = image_obj
                            self.selected_text = None
                            self.selected_shape = None
                            command = AddObjectCommand(self, image_obj)
                            command.execute()
                            self.undo_manager.add_command(command)
                            self.document_modified = True
                            self.pdf_view.queue_draw()
                            self._update_ui_state()
                        except Exception as e:
                            show_error_dialog(self, _("err_adding_image_dialog", e), _("err_title"))

                    self.temp_image_bbox = None
                    self.pdf_view.queue_draw()

                show_open_file_dialog(
                    self,
                    _("image_select_title"),
                    filters=[filter_img],
                    callback=on_image_selected
                )
            elif getattr(self, 'temp_form_field_rect', None) is not None:
                x1, y1, x2, y2 = self.temp_form_field_rect
                self.temp_form_field_rect = None
                w = x2 - x1
                h = y2 - y1
                if w < 10 or h < 10:
                    if getattr(self, 'form_builder_field_type', 'text') == 'checkbox':
                        w, h = 20.0, 20.0
                    else:
                        w, h = 140.0, 26.0
                    x2 = x1 + w
                    y2 = y1 + h
                elif getattr(self, 'form_builder_field_type', 'text') == 'checkbox':
                    side = max(w, h)
                    w, h = side, side
                    x2 = x1 + w
                    y2 = y1 + h

                rect = (x1, y1, x2, y2)
                self._create_new_form_field(rect)
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif getattr(self, 'temp_calibration_line', None) is not None:
                line = self.temp_calibration_line
                sx, sy, ex, ey = line
                measured_len = math.hypot(ex - sx, ey - sy)
                if measured_len >= 5.0:
                    self.show_scale_calibration_dialog(measured_len, reference_line=line)
                else:
                    self.temp_calibration_line = None
                self.pdf_view.queue_draw()
                self._update_ui_state()
            return
        
        if not self.dragged_object or not hasattr(self, 'drag_begin_state'):
            if self.dragged_object:
                self.dragged_object = None
            self.resize_handle = None
            self.resize_start_bbox = None
            if hasattr(self, 'rotate_center'):
                del self.rotate_center
            if hasattr(self, 'rotate_start_angle'):
                del self.rotate_start_angle
            if hasattr(self, 'rotate_pointer_start_angle'):
                del self.rotate_pointer_start_angle
            self.pdf_view.queue_draw()
            return

        self.commit_pending_format_change()

        old_properties = self.drag_begin_state
        
        new_properties = copy.deepcopy(self.dragged_object.__dict__)

        dragged_obj_ref = self.dragged_object
        self.dragged_object = None
        self.resize_handle = None
        self.resize_start_bbox = None
        del self.drag_begin_state
        if hasattr(self, 'rotate_center'):
            del self.rotate_center
        if hasattr(self, 'rotate_start_angle'):
            del self.rotate_start_angle
        if hasattr(self, 'rotate_pointer_start_angle'):
            del self.rotate_pointer_start_angle

        if isinstance(dragged_obj_ref, AcroFormField):
            old_rect = old_properties.get('rect', getattr(dragged_obj_ref, 'rect', None))
            new_rect = getattr(dragged_obj_ref, 'rect', None)
            if old_rect and new_rect and old_rect != new_rect:
                command = MoveResizeFormFieldCommand(self, dragged_obj_ref, old_rect, new_rect)
                command.execute()
                self.undo_manager.add_command(command)
            self.selected_form_field = dragged_obj_ref
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self._update_form_builder_controls_for_selected()
            self._update_ui_state()
            self.pdf_view.queue_draw()
            return
        
        rot_changed = (old_properties.get('rotation', 0.0) != new_properties.get('rotation', 0.0))
        if abs(offset_x) < 1 and abs(offset_y) < 1 and not rot_changed:
            self.pdf_view.queue_draw()
            return

        if rot_changed:
            old_rot = old_properties.get('rotation', 0.0)
            new_rot = new_properties.get('rotation', 0.0)
            command = RotateObjectCommand(self, dragged_obj_ref, old_rot, new_rot)
            command.execute()
            self.undo_manager.add_command(command)
        else:
            print(_("dbg_creating_drag_command"))
            command = EditObjectCommand(self, dragged_obj_ref, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)

        if isinstance(dragged_obj_ref, EditableText):
            self.selected_text = dragged_obj_ref
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.pending_format_change_obj = self.selected_text
            self.before_format_change_state = copy.deepcopy(self.selected_text.__dict__)
            self._update_text_format_controls(self.selected_text)
        elif isinstance(dragged_obj_ref, EditableImage):
            self.selected_image = dragged_obj_ref
            self.selected_text = None
            self.selected_shape = None
            self.selected_stroke = None
        elif isinstance(dragged_obj_ref, EditableShape):
            self.selected_shape = dragged_obj_ref
            self.selected_text = None
            self.selected_image = None
            self.selected_stroke = None
        elif isinstance(dragged_obj_ref, EditableStroke):
            self.selected_stroke = dragged_obj_ref
            self.selected_shape = None
            self.selected_text = None
            self.selected_image = None

        self._update_ui_state()
        self.pdf_view.queue_draw()

    def insert_symbol_or_emoji(self, symbol, is_emoji=False):
        """Insert symbol into active text block or create full-color emoji stamp on document."""
        if getattr(self, 'inline_editor_widget', None) is not None and getattr(self, 'inline_text_view', None) is not None:
            buf = self.inline_text_view.get_buffer()
            buf.insert_at_cursor(symbol)
            self.inline_text_view.grab_focus()
            return

        if is_emoji and self.doc and self.current_pdf_page_width > 0:
            try:
                png_bytes = render_emoji_to_png_bytes(symbol, size=96)
                page_w_unzoomed = self.current_pdf_page_width / self.zoom_level
                page_h_unzoomed = self.current_pdf_page_height / self.zoom_level
                stamp_size = 32.0
                stamp_x = max(20.0, (page_w_unzoomed - stamp_size) / 2.0)
                stamp_y = max(20.0, (page_h_unzoomed - stamp_size) / 2.0)

                emoji_obj = EditableImage(
                    bbox=(stamp_x, stamp_y, stamp_x + stamp_size, stamp_y + stamp_size),
                    page_number=self.current_page_index,
                    xref=None,
                    image_bytes=png_bytes,
                    is_new=True
                )
                self.selected_image = emoji_obj
                self.selected_text = None
                self.selected_shape = None
                if hasattr(self, 'selected_stroke'):
                    self.selected_stroke = None

                command = AddObjectCommand(self, emoji_obj)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._refresh_thumbnail(self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                self.status_label.set_text(f"Added emoji stamp: {symbol}")
                return
            except Exception as e:
                print(f"Error creating emoji stamp: {e}")

        display = Gdk.Display.get_default()
        if display:
            clipboard = display.get_clipboard()
            clipboard.set(symbol)

        self.status_label.set_text(_("symbol_copied", symbol))

    def _on_quick_guide_activated(self, action, param):
        """Display the interactive quick user guide dialog."""
        dialog = QuickGuideDialog(self)
        dialog.present()

    def _update_undo_redo_buttons(self, *args):
        """Sync undo/redo toolbar button sensitivity with UndoManager stacks."""
        self.undo_button.set_sensitive(bool(self.undo_manager.undo_stack))
        self.redo_button.set_sensitive(bool(self.undo_manager.redo_stack))

    def _refresh_thumbnail(self, page_index):
        """Regenerate and replace the thumbnail pixbuf for a modified page."""
        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            return
        try:
            thumb = pdf_handler.generate_thumbnail(self.doc, page_index, target_width=150)
            if thumb:
                n = self.pages_model.get_n_items()
                for i in range(n):
                    item = self.pages_model.get_item(i)
                    if item and item.index == page_index:
                        from .models import PdfPage
                        new_item = PdfPage(page_index, thumb)
                        self.pages_model.splice(i, 1, [new_item])
                        GLib.idle_add(self._sync_thumbnail_selection)
                        break
        except Exception as e:
            print(f"Warning: Could not refresh thumbnail for page {page_index + 1}: {e}")
    
    def commit_pending_format_change(self):
        """Record pending text/shape style modifications into undo history."""
        if hasattr(self, '_commit_pending_form_field_edit'):
            self._commit_pending_form_field_edit()
        if self.pending_format_change_obj and self.before_format_change_state:
            current_state = copy.deepcopy(self.pending_format_change_obj.__dict__)
            
            if self.before_format_change_state != current_state:
                print(_("dbg_format_change_saved"))
                command = EditObjectCommand(self, self.pending_format_change_obj, self.before_format_change_state, current_state)
                command.execute()
                self.undo_manager.add_command(command)

        self.pending_format_change_obj = None
        self.before_format_change_state = None

    def on_new_clicked(self, widget=None):
        """Prompt user for dimensions and initialize a new empty PDF document in a tab."""
        def on_create(width_pt, height_pt, num_pages):
            doc, error_msg = pdf_handler.create_new_pdf(width=width_pt, height=height_pt, num_pages=num_pages)

            if error_msg:
                show_error_dialog(self, error_msg)
                return

            if doc:
                if self._active_session is not None and self._active_session.doc is not None:
                    sess = self.create_session()
                    self.add_session(sess, switch_to=True)
                else:
                    sess = self._active_session or self.create_session()
                    if sess not in self.sessions:
                        self.add_session(sess, switch_to=True)

                sess.doc = doc
                sess.pdf_path = None
                sess.original_file_path = None
                sess.current_page_index = 0
                sess.is_modified = True

                self.set_active_session(sess)
                self.set_title(f"{constants.APP_NAME} - {sess.display_title}")
                self._update_tab_title(sess)
                if hasattr(self, 'stack') and self.stack:
                    self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_visible(True)

                self._load_thumbnails(sess)
                self._load_page(0)
                self.status_label.set_text(_("status_new_doc_created"))
                self._update_ui_state()

        show_new_document_dialog(self, on_create)

    def do_close_request(self):
        """Prompt to save unsaved changes in all open tabs before closing the window."""
        if getattr(self, "_merge_dialog", None) is not None:
            try:
                self._merge_dialog.cleanup()
                self._merge_dialog.close()
            except Exception:
                pass
            self._merge_dialog = None

        modified_sessions = [s for s in self.sessions if s and s.is_modified and s.doc is not None]
        for s in modified_sessions:
            if self.check_unsaved_changes(s):
                return True
        self._is_closing = True
        for s in list(self.sessions):
            self.remove_session(s)
        return False

    def on_stroke_width_scroll(self, controller, dx, dy):
        """Adjust stroke width of selected shape using mouse wheel scroll."""
        if not self.selected_shape:
            return False
        
        dy_abs = abs(dy)
        increment = 0.5 if dy > 0 else -0.5
        
        new_width = max(0.5, self.selected_shape.stroke_width + increment)
        self.selected_shape.stroke_width = round(new_width, 1)
        
        self.pdf_view.queue_draw()
        return True

    def _toggle_view_edit_mode(self, button=None):
        """Toggle between read-only text-selection mode and interactive object edit mode."""
        if hasattr(self, 'stack') and self.stack and self.stack.get_visible_child_name() == "welcome":
            if any(s.doc is not None for s in self.sessions):
                self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
                if self._active_session and self._active_session.doc is not None:
                    self.set_title(f"{constants.APP_NAME} - {self._active_session.display_title}")
        self.view_mode = not self.view_mode
        self._close_active_form_field_editor()
        if self.view_mode:
            self._apply_and_hide_editor()
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_form_field = None
            self.tool_mode = "select"
        else:
            self.view_sel_start = None
            self.view_sel_rect = None
            self.view_selected_text = ""
            self.selected_form_field = None
        self._update_ui_state()
        self.pdf_view.queue_draw()

    def on_highlight_clicked(self, button):
        """Add a highlight annotation over selected text or canvas selection rectangle."""
        rgba = self.highlight_color_button.get_rgba()
        color = (rgba.red, rgba.green, rgba.blue)
        
        target_rect = None
        is_visual = False
        rot = 0.0
        if self.view_mode and self.view_sel_rect:
            target_rect = self.view_sel_rect
            is_visual = True
        elif not self.view_mode and self.selected_text and self.selected_text.bbox:
            if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char'):
                text = self.selected_text.text
                r1 = self.selected_word_start_char / max(len(text), 1)
                r2 = self.selected_word_end_char / max(len(text), 1)
                x1, y1, x2, y2 = self.selected_text.bbox
                target_rect = (x1 + (x2 - x1) * r1, y1, x1 + (x2 - x1) * r2, y2)
            else:
                target_rect = self.selected_text.bbox
            is_visual = False
            rot = getattr(self.selected_text, 'rotation', 0.0)
            
        if not target_rect:
            return
            
        x1, y1, x2, y2 = target_rect
        success, err = pdf_handler.add_highlight_annotation(
            self.doc, self.current_page_index, (x1, y1, x2, y2), color=color, is_visual=is_visual, rotation=rot
        )
        if success:
            pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
            self.document_modified = True
            self.view_sel_start = None
            self.view_sel_rect = None
            self.view_selected_text = ""
            self._refresh_thumbnail(self.current_page_index)
            self._update_ui_state()
            self.pdf_view.queue_draw()
        else:
            from .ui_components import show_error_dialog
            show_error_dialog(self, _("highlight_failed", err))

    def on_remove_highlight_clicked(self, button):
        """Remove highlight annotations overlapping current selection."""
        target_rect = None
        is_visual = False
        if self.view_mode and self.view_sel_rect:
            target_rect = self.view_sel_rect
            is_visual = True
        elif not self.view_mode and self.selected_text and self.selected_text.bbox:
            if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char'):
                text = self.selected_text.text
                r1 = self.selected_word_start_char / max(len(text), 1)
                r2 = self.selected_word_end_char / max(len(text), 1)
                x1, y1, x2, y2 = self.selected_text.bbox
                target_rect = (x1 + (x2 - x1) * r1, y1, x1 + (x2 - x1) * r2, y2)
            else:
                target_rect = self.selected_text.bbox
            is_visual = False
            
        if not target_rect:
            return
            
        self._remove_highlight_at_region(target_rect, is_visual=is_visual)

    def _extract_word_at_position(self, text, click_pos_in_text):
        """Extract contiguous non-whitespace word and its character indices at cursor."""
        if not text or click_pos_in_text < 0 or click_pos_in_text > len(text):
            return None, 0, 0
        
        start = click_pos_in_text
        end = click_pos_in_text
        
        while start > 0 and text[start - 1] not in ' \t\n':
            start -= 1
        
        while end < len(text) and text[end] not in ' \t\n':
            end += 1
        
        return text[start:end], start, end

    def _on_middle_click(self, gesture, n_press, x, y):
        """Handle middle-click gesture to quickly select words or jump to links."""
        if not self.doc:
            return
        
        drawing_area_width = self.pdf_view.get_allocated_width()
        drawing_area_height = self.pdf_view.get_allocated_height()
        page_offset_x = max(0, (drawing_area_width - self.current_pdf_page_width) / 2)
        page_offset_y = max(0, (drawing_area_height - self.current_pdf_page_height) / 2)
        click_x_zoomed = x - page_offset_x
        click_y_zoomed = y - page_offset_y
        page_x = click_x_zoomed / self.zoom_level
        page_y = click_y_zoomed / self.zoom_level
        
        if self.view_mode:
            clicked_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x, page_y))
            if clicked_word:
                self.selected_word = clicked_word['text']
                self.view_sel_rect = clicked_word['bbox']
                self.word_selection_mode = True
                self.pdf_view.queue_draw()
                self._update_ui_state()
        else:
            clicked_text = self._find_text_at_pos(page_x, page_y)
            if clicked_text:
                self.selected_text = clicked_text
                pdf_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x, page_y))
                if pdf_word:
                    self.selected_word = pdf_word['text']
                    idx = clicked_text.text.find(self.selected_word)
                    if idx != -1:
                        self.selected_word_start_char = idx
                        self.selected_word_end_char = idx + len(self.selected_word)
                        self.word_selection_mode = True
                        self.pending_format_change_obj = clicked_text
                        self.before_format_change_state = copy.deepcopy(clicked_text.__dict__)
                        self.pdf_view.queue_draw()
                        self._update_ui_state()
                else:
                    unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x, page_y)
                    rot = getattr(clicked_text, 'rotation', 0.0) % 360.0
                    x1, y1, x2, y2 = clicked_text.bbox
                    px, py = unrot_x, unrot_y
                    if rot != 0.0:
                        cx = (x1 + x2) / 2.0
                        cy = (y1 + y2) / 2.0
                        px, py = pdf_handler.rotate_point(unrot_x, unrot_y, cx, cy, -rot)
                    relative_x = (px - x1) / (x2 - x1) if (x2 - x1) > 0 else 0
                    approx_char_pos = int(relative_x * len(clicked_text.text))
                    approx_char_pos = max(0, min(approx_char_pos, len(clicked_text.text)))
                    
                    word, start_pos, end_pos = self._extract_word_at_position(clicked_text.text, approx_char_pos)
                    if word:
                        self.selected_word = word
                        self.selected_word_start_char = start_pos
                        self.selected_word_end_char = end_pos
                        self.word_selection_mode = True
                        self.pending_format_change_obj = clicked_text
                        self.before_format_change_state = copy.deepcopy(clicked_text.__dict__)
                        self.pdf_view.queue_draw()
                        self._update_ui_state()

    def _on_right_click(self, gesture, n_press, x, y):
        """Display context popover menu tailored to clicked text, shape, image, or empty area."""
        if not self.doc:
            return
        
        drawing_area_width = self.pdf_view.get_allocated_width()
        drawing_area_height = self.pdf_view.get_allocated_height()
        page_offset_x = max(0, (drawing_area_width - self.current_pdf_page_width) / 2)
        page_offset_y = max(0, (drawing_area_height - self.current_pdf_page_height) / 2)
        click_x_zoomed = x - page_offset_x
        click_y_zoomed = y - page_offset_y
        page_x = click_x_zoomed / self.zoom_level
        page_y = click_y_zoomed / self.zoom_level
        
        modifiers = Gtk.EventController.get_current_event_state(gesture)
        ctrl_pressed = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)

        if self.view_mode:
            if not self.view_sel_rect or not (self.view_sel_rect[0] <= page_x <= self.view_sel_rect[2] and self.view_sel_rect[1] <= page_y <= self.view_sel_rect[3]):
                clicked_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x, page_y))
                if clicked_word:
                    self.view_sel_rect = clicked_word['bbox']
                    self.view_selected_text = clicked_word['text']
                    self.pdf_view.queue_draw()
                else:
                    return
            
            if ctrl_pressed and self.view_selected_text:
                import webbrowser
                import re
                match = re.search(r'https?://[^\s]+', self.view_selected_text)
                if match:
                    webbrowser.open(match.group(0))
                return
                    
            popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            popover_box.set_margin_start(6); popover_box.set_margin_end(6)
            popover_box.set_margin_top(6); popover_box.set_margin_bottom(6)
            
            btn_copy = Gtk.Button(label=_("btn_copy_text"))
            btn_copy.connect("clicked", lambda b: self._handle_context_action("copy_view", None, x, y))
            popover_box.append(btn_copy)
            
            btn_hl = Gtk.Button(label=_("menu_highlight"))
            btn_hl.connect("clicked", lambda b: self._handle_context_action("highlight_view", None, x, y))
            popover_box.append(btn_hl)
            
            self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
            self.context_popover.set_child(popover_box)
            self.context_popover.set_parent(self.pdf_view)
            rect = Gdk.Rectangle()
            rect.x = int(x)
            rect.y = int(y)
            rect.width = 1
            rect.height = 1
            self.context_popover.set_pointing_to(rect)
            self.context_popover.popup()
            return

        clicked_text = self._find_text_at_pos(page_x, page_y)
        clicked_shape = self._find_shape_at_pos(page_x, page_y)
        clicked_image = self._find_image_at_pos(page_x, page_y)
        
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        popover_box.set_margin_start(6); popover_box.set_margin_end(6)
        popover_box.set_margin_top(6); popover_box.set_margin_bottom(6)
        
        if clicked_text:
            self.selected_text = clicked_text
            self.selected_shape = None
            self.selected_image = None
            
            btn_copy = Gtk.Button(label=_("btn_copy"))
            def on_copy_clicked(b):
                if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word'):
                    self.get_clipboard().set(self.selected_word)
                else:
                    self.get_clipboard().set(clicked_text.text)
                if hasattr(self, 'context_popover') and self.context_popover:
                    self.context_popover.popdown()
            btn_copy.connect("clicked", on_copy_clicked)
            popover_box.append(btn_copy)
            
            btn_paste = Gtk.Button(label=_("btn_paste"))
            btn_paste.set_sensitive(False)
            popover_box.append(btn_paste)
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            
            btn_bold = Gtk.Button(label=_("bold_tip"))
            btn_italic = Gtk.Button(label=_("italic_tip"))
            btn_underline = Gtk.Button(label=_("underline_tip"))
            btn_strikethrough = Gtk.Button(label=_("strikethrough_tip"))
            def on_bold_clicked(b):
                self._toggle_text_bold(clicked_text)
            def on_italic_clicked(b):
                self._toggle_text_italic(clicked_text)
            def on_underline_clicked(b):
                self._toggle_text_underline(clicked_text)
            def on_strikethrough_clicked(b):
                self._toggle_text_strikethrough(clicked_text)
            btn_bold.connect("clicked", on_bold_clicked)
            btn_italic.connect("clicked", on_italic_clicked)
            btn_underline.connect("clicked", on_underline_clicked)
            btn_strikethrough.connect("clicked", on_strikethrough_clicked)
            popover_box.append(btn_bold)
            popover_box.append(btn_italic)
            popover_box.append(btn_underline)
            popover_box.append(btn_strikethrough)
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            align_popover_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            align_popover_box.add_css_class("linked")
            btn_al_l = Gtk.Button(icon_name="format-justify-left-symbolic")
            btn_al_l.set_tooltip_text(_("align_left_tip"))
            btn_al_l.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "left"))
            align_popover_box.append(btn_al_l)

            btn_al_c = Gtk.Button(icon_name="format-justify-center-symbolic")
            btn_al_c.set_tooltip_text(_("align_center_tip"))
            btn_al_c.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "center"))
            align_popover_box.append(btn_al_c)

            btn_al_r = Gtk.Button(icon_name="format-justify-right-symbolic")
            btn_al_r.set_tooltip_text(_("align_right_tip"))
            btn_al_r.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "right"))
            align_popover_box.append(btn_al_r)

            btn_al_j = Gtk.Button(icon_name="format-justify-fill-symbolic")
            btn_al_j.set_tooltip_text(_("align_justify_tip"))
            btn_al_j.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "justify"))
            align_popover_box.append(btn_al_j)
            popover_box.append(align_popover_box)
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            
            btn_hl = Gtk.Button(label=_("menu_highlight"))
            btn_hl.connect("clicked", lambda b: self._handle_context_action("highlight_edit", clicked_text, x, y))
            popover_box.append(btn_hl)
            
            btn_rm_hl = Gtk.Button(label=_("menu_remove_highlight"))
            btn_rm_hl.connect("clicked", lambda b: self._handle_context_action("remove_highlight", clicked_text, x, y))
            popover_box.append(btn_rm_hl)
            
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            btn_edit = Gtk.Button(label=_("menu_edit_text"))
            btn_edit.connect("clicked", lambda b: self._handle_context_action("edit_text", clicked_text, x, y))
            popover_box.append(btn_edit)

            btn_link = Gtk.Button(label=_("menu_insert_edit_link"))
            def on_link_ctx(b):
                if hasattr(self, 'context_popover') and self.context_popover:
                    self.context_popover.popdown()
                pt_rect = Gdk.Rectangle()
                pt_rect.x = int(x); pt_rect.y = int(y); pt_rect.width = 1; pt_rect.height = 1
                self.show_link_popover(clicked_text, parent_widget=self.pdf_view, point_rect=pt_rect)
            btn_link.connect("clicked", on_link_ctx)
            popover_box.append(btn_link)
            
            btn_del = Gtk.Button(label=_("delete_confirm"))
            btn_del.add_css_class("destructive-action")
            def on_delete_text(b):
                self._handle_delete_with_confirmation(clicked_text, "delete_text_confirm")
            btn_del.connect("clicked", on_delete_text)
            popover_box.append(btn_del)
            
        elif clicked_shape:
            self.selected_shape = clicked_shape
            self.selected_text = None
            self.selected_image = None
            
            btn_del = Gtk.Button(label=_("menu_delete_shape"))
            btn_del.add_css_class("destructive-action")
            def on_delete_shape(b):
                self._handle_delete_with_confirmation(clicked_shape, "delete_shape_confirm")
            btn_del.connect("clicked", on_delete_shape)
            popover_box.append(btn_del)
            
        elif clicked_image:
            self.selected_image = clicked_image
            self.selected_text = None
            self.selected_shape = None
            
            btn_extract = Gtk.Button(label=_("menu_extract_image"))
            btn_extract.connect("clicked", lambda b: self._handle_context_action("extract_image", clicked_image, x, y))
            popover_box.append(btn_extract)

            btn_replace = Gtk.Button(label=_("menu_replace_image"))
            btn_replace.connect("clicked", lambda b: self._handle_context_action("replace_image", clicked_image, x, y))
            popover_box.append(btn_replace)

            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            btn_del = Gtk.Button(label=_("menu_delete_image"))
            btn_del.add_css_class("destructive-action")
            def on_delete_image(b):
                self._handle_delete_with_confirmation(clicked_image, "delete_image_confirm")
            btn_del.connect("clicked", on_delete_image)
            popover_box.append(btn_del)
            
        else:
            popover_box_empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            popover_box_empty.set_margin_start(6); popover_box_empty.set_margin_end(6)
            popover_box_empty.set_margin_top(6); popover_box_empty.set_margin_bottom(6)
            
            btn_paste_new = Gtk.Button(label=_("btn_paste_new"))
            btn_paste_new.connect("clicked", lambda b: self._handle_context_action("paste_new_text", (page_x, page_y), x, y))
            popover_box_empty.append(btn_paste_new)
            
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()
                
            self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
            self.context_popover.set_child(popover_box_empty)
            self.context_popover.set_parent(self.pdf_view)
            rect = Gdk.Rectangle()
            rect.x = int(x)
            rect.y = int(y)
            rect.width = 1
            rect.height = 1
            self.context_popover.set_pointing_to(rect)
            self.context_popover.set_position(Gtk.PositionType.RIGHT)
            self.context_popover.popup()
            return
            
        self._update_ui_state()
        self.pdf_view.queue_draw()
        
        self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
        self.context_popover.set_child(popover_box)
        self.context_popover.set_parent(self.pdf_view)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self.context_popover.set_pointing_to(rect)
        self.context_popover.set_position(Gtk.PositionType.RIGHT)
        self.context_popover.popup()

    def _handle_context_action(self, action, obj, x, y):
        """Execute actions dispatched from context menu popovers."""
        if hasattr(self, 'context_popover'):
            self.context_popover.popdown()
            
        if action == "edit_text":
            self._show_inline_editor(obj, click_x=x, click_y=y)
        elif action == "delete":
            self.selected_text = obj if type(obj).__name__ == 'EditableText' else None
            self.selected_shape = obj if type(obj).__name__ == 'EditableShape' else None
            if self.selected_text or self.selected_shape:
                obj_to_delete = self.selected_text or self.selected_shape
                command = DeleteObjectCommand(self, obj_to_delete)
                command.execute()
                self.undo_manager.add_command(command)
                self.selected_text = None
                self.selected_shape = None
                self._update_ui_state()
                self.pdf_view.queue_draw()
        elif action == "copy_view":
            if self.view_selected_text:
                self.get_clipboard().set(self.view_selected_text)
        elif action == "highlight_view":
            self.on_highlight_clicked(None)
        elif action == "highlight_edit":
            self.on_highlight_clicked(None)
        elif action == "remove_highlight":
            if obj and hasattr(obj, 'bbox'):
                self._remove_highlight_at_region(obj.bbox)
        elif action == "paste_new_text":
            page_x, page_y = obj
            clipboard = self.get_clipboard()
            def _on_paste_finished(cb, task):
                try:
                    text = cb.read_text_finish(task)
                    if text and text.strip():
                        self._create_text_from_paste(page_x, page_y, text)
                except Exception:
                    pass
            clipboard.read_text_async(None, _on_paste_finished)
        elif action == "toggle_bold":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_bold(self.selected_text)
        elif action == "toggle_italic":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_italic(self.selected_text)
        elif action == "toggle_underline":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_underline(self.selected_text)
        elif action == "toggle_strikethrough":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_strikethrough(self.selected_text)
        elif action == "extract_image":
            self._extract_image(obj)
        elif action == "replace_image":
            self._replace_image(obj)

    def _extract_image(self, image_obj):
        """Export an embedded or active image to disk."""
        if not image_obj:
            return

        img_bytes, ext = pdf_handler.extract_image_data(self.doc, image_obj)
        if not img_bytes:
            show_error_dialog(self, _("err_extract_image"), _("err_title"))
            return

        page_num = getattr(image_obj, 'page_number', self.current_page_index) or 0
        xref_part = getattr(image_obj, 'xref', None) or 'extracted'
        default_name = f"image_p{page_num + 1}_{xref_part}.{ext}"

        filter_img = Gtk.FileFilter(name=_("image_filter_label"))
        filter_img.add_pattern(f"*.{ext}")
        filter_all = Gtk.FileFilter(name=_("filter_all_files"))
        filter_all.add_pattern("*")

        def on_save_finish(file):
            if file:
                save_path = file.get_path()
                try:
                    with open(save_path, "wb") as f:
                        f.write(img_bytes)
                    self.status_label.set_text(_("image_extracted_success", os.path.basename(save_path)))
                except Exception as err:
                    show_error_dialog(self, str(err), _("err_title"))

        show_save_file_dialog(
            self,
            _("menu_extract_image"),
            initial_name=default_name,
            filters=[filter_img, filter_all],
            callback=on_save_finish
        )

    def _replace_image(self, image_obj):
        """Prompt user for a replacement image file and replace using page.replace_image()."""
        if not image_obj:
            return

        filter_img = Gtk.FileFilter(name=_("image_filter_label"))
        for mime in ["image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"]:
            filter_img.add_mime_type(mime)

        def on_open_finish(file):
            if file:
                image_path = file.get_path()
                try:
                    with open(image_path, "rb") as f:
                        new_raw_bytes = f.read()
                    if not new_raw_bytes:
                        return

                    command = ReplaceImageCommand(self, image_obj, new_raw_bytes)
                    if command.execute():
                        self.undo_manager.add_command(command)
                except Exception as err:
                    show_error_dialog(self, _("image_add_error", err), _("image_error_title"))

        show_open_file_dialog(
            self,
            _("menu_replace_image"),
            filters=[filter_img],
            callback=on_open_finish
        )

    def _convert_view_selection_to_editable(self):
        """Convert view selection to editable."""
        if not self.view_sel_rect or not self.view_selected_text:
            return
            
        from .models import EditableText
        from .undo_manager import AddObjectCommand
        
        x1, y1, x2, y2 = self.view_sel_rect
        new_obj = EditableText(x1, y1, self.view_selected_text, is_new=False)
        new_obj.bbox = (x1, y1, x2, y2)
        new_obj.page_number = self.current_page_index
        
        command = AddObjectCommand(self, new_obj)
        command.execute()
        self.undo_manager.add_command(command)
        self.selected_text = new_obj
        self.view_sel_rect = None
        self.view_selected_text = None
        self.word_selection_mode = False
        self.pdf_view.queue_draw()

    def _toggle_text_bold(self, text_obj):
        """Toggle text bold."""
        if text_obj:
            self.selected_text = text_obj
            old_properties = {'is_bold': text_obj.is_bold, 'bbox': text_obj.bbox}
            new_properties = {'is_bold': not text_obj.is_bold, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _toggle_text_italic(self, text_obj):
        """Toggle text italic."""
        if text_obj:
            self.selected_text = text_obj
            old_properties = {'is_italic': text_obj.is_italic, 'bbox': text_obj.bbox}
            new_properties = {'is_italic': not text_obj.is_italic, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _toggle_text_underline(self, text_obj):
        """Toggle text underline."""
        if text_obj:
            self.selected_text = text_obj
            old_val = getattr(text_obj, 'is_underline', False)
            old_properties = {'is_underline': old_val, 'bbox': text_obj.bbox}
            new_properties = {'is_underline': not old_val, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _toggle_text_strikethrough(self, text_obj):
        """Toggle text strikethrough."""
        if text_obj:
            self.selected_text = text_obj
            old_val = getattr(text_obj, 'is_strikethrough', False)
            old_properties = {'is_strikethrough': old_val, 'bbox': text_obj.bbox}
            new_properties = {'is_strikethrough': not old_val, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _set_text_alignment(self, text_obj, new_align):
        """Set text alignment with undo/redo."""
        if text_obj:
            self.selected_text = text_obj
            old_val = getattr(text_obj, 'alignment', 'left')
            if old_val != new_align:
                old_properties = {'alignment': old_val, 'bbox': text_obj.bbox}
                new_properties = {'alignment': new_align, 'bbox': text_obj.bbox}
                command = EditObjectCommand(self, text_obj, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self.pdf_view.queue_draw()
                if hasattr(self, '_update_text_format_controls'):
                    self._update_text_format_controls(text_obj)
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def on_insert_edit_link_clicked(self, button=None):
        """Handle toolbar Insert/Edit link button click."""
        target = self.selected_text
        if not target:
            return
        anchor = getattr(self, 'link_button', self.pdf_view)
        self.show_link_popover(target, parent_widget=anchor)

    def show_link_popover(self, text_obj, parent_widget=None, point_rect=None):
        """Display popover dialog allowing user to insert, edit, or remove hyperlink for text_obj."""
        if not text_obj:
            return

        if hasattr(self, '_link_popover') and self._link_popover:
            try:
                self._link_popover.popdown()
                self._link_popover.unparent()
            except Exception:
                pass
            self._link_popover = None

        popover = Gtk.Popover(autohide=True, has_arrow=True)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)

        title_lbl = Gtk.Label(label=_("dialog_link_title"))
        title_lbl.add_css_class("heading")
        title_lbl.set_halign(Gtk.Align.START)
        content_box.append(title_lbl)

        url_lbl = Gtk.Label(label=_("link_url_label"))
        url_lbl.set_halign(Gtk.Align.START)
        url_lbl.add_css_class("dim-label")
        content_box.append(url_lbl)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("https://example.com")
        url_entry.set_width_chars(32)

        initial_url = getattr(text_obj, 'link_url', None) or ""
        if not initial_url and hasattr(text_obj, 'get_link_url'):
            initial_url = text_obj.get_link_url() or ""
        url_entry.set_text(initial_url)
        content_box.append(url_entry)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)

        def apply_link(b=None):
            target_url = url_entry.get_text().strip()
            popover.popdown()
            if target_url:
                self._apply_text_link(text_obj, target_url)
            else:
                self._remove_text_link(text_obj)

        def remove_link(b=None):
            popover.popdown()
            self._remove_text_link(text_obj)

        def cancel_link(b=None):
            popover.popdown()

        btn_cancel = Gtk.Button(label=_("btn_cancel"))
        btn_cancel.connect("clicked", cancel_link)
        btn_box.append(btn_cancel)

        if getattr(text_obj, 'link_url', None) or getattr(text_obj, 'is_link', False):
            btn_remove = Gtk.Button(label=_("btn_remove_link"))
            btn_remove.add_css_class("destructive-action")
            btn_remove.connect("clicked", remove_link)
            btn_box.append(btn_remove)

        btn_apply = Gtk.Button(label=_("btn_apply"))
        btn_apply.add_css_class("suggested-action")
        btn_apply.connect("clicked", apply_link)
        url_entry.connect("activate", apply_link)
        btn_box.append(btn_apply)

        content_box.append(btn_box)
        popover.set_child(content_box)

        anchor = parent_widget or getattr(self, 'link_button', self.pdf_view)
        popover.set_parent(anchor)
        if point_rect:
            popover.set_pointing_to(point_rect)
        self._link_popover = popover
        popover.popup()

    def _apply_text_link(self, text_obj, url: str):
        """Apply hyperlink URL and blue underlined styling to text_obj."""
        if not text_obj or not url:
            return
        if not url.startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        self.selected_text = text_obj
        old_props = {
            'link_url': getattr(text_obj, 'link_url', None),
            'color': getattr(text_obj, 'color', (0.0, 0.0, 0.0)),
            'is_underline': getattr(text_obj, 'is_underline', False),
            'bbox': text_obj.bbox
        }
        # Hyperlink styling: blue #0000ee and underline
        new_props = {
            'link_url': url,
            'color': (0.0, 0.0, 238.0 / 255.0),
            'is_underline': True,
            'bbox': text_obj.bbox
        }
        cmd = EditObjectCommand(self, text_obj, old_props, new_props)
        cmd.execute()
        self.undo_manager.add_command(cmd)
        self._update_text_format_controls(text_obj)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("link_applied_success"))
        self.document_modified = True
        self.pdf_view.queue_draw()

    def _remove_text_link(self, text_obj):
        """Remove hyperlink URL from text_obj and restore original properties."""
        if not text_obj:
            return
        self.selected_text = text_obj
        old_props = {
            'link_url': getattr(text_obj, 'link_url', None),
            'color': getattr(text_obj, 'color', (0.0, 0.0, 0.0)),
            'is_underline': getattr(text_obj, 'is_underline', False),
            'bbox': text_obj.bbox
        }
        orig_color = getattr(text_obj, 'original_color', (0.0, 0.0, 0.0))
        if orig_color == (0.0, 0.0, 238.0 / 255.0):
            orig_color = (0.0, 0.0, 0.0)
        new_props = {
            'link_url': None,
            'color': orig_color,
            'is_underline': False,
            'bbox': text_obj.bbox
        }
        cmd = EditObjectCommand(self, text_obj, old_props, new_props)
        cmd.execute()
        self.undo_manager.add_command(cmd)
        self._update_text_format_controls(text_obj)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("link_removed_success"))
        self.document_modified = True
        self.pdf_view.queue_draw()

    def _get_link_url_at_pos(self, page_x, page_y):
        """Find destination URL at page coordinates from editable texts or PDF link annotations."""
        for t in getattr(self, 'editable_texts', []):
            if getattr(t, 'page_number', None) != self.current_page_index:
                continue
            if getattr(t, 'bbox', None):
                bx1, by1, bx2, by2 = t.bbox
                if min(bx1, bx2) <= page_x <= max(bx1, bx2) and min(by1, by2) <= page_y <= max(by1, by2):
                    if getattr(t, 'is_link', False):
                        url = t.get_link_url() if hasattr(t, 'get_link_url') else getattr(t, 'link_url', None)
                        if url:
                            return url
        if getattr(self, 'doc', None) and 0 <= self.current_page_index < len(self.doc):
            try:
                page = self.doc[self.current_page_index]
                pt = fitz.Point(page_x, page_y)
                for link in page.get_links():
                    if link.get('kind') == fitz.LINK_URI and link.get('uri'):
                        rect = link.get('from')
                        if rect and rect.contains(pt):
                            return link.get('uri')
            except Exception:
                pass
        return None

    def _open_url(self, url: str):
        """Open web link in the system default browser."""
        if not url:
            return
        if not url.startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        try:
            from gi.repository import Gtk, Gdk
            Gtk.show_uri(self, url, Gdk.CURRENT_TIME)
        except Exception:
            try:
                from gi.repository import Gio
                Gio.AppInfo.launch_default_for_uri(url, None)
            except Exception:
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception as e:
                    print(f"Warning: could not open URL {url}: {e}")

    def _update_confirm_delete_menu_state(self, val: bool):
        """Update the confirm delete menu action state."""
        if hasattr(self, 'action_confirm_delete'):
            self.action_confirm_delete.set_state(GLib.Variant.new_boolean(val))

    def _handle_delete_with_confirmation(self, obj, confirmation_key):
        """Handle delete with confirmation."""
        from .ui_components import show_confirm_dialog
        
        if isinstance(obj, EditableText):
            confirm_text = _("delete_text_confirm").format(f"{obj.text[:50]}...")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, EditableShape):
            confirm_text = _("delete_shape_confirm")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, EditableImage):
            confirm_text = _("delete_image_confirm")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, EditableStroke):
            confirm_text = _("delete_shape_confirm")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, AcroFormField):
            fname = getattr(obj, 'field_name', '') or 'field'
            confirm_text = _("delete_form_field_confirm").format(fname)
            confirm_title = _("delete_confirm_title")
        else:
            return

        confirm_needed = get_setting("confirm_delete_objects", True)
        confirmed = True
        if confirm_needed:
            confirmed, do_not_ask = show_confirm_dialog(
                self, confirm_text, confirm_title, destructive=True,
                checkbox_label=_("do_not_ask_again")
            )
            if confirmed and do_not_ask:
                set_setting("confirm_delete_objects", False)
                self._update_confirm_delete_menu_state(False)
            
        if confirmed:
            if isinstance(obj, AcroFormField):
                if getattr(self, '_active_editing_form_field', None) == obj:
                    self._close_active_form_field_editor()
                self.selected_form_field = None
                command = DeleteFormFieldCommand(self, obj)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._update_tab_dirty_state()
                self._update_form_builder_controls_for_selected()
                self._update_ui_state()
                self.pdf_view.queue_draw()
                self.status_label.set_text(_("object_deleted"))
                return
            command = DeleteObjectCommand(self, obj)
            command.execute()
            self.undo_manager.add_command(command)
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self._update_ui_state()
            self.pdf_view.queue_draw()
            self.status_label.set_text(_("object_deleted"))

    def _remove_highlight_at_region(self, bbox, is_visual=False):
        """Remove highlight at region."""
        if not self.doc:
            return
        try:
            success, removed_count = pdf_handler.remove_highlight_annotations(
                self.doc, self.current_page_index, bbox, is_visual=is_visual
            )
            if success and removed_count > 0:
                pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
                self.document_modified = True
                self._refresh_thumbnail(self.current_page_index)
                self._update_ui_state()
                self.pdf_view.queue_draw()
        except Exception as e:
            print(f"Error removing highlight: {e}")

    def _create_text_from_paste(self, page_x, page_y, text):
        """Create text from paste."""
        if not self.doc or not text or not text.strip():
            return
        
        try:
            font_family = self._last_font_family or "Liberation Sans"
            font_size = self._last_font_size or 11.0
            is_bold = self._last_is_bold or False
            is_italic = self._last_is_italic or False
            is_strikethrough = getattr(self, '_last_is_strikethrough', False)
            alignment = getattr(self, '_last_alignment', 'left')
            color = self._last_color or (0.0, 0.0, 0.0)
            
            new_text = EditableText(
                x=page_x,
                y=page_y,
                text=text.strip(),
                font_size=font_size,
                font_family=font_family,
                color=color,
                is_new=True,
                baseline=page_y + (font_size * 0.85),
                alignment=alignment
            )
            new_text.is_bold = is_bold
            new_text.is_italic = is_italic
            new_text.is_strikethrough = is_strikethrough
            new_text.page_number = self.current_page_index
            
            self.editable_texts.append(new_text)
            command = AddObjectCommand(self, new_text)
            command.execute()
            self.undo_manager.add_command(command)
            
            self.document_modified = True
            self._refresh_thumbnail(self.current_page_index)
            self._update_ui_state()
            self.pdf_view.queue_draw()
            
        except Exception as e:
            print(f"Error creating text from paste: {e}")
