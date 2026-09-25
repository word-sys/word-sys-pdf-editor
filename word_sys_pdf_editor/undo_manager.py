import copy
import re
try:
    import pymupdf as fitz
except ImportError:
    import fitz
from . import pdf_handler
from .models import EditableText, EditableShape, EditableStroke, EditableImage
from .i18n import _

class Command:
    """Base class for undoable/redoable actions."""
    def __init__(self, window):
        """Initialise command with parent window context."""
        self.window = window

    def execute(self):
        """Execute the command."""
        raise NotImplementedError

    def undo(self):
        """Undo the command."""
        raise NotImplementedError

    def _erase_ghost_if_needed(self, target_object, page_num):
        """Redact original object from snapshot if edited/moved."""
        if getattr(target_object, 'is_new', True) or getattr(target_object, '_ghost_redacted', False):
            return
            
        pdf_handler.restore_page_from_snapshot(self.window.doc, page_num)
        
        orig_bbox = getattr(target_object, 'original_bbox', target_object.bbox)
        if isinstance(target_object, (EditableShape, EditableStroke)):
            pad = max(getattr(target_object, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
            x0, y0, x1, y1 = orig_bbox
            redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        else:
            redact_rect = fitz.Rect(orig_bbox)
        try:
            page = self.window.doc.load_page(page_num)
            page.add_redact_annot(redact_rect)
            
            if isinstance(target_object, EditableText):
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)

                # If text has underline or links, redact vector underline lines cleanly
                is_underlined = (
                    getattr(target_object, 'is_underline', False)
                    or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', getattr(target_object, 'text', '')))
                )
                x0, y0, x1, y1 = orig_bbox
                baseline = getattr(target_object, 'baseline', y1)
                
                if not is_underlined:
                    strip_test = fitz.Rect(x0, baseline - 1.0, x1, baseline + 3.0)
                    try:
                        for d in page.get_drawings():
                            d_rect = d.get('rect')
                            if d_rect and d_rect.intersects(strip_test) and d_rect.height <= 3.5:
                                overlap = min(d_rect.x1, x1) - max(d_rect.x0, x0)
                                if overlap >= min(4.0, (x1 - x0) * 0.4):
                                    is_underlined = True
                                    break
                    except Exception:
                        pass
                        
                if is_underlined:
                    lines = getattr(target_object, 'text', '').split('\n')
                    line_height = getattr(target_object, 'font_size', 12.0) * 1.2
                    for i in range(len(lines)):
                        strip_rect = fitz.Rect(x0, baseline + (i * line_height) - 0.5, x1, baseline + (i * line_height) + 3.0)
                        page.add_redact_annot(strip_rect)
                    try:
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
                    except Exception:
                        pass
                    
                    try:
                        for link in list(page.get_links()):
                            if fitz.Rect(link.get('from', (0, 0, 0, 0))).intersects(fitz.Rect(orig_bbox)):
                                page.delete_link(link)
                    except Exception as link_err:
                        print(f"Warning: could not delete old link: {link_err}")
            elif isinstance(target_object, EditableImage):
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=1)
            else:
                try:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
                except TypeError:
                    try:
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=True)
                    except Exception:
                        page.apply_redactions()

                # If redacting graphics, any intersecting shapes or strokes must be re-applied on rebuild
                redact_fitz = fitz.Rect(redact_rect)
                other_objs = [o for o in getattr(self.window, 'editable_shapes', []) if o is not target_object]
                other_objs += [s for s in getattr(self.window, 'editable_strokes', []) if s is not target_object]
                for other in other_objs:
                    if hasattr(other, 'bbox') and other.bbox:
                        ox0, oy0, ox1, oy1 = other.bbox
                        opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0)
                        other_rect = fitz.Rect(ox0 - opad, oy0 - opad, ox1 + opad, oy1 + opad)
                        if redact_fitz.intersects(other_rect):
                            other._ghost_redacted = True
                    
            self.window.doc.load_page(page_num)
            pdf_handler.save_page_snapshot(self.window.doc, page_num, force=True)
            pdf_handler.invalidate_page_cache(self.window.doc, page_num)
            target_object._ghost_redacted = True
        except Exception as e:
            print(f"Warning: could not erase ghost from snapshot for page {page_num}: {e}")

