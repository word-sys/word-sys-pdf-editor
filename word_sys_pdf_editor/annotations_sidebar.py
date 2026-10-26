# -*- coding: utf-8 -*-
"""Annotations Tree List Sidebar for Word-Sys PDF Editor.

Provides a modern GTK4 ListView sidebar displaying all annotations, highlights,
drawings, shapes, text blocks, form fields, and measurements across the document
with real-time filtering, search, bi-directional canvas selection sync, and
instant viewport scrolling.
"""

from typing import Any, List, Optional, Tuple
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, GObject, Gio, Pango

from .i18n import _
from .models import (
    EditableText,
    EditableImage,
    EditableShape,
    EditableStroke,
    AcroFormField,
    MeasurementObject,
    StickyNoteObject,
    RedactionMark,
)


class AnnotationListItem(GObject.Object):
    """GObject data item representing a document annotation or editable object."""

    __gtype_name__ = "AnnotationListItem"

    item_id = GObject.Property(type=str, default="")
    item_type = GObject.Property(type=str, default="annotation")
    category = GObject.Property(type=str, default="all")
    title = GObject.Property(type=str, default="")
    subtitle = GObject.Property(type=str, default="")
    page_number = GObject.Property(type=int, default=0)
    icon_name = GObject.Property(type=str, default="dialog-information-symbolic")
    badge_text = GObject.Property(type=str, default="")

    def __init__(
        self,
        item_id: str,
        item_type: str,
        category: str,
        title: str,
        subtitle: str,
        page_number: int,
        icon_name: str,
        target_obj: Any = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        native_annot: Any = None,
    ):
        super().__init__()
        self.item_id = item_id
        self.item_type = item_type
        self.category = category
        self.title = title
        self.subtitle = subtitle
        self.page_number = page_number
        self.icon_name = icon_name
        self.badge_text = _("badge_page_fmt").format(page_number + 1)
        self.target_obj = target_obj
        self.bbox = bbox if bbox is not None else (0.0, 0.0, 0.0, 0.0)
        self.native_annot = native_annot


class AnnotationListItemFactory(Gtk.SignalListItemFactory):
    """Signal list item factory that creates and binds row widgets for the annotations list view."""

    def __init__(self, sidebar=None):
        super().__init__()
        self.sidebar = sidebar
        self.connect("setup", self._on_setup)
        self.connect("bind", self._on_bind)

    def _on_setup(self, factory, list_item: Gtk.ListItem):
        """Build the row widget hierarchy."""
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row_box.add_css_class("annotation-row")
        row_box.set_margin_top(4)
        row_box.set_margin_bottom(4)
        row_box.set_margin_start(8)
        row_box.set_margin_end(8)

        icon_img = Gtk.Image()
        icon_img.set_pixel_size(20)
        icon_img.set_valign(Gtk.Align.CENTER)
        row_box.append(icon_img)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        text_box.set_valign(Gtk.Align.CENTER)

        title_label = Gtk.Label(xalign=0.0)
        title_label.add_css_class("annotation-title")
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_max_width_chars(26)
        text_box.append(title_label)

        subtitle_label = Gtk.Label(xalign=0.0)
        subtitle_label.add_css_class("annotation-subtitle")
        subtitle_label.add_css_class("dim-label")
        subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle_label.set_max_width_chars(28)
        text_box.append(subtitle_label)

        row_box.append(text_box)

        badge_label = Gtk.Label()
        badge_label.add_css_class("annotation-badge")
        badge_label.add_css_class("dim-label")
        badge_label.set_valign(Gtk.Align.CENTER)
        row_box.append(badge_label)

        list_item.set_child(row_box)

    def _on_bind(self, factory, list_item: Gtk.ListItem):
        """Bind model item properties to the row widgets."""
        row_box = list_item.get_child()
        if not row_box:
            return

        icon_img = row_box.get_first_child()
        text_box = icon_img.get_next_sibling()
        badge_label = row_box.get_last_child()

        title_label = text_box.get_first_child()
        subtitle_label = text_box.get_last_child()

        item: AnnotationListItem = list_item.get_item()
        if item:
            icon_img.set_from_icon_name(item.icon_name)
            title_label.set_text(item.title)
            subtitle_label.set_text(item.subtitle)
            badge_label.set_text(item.badge_text)


class AnnotationsSidebar(Gtk.Box):
    """Right sidebar component displaying the document annotations and objects hierarchy."""

    CATEGORY_ALL = "all"
    CATEGORY_TEXT = "text"
    CATEGORY_IMAGES = "images"
    CATEGORY_SHAPES = "shapes"
    CATEGORY_PEN = "pen"
    CATEGORY_HIGHLIGHTS = "highlights"
    CATEGORY_FORMS = "forms"
    CATEGORY_MEASUREMENTS = "measurements"
    CATEGORY_NOTES = "notes"
    CATEGORY_REDACTIONS = "redactions"

    def __init__(self, editor_window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.editor_window = editor_window
        self.add_css_class("annotations-sidebar")
        self.set_size_request(280, -1)

        self._syncing_selection = False
        self._current_search_query = ""
        self._current_category_filter = self.CATEGORY_ALL

        self._build_ui()

    def _build_ui(self):
        """Construct the sidebar widgets."""
        # Top Header Box
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.add_css_class("annotations-header")
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(8)
        header_box.set_margin_start(10)
        header_box.set_margin_end(10)

        title_label = Gtk.Label(label=_("annotations_sidebar_title"), xalign=0.0, hexpand=True)
        title_label.add_css_class("title-4")
        header_box.append(title_label)

        self.count_badge = Gtk.Label(label="0")
        self.count_badge.add_css_class("annotation-count-pill")
        self.count_badge.add_css_class("dim-label")
        header_box.append(self.count_badge)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.add_css_class("flat")
        refresh_btn.set_tooltip_text(_("refresh_annotations_tip"))
        refresh_btn.connect("clicked", lambda b: self.refresh())
        header_box.append(refresh_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text(_("close_sidebar_tip"))
        close_btn.connect("clicked", lambda b: self.toggle_visible(False))
        header_box.append(close_btn)

        self.append(header_box)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Filter & Search Controls
        controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        controls_box.set_margin_top(8)
        controls_box.set_margin_bottom(6)
        controls_box.set_margin_start(10)
        controls_box.set_margin_end(10)

        self.search_entry = Gtk.SearchEntry(placeholder_text=_("search_annotations_placeholder"))
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("notify::text", self._on_search_changed)
        controls_box.append(self.search_entry)

        categories = [
            _("filter_all_objects"),
            _("filter_text"),
            _("filter_images"),
            _("filter_shapes"),
            _("filter_pen"),
            _("filter_highlights"),
            _("filter_forms"),
            _("filter_measurements"),
            _("filter_notes"),
            _("category_redactions"),
        ]
        self.category_keys = [
            self.CATEGORY_ALL,
            self.CATEGORY_TEXT,
            self.CATEGORY_IMAGES,
            self.CATEGORY_SHAPES,
            self.CATEGORY_PEN,
            self.CATEGORY_HIGHLIGHTS,
            self.CATEGORY_FORMS,
            self.CATEGORY_MEASUREMENTS,
            self.CATEGORY_NOTES,
            self.CATEGORY_REDACTIONS,
        ]
        self.category_dropdown = Gtk.DropDown.new_from_strings(categories)
        self.category_dropdown.connect("notify::selected", self._on_category_changed)
        controls_box.append(self.category_dropdown)

        self.append(controls_box)

        # Main List Store and Filter
        self.list_store = Gio.ListStore.new(AnnotationListItem)

        self.custom_filter = Gtk.CustomFilter.new(self._filter_match_func)
        self.filter_model = Gtk.FilterListModel.new(self.list_store, self.custom_filter)
        self.selection_model = Gtk.SingleSelection.new(self.filter_model)
        self.selection_model.connect("selection-changed", self._on_selection_changed)

        factory = AnnotationListItemFactory(sidebar=self)
        self.list_view = Gtk.ListView.new(self.selection_model, factory)
        self.list_view.set_vexpand(True)
        self.list_view.connect("activate", self._on_list_view_activated)

        self.scrolled_window = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_child(self.list_view)

        # Empty state container
        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, vexpand=True)
        self.empty_box.set_valign(Gtk.Align.CENTER)
        self.empty_box.set_halign(Gtk.Align.CENTER)
        self.empty_box.set_margin_start(20)
        self.empty_box.set_margin_end(20)

        empty_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        empty_icon.set_pixel_size(36)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)

        empty_label = Gtk.Label(label=_("annotations_empty_state"))
        empty_label.add_css_class("dim-label")
        empty_label.set_wrap(True)
        empty_label.set_justify(Gtk.Justification.CENTER)
        self.empty_box.append(empty_label)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.scrolled_window, "list")
        self.stack.add_named(self.empty_box, "empty")
        self.stack.set_visible_child_name("empty")
        self.stack.set_vexpand(True)

        self.append(self.stack)

    def _filter_match_func(self, item: AnnotationListItem) -> bool:
        """Evaluate if an item matches the current search query and category filter."""
        if not item:
            return False

        if self._current_category_filter != self.CATEGORY_ALL:
            if item.category != self._current_category_filter:
                return False

        if self._current_search_query:
            query = self._current_search_query.lower()
            text_match = (
                query in item.title.lower()
                or query in item.subtitle.lower()
                or query in item.item_type.lower()
                or query in f"page {item.page_number + 1}".lower()
            )
            if not text_match:
                return False

        return True

    def _on_search_changed(self, entry: Gtk.SearchEntry, *args):
        """Update search query filter on entry text changes."""
        self._current_search_query = entry.get_text().strip()
        self.custom_filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_empty_state_and_count()

    def _on_category_changed(self, dropdown: Gtk.DropDown, _pspec):
        """Update category filter on dropdown selection changes."""
        idx = dropdown.get_selected()
        if 0 <= idx < len(self.category_keys):
            self._current_category_filter = self.category_keys[idx]
        else:
            self._current_category_filter = self.CATEGORY_ALL
        self.custom_filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_empty_state_and_count()

    def _update_empty_state_and_count(self):
        """Synchronize count label and toggle between list and empty state view."""
        n_filtered = self.filter_model.get_n_items()
        n_total = self.list_store.get_n_items()
        if self._current_search_query or self._current_category_filter != self.CATEGORY_ALL:
            self.count_badge.set_text(f"{n_filtered}/{n_total}")
        else:
            self.count_badge.set_text(str(n_total))

        if n_filtered == 0:
            self.stack.set_visible_child_name("empty")
        else:
            self.stack.set_visible_child_name("list")

    def _on_list_view_activated(self, list_view: Gtk.ListView, position: int):
        """Handle enter or double-click on a row item."""
        item = self.filter_model.get_item(position)
        if item and self.editor_window:
            self.editor_window.select_and_scroll_to_annotation(item)

    def _on_selection_changed(self, selection_model: Gtk.SingleSelection, position: int, n_items: int):
        """Navigate to and highlight annotation on single selection changes."""
        if self._syncing_selection:
            return

        selected_idx = selection_model.get_selected()
        if selected_idx != Gtk.INVALID_LIST_POSITION:
            item = self.filter_model.get_item(selected_idx)
            if item and self.editor_window:
                self.editor_window.select_and_scroll_to_annotation(item)

    def toggle_visible(self, visible: Optional[bool] = None):
        """Toggle or set right sidebar visibility."""
        new_vis = not self.get_visible() if visible is None else visible
        self.set_visible(new_vis)
        if self.editor_window and hasattr(self.editor_window, "toggle_annotations_button"):
            self.editor_window.toggle_annotations_button.set_active(new_vis)
        if new_vis:
            self.refresh()

    def sync_selection(self, selected_obj: Any):
        """Synchronize list view selection with an object selected on the canvas."""
        if not selected_obj or self._syncing_selection:
            return

        self._syncing_selection = True
        try:
            n_items = self.filter_model.get_n_items()
            for i in range(n_items):
                item: AnnotationListItem = self.filter_model.get_item(i)
                if item and item.target_obj is selected_obj:
                    self.selection_model.set_selected(i)
                    if hasattr(self.list_view, "scroll_to"):
                        try:
                            self.list_view.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
                        except Exception:
                            pass
                    break
        finally:
            self._syncing_selection = False

    def refresh(self):
        """Reload all annotations and objects from the active document session."""
        if not self.editor_window:
            return
        if hasattr(self, "get_visible") and not self.get_visible():
            self._needs_refresh = True
            return

        doc = getattr(self.editor_window, "doc", None)
        session = getattr(self.editor_window, "_active_session", None)
        self.populate(doc, session)

    def populate(self, doc: Any, session: Any):
        """Scan document and session to populate the annotations list store."""
        self.list_store.remove_all()
        if not doc or doc.is_closed:
            self._update_empty_state_and_count()
            return

        items: List[AnnotationListItem] = []
        page_count = doc.page_count

        for p in range(page_count):
            # 1. Session Editable Texts
            if session and hasattr(session, "editable_texts"):
                for t in session.editable_texts:
                    if getattr(t, "page_number", 0) == p:
                        clean_text = (t.text or "").replace("\n", " ").strip()
                        snippet = clean_text[:28] + ("…" if len(clean_text) > 28 else "")
                        font_name = getattr(t, "font_family_base", getattr(t, "font_family_original", "Sans"))
                        items.append(
                            AnnotationListItem(
                                item_id=f"text_{p}_{id(t)}",
                                item_type="text",
                                category=self.CATEGORY_TEXT,
                                title=snippet if snippet else _("tool_add_text"),
                                subtitle=f"{font_name}, {getattr(t, 'font_size', 11.0):.1f}pt",
                                page_number=p,
                                icon_name="insert-text-symbolic",
                                target_obj=t,
                                bbox=getattr(t, "bbox", None),
                            )
                        )

            # 2. Images: Session Editable Images & PDF Embedded Images
            page_has_session_images = False
            if session and hasattr(session, "editable_images") and session.editable_images:
                for img in session.editable_images:
                    img_page = getattr(img, "page_number", None)
                    if img_page is None and hasattr(self.editor_window, "current_page_index"):
                        img_page = self.editor_window.current_page_index
                    if img_page == p:
                        page_has_session_images = True
                        bx = getattr(img, "bbox", (0, 0, 0, 0))
                        w, h = abs(bx[2] - bx[0]), abs(bx[3] - bx[1])
                        items.append(
                            AnnotationListItem(
                                item_id=f"img_{p}_{id(img)}",
                                item_type="image",
                                category=self.CATEGORY_IMAGES,
                                title=f"Image ({int(w)}×{int(h)} pt)",
                                subtitle=_("badge_page_fmt").format(p + 1),
                                page_number=p,
                                icon_name="insert-image-symbolic",
                                target_obj=img,
                                bbox=bx,
                            )
                        )

            # If no session editable images for page p, scan embedded PDF images
            if not page_has_session_images:
                try:
                    if doc.get_page_images(p):
                        page = doc.load_page(p)
                        img_infos = page.get_image_info(xrefs=True)
                        for idx, info in enumerate(img_infos):
                            bx = info.get("bbox", (0, 0, 0, 0))
                            w = info.get("width", abs(bx[2] - bx[0]))
                            h = info.get("height", abs(bx[3] - bx[1]))
                            items.append(
                                AnnotationListItem(
                                    item_id=f"doc_img_{p}_{idx}",
                                    item_type="image",
                                    category=self.CATEGORY_IMAGES,
                                    title=f"Image ({int(w)}×{int(h)} pt)",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="insert-image-symbolic",
                                    target_obj=None,
                                    bbox=tuple(bx),
                                )
                            )
                except Exception:
                    pass

            # 3. Session Editable Shapes
            if session and hasattr(session, "editable_shapes"):
                for shp in session.editable_shapes:
                    if getattr(shp, "page_number", 0) == p:
                        stype = getattr(shp, "shape_type", "rectangle")
                        icon = "checkbox-symbolic"
                        if stype == "ellipse":
                            icon = "media-record-symbolic"
                        elif stype == "checkmark":
                            icon = "emblem-ok-symbolic"
                        elif stype == "cross":
                            icon = "window-close-symbolic"

                        items.append(
                            AnnotationListItem(
                                item_id=f"shape_{p}_{id(shp)}",
                                item_type=stype,
                                category=self.CATEGORY_SHAPES,
                                title=f"Shape: {stype.capitalize()}",
                                subtitle=f"Stroke: {getattr(shp, 'stroke_width', 1.0):.1f}pt",
                                page_number=p,
                                icon_name=icon,
                                target_obj=shp,
                                bbox=getattr(shp, "bbox", None),
                            )
                        )

            # 4. Session Editable Strokes (Pens & Highlighters)
            if session and hasattr(session, "editable_strokes"):
                for stk in session.editable_strokes:
                    if getattr(stk, "page_number", 0) == p:
                        ttype = getattr(stk, "tool_type", "pen")
                        is_hl = ttype == "highlighter"
                        items.append(
                            AnnotationListItem(
                                item_id=f"stroke_{p}_{id(stk)}",
                                item_type=ttype,
                                category=self.CATEGORY_HIGHLIGHTS if is_hl else self.CATEGORY_PEN,
                                title=_("tool_highlighter") if is_hl else _("tool_pen"),
                                subtitle=f"Width: {getattr(stk, 'stroke_width', 2.0):.1f}pt ({len(getattr(stk, 'points', []))} pts)",
                                page_number=p,
                                icon_name="marker-symbolic" if is_hl else "document-edit-symbolic",
                                target_obj=stk,
                                bbox=getattr(stk, "bbox", None),
                            )
                        )

            # 5. Session Form Fields
            if session and hasattr(session, "form_fields"):
                for ff in session.form_fields:
                    if getattr(ff, "page_number", 0) == p:
                        fname = getattr(ff, "field_name", "")
                        ftype = getattr(ff, "field_type", "text")
                        title = f"Field: {fname}" if fname else f"Form {ftype.capitalize()}"
                        rect = getattr(ff, "rect", None)
                        icon_name = "channel-secure-symbolic" if ftype.lower() == "signature" else "edit-select-all-symbolic"
                        items.append(
                            AnnotationListItem(
                                item_id=f"field_{p}_{id(ff)}",
                                item_type="form_field",
                                category=self.CATEGORY_FORMS,
                                title=title,
                                subtitle=f"Type: {ftype.capitalize()}",
                                page_number=p,
                                icon_name=icon_name,
                                target_obj=ff,
                                bbox=rect,
                            )
                        )

            # 6. Session Measurements (Distance & Area)
            if session and hasattr(session, "measurements"):
                page_meas = session.measurements.get(p, [])
                for m in page_meas:
                    mtype = getattr(m, "measurement_type", "distance")
                    mlabel = getattr(m, "label", None)
                    mval = getattr(m, "formatted_value", "")
                    title = mlabel if mlabel else (f"Distance: {mval}" if mtype == "distance" else f"Area: {mval}")
                    items.append(
                        AnnotationListItem(
                            item_id=f"meas_{p}_{id(m)}",
                            item_type=mtype,
                            category=self.CATEGORY_MEASUREMENTS,
                            title=title,
                            subtitle=f"{mtype.capitalize()}",
                            page_number=p,
                            icon_name="straighten-symbolic" if mtype == "distance" else "view-grid-symbolic",
                            target_obj=m,
                            bbox=getattr(m, "bbox", None),
                        )
                    )

            # 7. Session Sticky Notes & Comments
            if session and hasattr(session, "sticky_notes"):
                page_notes = session.sticky_notes.get(p, [])
                for note in page_notes:
                    content = (note.content or "").strip()
                    title = content[:26] + ("…" if len(content) > 26 else "") if content else _("sticky_note")
                    author_str = note.author or _("author_user")
                    date_snippet = note.created_at[:10] if getattr(note, 'created_at', None) else ""
                    sub = f"{author_str} • {date_snippet}".strip(" •")
                    items.append(
                        AnnotationListItem(
                            item_id=f"stickynote_{p}_{note.id}",
                            item_type="sticky_note",
                            category=self.CATEGORY_NOTES,
                            title=title,
                            subtitle=sub or _("sticky_note"),
                            page_number=p,
                            icon_name="dialog-information-symbolic",
                            target_obj=note,
                            bbox=note.bbox,
                        )
                    )

            # 8. Session Redaction Marks (Pending Staged Redactions)
            if session and hasattr(session, "redaction_marks"):
                page_redacts = session.redaction_marks.get(p, [])
                for mark in page_redacts:
                    otext = (mark.overlay_text or "").strip()
                    title = f"Redact: {otext}" if otext else _("redaction_mark")
                    bx = mark.bbox
                    w, h = abs(bx[2] - bx[0]), abs(bx[3] - bx[1])
                    sub = f"{int(w)}×{int(h)} pt • {'White' if mark.fill_color == (1.0, 1.0, 1.0) else 'Black'}"
                    items.append(
                        AnnotationListItem(
                            item_id=f"redact_{p}_{mark.id}",
                            item_type="redaction_mark",
                            category=self.CATEGORY_REDACTIONS,
                            title=title,
                            subtitle=sub,
                            page_number=p,
                            icon_name="edit-clear-symbolic",
                            target_obj=mark,
                            bbox=mark.bbox,
                        )
                    )

            # 8. Native PDF Page Annotations
            try:
                page = doc.load_page(p)
                annots = page.annots()
                if annots:
                    for idx, a in enumerate(annots):
                        atype = a.type[0]
                        arect = (a.rect.x0, a.rect.y0, a.rect.x1, a.rect.y1)
                        content = (a.info.get("content") or "").strip()

                        if atype == 8:  # Highlight
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_highlight",
                                    category=self.CATEGORY_HIGHLIGHTS,
                                    title=f"Highlight: {content[:24]}…" if content else _("highlight"),
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="marker-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype == 9:  # Underline
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_underline",
                                    category=self.CATEGORY_HIGHLIGHTS,
                                    title=f"Underline: {content[:24]}…" if content else "Underline",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="format-text-underline-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype == 11:  # StrikeOut
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_strikeout",
                                    category=self.CATEGORY_HIGHLIGHTS,
                                    title=f"StrikeOut: {content[:24]}…" if content else "StrikeOut",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="format-text-strikethrough-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype in (0, 1):  # Text / Note
                            # Avoid duplicate listing if already tracked in session.sticky_notes
                            if session and hasattr(session, "sticky_notes") and any(
                                getattr(sn, "native_annot", None) == a or
                                (abs(sn.x - arect[0]) < 2.0 and abs(sn.y - arect[1]) < 2.0)
                                for sn in session.sticky_notes.get(p, [])
                            ):
                                continue
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_note",
                                    category=self.CATEGORY_NOTES,
                                    title=content[:26] + ("…" if len(content) > 26 else "") if content else "Sticky Note",
                                    subtitle="Sticky Note",
                                    page_number=p,
                                    icon_name="dialog-information-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype == 15:  # Ink
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_ink",
                                    category=self.CATEGORY_PEN,
                                    title="PDF Ink / Drawing",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="document-edit-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype in (4, 13):  # Square
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_shape",
                                    category=self.CATEGORY_SHAPES,
                                    title="PDF Rectangle",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="checkbox-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype in (5, 14):  # Circle
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_shape",
                                    category=self.CATEGORY_SHAPES,
                                    title="PDF Ellipse",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="media-record-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        elif atype == 25:  # Stamp
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_stamp",
                                    category="other",
                                    title=f"Stamp: {content}" if content else "PDF Stamp",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="emblem-documents-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
                        else:
                            items.append(
                                AnnotationListItem(
                                    item_id=f"native_{p}_{idx}",
                                    item_type="native_annot",
                                    category="other",
                                    title=f"Annotation ({a.type[1]})",
                                    subtitle=_("badge_page_fmt").format(p + 1),
                                    page_number=p,
                                    icon_name="dialog-information-symbolic",
                                    target_obj=None,
                                    bbox=arect,
                                    native_annot=a,
                                )
                            )
            except Exception:
                pass

        # Populate Gio.ListStore
        for it in items:
            self.list_store.append(it)

        self._update_empty_state_and_count()