class UndoManager:
    """Manager class that stores undo and redo action stacks."""
    def __init__(self, window):
        """Initialise undo and redo stacks."""
        self.window = window
        self.undo_stack = []
        self.redo_stack = []
        self._update_ui_callback = self.window._update_undo_redo_buttons

    def add_command(self, command):
        """Add a command to the undo stack and clear redo stack."""
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self._update_ui_callback()

    def undo(self):
        """Undo the command."""
        if not self.undo_stack:
            return
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        self._update_ui_callback()
        self.window.pdf_view.queue_draw()

    def redo(self):
        """Redo the command."""
        if not self.redo_stack:
            return
        command = self.redo_stack.pop()
        command.execute()
        self.undo_stack.append(command)
        self._update_ui_callback()
        self.window.pdf_view.queue_draw()

    def clear(self):
        """Clear the items."""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._update_ui_callback()

class EditObjectCommand(Command):
    """The EditObjectCommand class."""
    def __init__(self, window, target_object, old_properties, new_properties):
        """Initialize the EditObjectCommand."""
        super().__init__(window)
        self.target_object = target_object
        self.old_properties = old_properties
        self.new_properties = new_properties

    def _erase_ghost_if_needed(self, page_num, properties_to_clear):
        """Erase ghost if needed."""
        if getattr(self.target_object, 'is_new', True) or getattr(self.target_object, '_ghost_redacted', False):
            return
            
        pdf_handler.restore_page_from_snapshot(self.window.doc, page_num)
        
        orig_bbox = properties_to_clear.get('bbox', getattr(self.target_object, 'original_bbox', self.target_object.bbox))
        if isinstance(self.target_object, (EditableShape, EditableStroke)):
            pad = max(getattr(self.target_object, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
            x0, y0, x1, y1 = orig_bbox
            redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        else:
            redact_rect = fitz.Rect(orig_bbox)
        try:
            page = self.window.doc.load_page(page_num)
            page.add_redact_annot(redact_rect)
            
            if isinstance(self.target_object, EditableText):
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)

                # If text has underline or links, redact vector underline lines cleanly
                is_underlined = (
                    getattr(self.target_object, 'is_underline', False)
                    or properties_to_clear.get('is_underline', False)
                    or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', getattr(self.target_object, 'text', '')))
                    or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', properties_to_clear.get('text', '')))
                )
                x0, y0, x1, y1 = orig_bbox
                baseline = getattr(self.target_object, 'baseline', y1)
                
                if not is_underlined:
                    strip_test = fitz.Rect(x0, baseline - 1.0, x1, baseline + 3.0)
                    try:
                        for d in page.get_drawings():
                            d_rect = d.get('rect')
                            if d_rect and d_rect.intersects(strip_test) and d_rect.height <= 3.5:
                                overlap = min(d_rect.x1, x1) - max(d_rect.x0, x0)
                                if overlap >= min(4.0, (x1 - x0) * 0.4):
                                    is_underlined = True
                                    break
                    except Exception:
                        pass
                        
                if is_underlined:
                    text_val = properties_to_clear.get('text', getattr(self.target_object, 'text', ''))
                    lines = text_val.split('\n')
                    line_height = getattr(self.target_object, 'font_size', 12.0) * 1.2
                    for i in range(len(lines)):
                        strip_rect = fitz.Rect(x0, baseline + (i * line_height) - 0.5, x1, baseline + (i * line_height) + 3.0)
                        page.add_redact_annot(strip_rect)
                    try:
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
                    except Exception:
                        pass
                    
                    try:
                        for link in list(page.get_links()):
                            if fitz.Rect(link.get('from', (0, 0, 0, 0))).intersects(fitz.Rect(orig_bbox)):
                                page.delete_link(link)
                    except Exception as link_err:
                        print(f"Warning: could not delete old link: {link_err}")
            elif isinstance(self.target_object, EditableImage):
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=1)
            else:
                try:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
                except TypeError:
                    try:
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=True)
                    except Exception:
                        page.apply_redactions()

                # If redacting graphics, any intersecting shapes or strokes must be re-applied on rebuild
                redact_fitz = fitz.Rect(redact_rect)
                other_objs = [o for o in getattr(self.window, 'editable_shapes', []) if o is not self.target_object]
                other_objs += [s for s in getattr(self.window, 'editable_strokes', []) if s is not self.target_object]
                for other in other_objs:
                    if hasattr(other, 'bbox') and other.bbox:
                        ox0, oy0, ox1, oy1 = other.bbox
                        opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0)
                        other_rect = fitz.Rect(ox0 - opad, oy0 - opad, ox1 + opad, oy1 + opad)
                        if redact_fitz.intersects(other_rect):
                            other._ghost_redacted = True
                    
            self.window.doc.load_page(page_num)
            pdf_handler.save_page_snapshot(self.window.doc, page_num, force=True)
            pdf_handler.invalidate_page_cache(self.window.doc, page_num)
            self.target_object._ghost_redacted = True
        except Exception as e:
            print(f"Warning: could not erase ghost from snapshot for page {page_num}: {e}")

    def _apply_properties_to_pdf(self, properties_to_apply, properties_to_clear):
        """Apply properties to PDF."""
        page_num = getattr(self.target_object, 'page_number', None)
        if page_num is not None:
            self._erase_ghost_if_needed(page_num, properties_to_clear)
            
        strokes = getattr(self.window, 'editable_strokes', [])
        if isinstance(self.target_object, EditableStroke):
            temp_obj = copy.deepcopy(self.target_object)
            temp_obj.__dict__.update(copy.deepcopy(properties_to_apply))
            temp_obj.original_bbox = properties_to_clear.get('bbox', temp_obj.bbox)
            if page_num is not None:
                pdf_handler.rebuild_page(
                    self.window.doc, page_num,
                    self.window.editable_texts,
                    self.window.editable_shapes,
                    self.window.editable_images,
                    exclude_obj=self.target_object,
                    all_strokes=strokes
                )
            success, msg = pdf_handler.apply_object_edit(self.window.doc, temp_obj)
            if success:
                self.target_object.is_baked = True
                self.target_object._ghost_redacted = True
                if page_num is not None:
                    self.window._refresh_thumbnail(page_num)
            else:
                from .ui_components import show_error_dialog
                show_error_dialog(self.window, _("err_during_op", msg))
            return success

        if isinstance(self.target_object, EditableShape):
            temp_obj = copy.deepcopy(self.target_object)
            temp_obj.__dict__.update(copy.deepcopy(properties_to_apply))
            temp_obj.original_bbox = properties_to_clear['bbox']
            if page_num is not None:
                pdf_handler.rebuild_page(
                    self.window.doc, page_num,
                    self.window.editable_texts,
                    self.window.editable_shapes,
                    self.window.editable_images,
                    exclude_obj=self.target_object,
                    all_strokes=strokes
                )
            success, msg = pdf_handler.apply_object_edit(self.window.doc, temp_obj)
            if success:
                self.target_object.is_baked = True
                self.target_object._ghost_redacted = True
                if page_num is not None:
                    self.window._refresh_thumbnail(page_num)
            else:
                from .ui_components import show_error_dialog
                show_error_dialog(self.window, _("err_moving_shape", msg))
            return success
            
        temp_obj_for_pdf = copy.deepcopy(self.target_object)
        temp_obj_for_pdf.__dict__.update(copy.deepcopy(properties_to_apply))
        temp_obj_for_pdf.original_bbox = properties_to_clear['bbox']
        
        page_num_fallback = getattr(self.target_object, 'page_number', None)
        if page_num_fallback is not None:
            pdf_handler.rebuild_page(
                self.window.doc, page_num_fallback,
                self.window.editable_texts,
                self.window.editable_shapes,
                self.window.editable_images,
                exclude_obj=self.target_object,
                all_strokes=strokes
            )
        
        success, msg = pdf_handler.apply_object_edit(self.window.doc, temp_obj_for_pdf)
        
        if not success:
            from .ui_components import show_error_dialog
            show_error_dialog(self.window, _("err_during_op", msg))
        
        return success

    def _update_live_object(self, properties_to_apply):
        """Update live object."""
        self.target_object.__dict__.update(copy.deepcopy(properties_to_apply))
        self.target_object.original_bbox = self.target_object.bbox
        self.target_object.modified = False
        self.window.document_modified = True
        if not isinstance(self.target_object, EditableShape):
            page_num = getattr(self.target_object, 'page_number', None)
            if page_num is not None:
                self.window._refresh_thumbnail(page_num)

    def execute(self):
        """Execute the command."""
        if self._apply_properties_to_pdf(self.new_properties, self.old_properties):
            self._update_live_object(self.new_properties)
            self.window.status_label.set_text(_("change_applied"))
            self.window.pdf_view.queue_draw()

    def undo(self):
        """Undo the command."""
        if self._apply_properties_to_pdf(self.old_properties, self.new_properties):
            self._update_live_object(self.old_properties)
            self.window.status_label.set_text(_("reverted"))
            self.window.pdf_view.queue_draw()

class AddObjectCommand(Command):
    """The AddObjectCommand class."""
    def __init__(self, window, new_object):
        """Initialize the AddObjectCommand."""
        super().__init__(window)
        self.new_object = new_object
        self.is_text = isinstance(new_object, EditableText)
        self.is_shape = isinstance(new_object, EditableShape)
        self.is_stroke = isinstance(new_object, EditableStroke)
        self.is_image = not (self.is_text or self.is_shape or self.is_stroke)

    def _refresh_thumb(self):
        """Refresh thumb."""
        page_num = getattr(self.new_object, 'page_number', None)
        if page_num is not None:
            self.window._refresh_thumbnail(page_num)

    def execute(self):
        """Execute the command."""
        if self.is_text:
            if self.new_object not in self.window.editable_texts:
                self.window.editable_texts.append(self.new_object)
        elif self.is_shape:
            if self.new_object not in self.window.editable_shapes:
                self.window.editable_shapes.append(self.new_object)
        elif self.is_stroke:
            if not hasattr(self.window, 'editable_strokes'):
                self.window.editable_strokes = []
            if self.new_object not in self.window.editable_strokes:
                self.window.editable_strokes.append(self.new_object)
        else:
            if self.new_object not in self.window.editable_images:
                self.window.editable_images.append(self.new_object)
                
        self.new_object.is_baked = True
        page_num = getattr(self.new_object, 'page_number', self.window.current_page_index)
        strokes = getattr(self.window, 'editable_strokes', [])
        pdf_handler.rebuild_page(
            self.window.doc, page_num,
            self.window.editable_texts,
            self.window.editable_shapes,
            self.window.editable_images,
            all_strokes=strokes
        )
        self._refresh_thumb()

        self.window.document_modified = True
        self.window.status_label.set_text(_("object_added"))
        self.window._update_ui_state()
        self.window.pdf_view.queue_draw()

    def undo(self):
        """Undo the command."""
        if self.is_text and self.new_object in self.window.editable_texts:
            self.window.editable_texts.remove(self.new_object)
        elif self.is_shape and self.new_object in self.window.editable_shapes:
            self.window.editable_shapes.remove(self.new_object)
        elif self.is_stroke and hasattr(self.window, 'editable_strokes') and self.new_object in self.window.editable_strokes:
            self.window.editable_strokes.remove(self.new_object)
        elif self.is_image and self.new_object in self.window.editable_images:
            self.window.editable_images.remove(self.new_object)

        page_num = getattr(self.new_object, 'page_number', self.window.current_page_index)
        strokes = getattr(self.window, 'editable_strokes', [])
        pdf_handler.rebuild_page(
            self.window.doc, page_num,
            self.window.editable_texts,
            self.window.editable_shapes,
            self.window.editable_images,
            all_strokes=strokes
        )

        self.window.document_modified = True
        self.window.status_label.set_text(_("reverted"))
        self.window._refresh_thumbnail(page_num)
        self.window.pdf_view.queue_draw()



class DeleteObjectCommand(Command):
    """The DeleteObjectCommand class."""
    def __init__(self, window, deleted_object):
        """Initialize the DeleteObjectCommand."""
        super().__init__(window)
        self.deleted_object = deleted_object
        self.is_text = isinstance(deleted_object, EditableText)
        self.is_shape = isinstance(deleted_object, EditableShape)
        self.is_stroke = isinstance(deleted_object, EditableStroke)

    def execute(self):
        """Execute the command."""
        if self.is_text and self.deleted_object in self.window.editable_texts:
            self.window.editable_texts.remove(self.deleted_object)
        elif self.is_shape and self.deleted_object in self.window.editable_shapes:
            self.window.editable_shapes.remove(self.deleted_object)
        elif self.is_stroke and hasattr(self.window, 'editable_strokes') and self.deleted_object in self.window.editable_strokes:
            self.window.editable_strokes.remove(self.deleted_object)
        elif not self.is_text and not self.is_shape and not self.is_stroke and self.deleted_object in self.window.editable_images:
            self.window.editable_images.remove(self.deleted_object)

        page_num = getattr(self.deleted_object, 'page_number', self.window.current_page_index)
        if page_num is not None:
            self._erase_ghost_if_needed(self.deleted_object, page_num)
            
        strokes = getattr(self.window, 'editable_strokes', [])
        pdf_handler.rebuild_page(
            self.window.doc, page_num,
            self.window.editable_texts,
            self.window.editable_shapes,
            self.window.editable_images,
            all_strokes=strokes
        )

        self.window.document_modified = True
        self.window.status_label.set_text(_("object_deleted"))
        self.window._refresh_thumbnail(page_num)
        self.window.pdf_view.queue_draw()

    def undo(self):
        """Undo the command."""
        if self.is_text and self.deleted_object not in self.window.editable_texts:
            self.window.editable_texts.append(self.deleted_object)
        elif self.is_shape and self.deleted_object not in self.window.editable_shapes:
            self.window.editable_shapes.append(self.deleted_object)
        elif self.is_stroke:
            if not hasattr(self.window, 'editable_strokes'):
                self.window.editable_strokes = []
            if self.deleted_object not in self.window.editable_strokes:
                self.window.editable_strokes.append(self.deleted_object)
        elif not self.is_text and not self.is_shape and not self.is_stroke and self.deleted_object not in self.window.editable_images:
            self.window.editable_images.append(self.deleted_object)

        page_num = getattr(self.deleted_object, 'page_number', self.window.current_page_index)
        strokes = getattr(self.window, 'editable_strokes', [])
        pdf_handler.rebuild_page(
            self.window.doc, page_num,
            self.window.editable_texts,
            self.window.editable_shapes,
            self.window.editable_images,
            all_strokes=strokes
        )

        self.window.document_modified = True
        self.window.status_label.set_text(_("delete_reverted"))
        self.window._refresh_thumbnail(page_num)
        self.window.pdf_view.queue_draw()

class CompositeCommand(Command):
    """The CompositeCommand class."""
    def __init__(self, window, commands):
        """Initialize the CompositeCommand."""
        super().__init__(window)
        self.commands = commands
        
    def execute(self):
        """Execute the command."""
        for command in self.commands:
            command.execute()
            
    def undo(self):
        """Undo the command."""
        for command in reversed(self.commands):
            command.undo()

class RotatePageCommand(Command):
    """Command to rotate a page 90 degrees clockwise or counterclockwise with undo/redo."""
    def __init__(self, window, page_index: int, angle_delta: int):
        super().__init__(window)
        self.page_index = page_index
        self.angle_delta = angle_delta

    def _get_page_dims(self):
        try:
            page = self.window.doc.load_page(self.page_index)
            return float(page.rect.width), float(page.rect.height)
        except Exception:
            return 595.0, 842.0

    def _transform_objects(self, old_w: float, old_h: float, angle_delta: int):
        """Rotate all objects on this page to match the new page orientation."""
        from .pdf_handler import transform_point_page_rot, transform_bbox_page_rot

        # 1. Texts
        for t in getattr(self.window, 'editable_texts', []):
            if getattr(t, 'page_number', -1) == self.page_index:
                if t.bbox:
                    new_bbox = transform_bbox_page_rot(t.bbox, old_w, old_h, angle_delta)
                    t.bbox = new_bbox
                    t.x = new_bbox[0]
                    t.y = new_bbox[1]
                    t.baseline = new_bbox[1] + (new_bbox[3] - new_bbox[1]) * 0.8
                t.rotation = (getattr(t, 'rotation', 0.0) + angle_delta) % 360.0
                if hasattr(t, 'original_bbox') and t.original_bbox:
                    t.original_bbox = transform_bbox_page_rot(t.original_bbox, old_w, old_h, angle_delta)

        # 2. Images
        for img in getattr(self.window, 'editable_images', []):
            if getattr(img, 'page_number', -1) == self.page_index:
                if img.bbox:
                    img.bbox = transform_bbox_page_rot(img.bbox, old_w, old_h, angle_delta)
                img.rotation = (getattr(img, 'rotation', 0.0) + angle_delta) % 360.0
                if hasattr(img, 'original_bbox') and img.original_bbox:
                    img.original_bbox = transform_bbox_page_rot(img.original_bbox, old_w, old_h, angle_delta)

        # 3. Shapes
        for s in getattr(self.window, 'editable_shapes', []):
            if getattr(s, 'page_number', -1) == self.page_index:
                if s.bbox:
                    s.bbox = transform_bbox_page_rot(s.bbox, old_w, old_h, angle_delta)
                s.rotation = (getattr(s, 'rotation', 0.0) + angle_delta) % 360.0
                if hasattr(s, 'original_bbox') and s.original_bbox:
                    s.original_bbox = transform_bbox_page_rot(s.original_bbox, old_w, old_h, angle_delta)

        # 4. Strokes
        for st in getattr(self.window, 'editable_strokes', []):
            if getattr(st, 'page_number', -1) == self.page_index:
                if st.points:
                    st.points = [transform_point_page_rot(px, py, old_w, old_h, angle_delta) for (px, py) in st.points]
                if getattr(st, 'bbox', None):
                    st.bbox = transform_bbox_page_rot(st.bbox, old_w, old_h, angle_delta)
                st.rotation = (getattr(st, 'rotation', 0.0) + angle_delta) % 360.0
                if hasattr(st, 'original_bbox') and st.original_bbox:
                    st.original_bbox = transform_bbox_page_rot(st.original_bbox, old_w, old_h, angle_delta)

    def execute(self):
        """Rotate page by angle_delta degrees and update display."""
        old_w, old_h = self._get_page_dims()
        success, _res = pdf_handler.rotate_page(self.window.doc, self.page_index, self.angle_delta)
        if success:
            self._transform_objects(old_w, old_h, self.angle_delta)
            self._apply_rotation_ui()

    def undo(self):
        """Revert page rotation by -angle_delta degrees and update display."""
        old_w, old_h = self._get_page_dims()
        success, _res = pdf_handler.rotate_page(self.window.doc, self.page_index, -self.angle_delta)
        if success:
            self._transform_objects(old_w, old_h, -self.angle_delta)
            self._apply_rotation_ui()

    def _apply_rotation_ui(self):
        self.window.document_modified = True
        if hasattr(self.window, '_refresh_thumbnail'):
            self.window._refresh_thumbnail(self.page_index)
        if hasattr(self.window, 'current_page_index') and self.window.current_page_index == self.page_index:
            try:
                page = self.window.doc.load_page(self.page_index)
                zoom = getattr(self.window, 'zoom_level', 1.0)
                self.window.current_pdf_page_width = int(page.rect.width * zoom)
                self.window.current_pdf_page_height = int(page.rect.height * zoom)
                if hasattr(self.window, 'pdf_view'):
                    self.window.pdf_view.set_content_width(self.window.current_pdf_page_width)
                    self.window.pdf_view.set_content_height(self.window.current_pdf_page_height)
            except Exception as e:
                print(f"Warning updating page dimensions on rotation: {e}")
            if hasattr(self.window, '_update_rotation_controls'):
                selected_obj = getattr(self.window, 'get_selected_object', lambda: None)()
                self.window._update_rotation_controls(selected_obj)
            if hasattr(self.window, 'pdf_view'):
                self.window.pdf_view.queue_draw()
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()

class RotateObjectCommand(Command):
    """Command to rotate an object (text, image, shape, stroke) with full undo/redo."""
    def __init__(self, window, target_object, old_rotation: float, new_rotation: float):
        super().__init__(window)
        self.target_object = target_object
        self.old_rotation = float(old_rotation) % 360.0
        self.new_rotation = float(new_rotation) % 360.0

    def _apply_rotation(self, angle: float):
        """Bake the rotation into the PDF page and update live object and UI."""
        if hasattr(self.target_object, 'set_rotation'):
            self.target_object.set_rotation(angle)
        else:
            self.target_object.rotation = float(angle) % 360.0

        page_num = getattr(self.target_object, 'page_number', None)
        if page_num is not None and getattr(self.window, 'doc', None):
            self._erase_ghost_if_needed(self.target_object, page_num)

            strokes = getattr(self.window, 'editable_strokes', [])
            pdf_handler.rebuild_page(
                self.window.doc, page_num,
                getattr(self.window, 'editable_texts', []),
                getattr(self.window, 'editable_shapes', []),
                getattr(self.window, 'editable_images', []),
                exclude_obj=self.target_object,
                all_strokes=strokes
            )
            success, msg = pdf_handler.apply_object_edit(self.window.doc, self.target_object)
            if success:
                self.target_object.is_baked = True
                self.target_object._ghost_redacted = True
                if hasattr(self.window, '_refresh_thumbnail'):
                    self.window._refresh_thumbnail(page_num)
            else:
                from .ui_components import show_error_dialog
                show_error_dialog(self.window, _("err_during_op", msg))

        self.window.document_modified = True
        if hasattr(self.window, '_update_rotation_controls'):
            self.window._update_rotation_controls(self.target_object)
        if hasattr(self.window, '_update_ui_state'):
            self.window._update_ui_state()
        if hasattr(self.window, 'pdf_view'):
            self.window.pdf_view.queue_draw()

    def execute(self):
        """Apply new rotation angle."""
        self._apply_rotation(self.new_rotation)
        if hasattr(self.window, 'status_label') and self.window.status_label:
            self.window.status_label.set_text(_("status_object_rotation", f"{self.new_rotation:.1f}°"))

    def undo(self):
        """Revert back to old rotation angle."""
        self._apply_rotation(self.old_rotation)
        if hasattr(self.window, 'status_label') and self.window.status_label:
            self.window.status_label.set_text(_("status_object_rotation", f"{self.old_rotation:.1f}°"))