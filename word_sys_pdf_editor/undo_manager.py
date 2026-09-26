import copy
import re
try:
    import pymupdf as fitz
except ImportError:
    import fitz
from . import pdf_handler
from .models import EditableText, EditableShape, EditableStroke, EditableImage
from .i18n import _

def _perform_ghost_erasure(window, target_object, page_num, properties_to_clear=None):
    """Redact original object from snapshot and protect intersecting objects from collateral deletion."""
    if getattr(target_object, 'is_new', True) or getattr(target_object, '_ghost_redacted', False):
        return

    pdf_handler.restore_page_from_snapshot(window.doc, page_num)

    props = properties_to_clear or {}
    orig_bbox = props.get('bbox', getattr(target_object, 'original_bbox', target_object.bbox))
    rot = props.get('rotation', getattr(target_object, 'rotation', 0.0))

    if isinstance(target_object, (EditableShape, EditableStroke)):
        sw = props.get('stroke_width', getattr(target_object, 'stroke_width', 2.0))
        pad = max(sw / 2.0 + 1.5, 2.0)
        x0, y0, x1, y1 = orig_bbox
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    elif isinstance(target_object, EditableImage):
        x0, y0, x1, y1 = orig_bbox
        redact_rect = fitz.Rect(x0 - 1.0, y0 - 1.0, x1 + 1.0, y1 + 1.0)
    else:
        redact_rect = fitz.Rect(orig_bbox)

    cx = (orig_bbox[0] + orig_bbox[2]) / 2.0
    cy = (orig_bbox[1] + orig_bbox[3]) / 2.0
    mat = pdf_handler.get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None

    applied_rects = []
    if mat:
        applied_rects.append((redact_rect.quad * mat).rect)
    else:
        applied_rects.append(redact_rect)

    try:
        page = window.doc.load_page(page_num)

        # Underline strip check for text
        strip_rects = []
        is_underlined = False
        if isinstance(target_object, EditableText):
            is_underlined = (
                getattr(target_object, 'is_underline', False)
                or props.get('is_underline', False)
                or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', getattr(target_object, 'text', '')))
                or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', props.get('text', '')))
            )
            x0, y0, x1, y1 = orig_bbox
            baseline = props.get('baseline', getattr(target_object, 'original_baseline', getattr(target_object, 'baseline', y1)))
            
            if not is_underlined:
                strip_test = fitz.Rect(x0 - 2.0, baseline - 1.0, x1 + 2.0, baseline + 3.0)
                strip_test_rect = (strip_test.quad * mat).rect if mat else strip_test
                try:
                    for d in page.get_drawings():
                        d_rect = d.get('rect')
                        if d_rect and d_rect.intersects(strip_test_rect) and d_rect.height <= 3.5:
                            overlap = min(d_rect.x1, strip_test_rect.x1) - max(d_rect.x0, strip_test_rect.x0)
                            if overlap >= min(4.0, (x1 - x0) * 0.4):
                                is_underlined = True
                                break
                except Exception:
                    pass

            if is_underlined:
                text_val = props.get('text', getattr(target_object, 'text', ''))
                lines = text_val.split('\n')
                font_sz = props.get('font_size', getattr(target_object, 'font_size', 12.0))
                line_height = font_sz * 1.2
                for i in range(len(lines)):
                    s_rect = fitz.Rect(x0 - 2.0, baseline + (i * line_height) - 1.0, x1 + 2.0, baseline + (i * line_height) + 4.0)
                    strip_rects.append(s_rect)
                    if mat:
                        applied_rects.append((s_rect.quad * mat).rect)
                    else:
                        applied_rects.append(s_rect)

        # Check ALL other objects on page for intersection with target's redactions
        all_other = []
        all_other += [t for t in getattr(window, 'editable_texts', []) if t is not target_object and getattr(t, 'page_number', None) == page_num]
        all_other += [s for s in getattr(window, 'editable_shapes', []) if s is not target_object and getattr(s, 'page_number', None) == page_num]
        all_other += [st for st in getattr(window, 'editable_strokes', []) if st is not target_object and getattr(st, 'page_number', None) == page_num]
        all_other += [im for im in getattr(window, 'editable_images', []) if im is not target_object and getattr(im, 'page_number', None) == page_num]

        intersecting_others = []
        for other in all_other:
            if hasattr(other, 'bbox') and other.bbox:
                ox0, oy0, ox1, oy1 = other.bbox
                opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0) if isinstance(other, (EditableShape, EditableStroke)) else 0.5
                other_rect = fitz.Rect(ox0 - opad, oy0 - opad, ox1 + opad, oy1 + opad)
                orot = getattr(other, 'rotation', 0.0)
                if orot != 0.0:
                    ocx = (ox0 + ox1) / 2.0
                    ocy = (oy0 + oy1) / 2.0
                    omat = pdf_handler.get_rotation_matrix(ocx, ocy, orot)
                    other_rect = (other_rect.quad * omat).rect
                for ar in applied_rects:
                    if ar.intersects(other_rect):
                        other._ghost_redacted = True
                        intersecting_others.append(other)
                        break

        # Apply redaction for target_object
        if mat:
            page.add_redact_annot(redact_rect.quad * mat)
        else:
            page.add_redact_annot(redact_rect)

        # Also add redactions for any intersecting objects so their entire original ghost is cleanly removed
        for other in intersecting_others:
            if hasattr(other, 'bbox') and other.bbox:
                ox0, oy0, ox1, oy1 = other.bbox
                opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0) if isinstance(other, (EditableShape, EditableStroke)) else 0.5
                o_rect = fitz.Rect(ox0 - opad, oy0 - opad, ox1 + opad, oy1 + opad)
                orot = getattr(other, 'rotation', 0.0)
                if orot != 0.0:
                    ocx = (ox0 + ox1) / 2.0
                    ocy = (oy0 + oy1) / 2.0
                    omat = pdf_handler.get_rotation_matrix(ocx, ocy, orot)
                    page.add_redact_annot(o_rect.quad * omat)
                else:
                    page.add_redact_annot(o_rect)

        # Execute redactions
        has_images = isinstance(target_object, EditableImage) or any(isinstance(o, EditableImage) for o in intersecting_others)
        has_graphics = isinstance(target_object, (EditableShape, EditableStroke)) or bool(strip_rects) or any(isinstance(o, (EditableShape, EditableStroke)) for o in intersecting_others)

        img_param = fitz.PDF_REDACT_IMAGE_REMOVE if has_images else fitz.PDF_REDACT_IMAGE_NONE
        gfx_param = 2 if has_graphics else 0
        try:
            page.apply_redactions(images=img_param, graphics=gfx_param, text=0)
        except Exception:
            page.apply_redactions()

        # Underline strip redaction if needed
        if strip_rects:
            for s_rect in strip_rects:
                if mat:
                    page.add_redact_annot(s_rect.quad * mat)
                else:
                    page.add_redact_annot(s_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except Exception:
                pass

        # Clean old links
        try:
            for link in list(page.get_links()):
                link_rect = fitz.Rect(link.get('from', (0, 0, 0, 0)))
                for ar in applied_rects:
                    if link_rect.intersects(ar):
                        page.delete_link(link)
                        break
        except Exception as link_err:
            print(f"Warning: could not delete old link: {link_err}")

        window.doc.load_page(page_num)
        pdf_handler.save_page_snapshot(window.doc, page_num, force=True)
        pdf_handler.invalidate_page_cache(window.doc, page_num)
        target_object._ghost_redacted = True
    except Exception as e:
        print(f"Warning: could not erase ghost from snapshot for page {page_num}: {e}")

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
        _perform_ghost_erasure(self.window, target_object, page_num)

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
        _perform_ghost_erasure(self.window, self.target_object, page_num, properties_to_clear)

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
        temp_obj_for_pdf.original_bbox = properties_to_clear.get('bbox', getattr(self.target_object, 'original_bbox', temp_obj_for_pdf.bbox))
        
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
        if success:
            self.target_object.is_baked = True
            self.target_object._ghost_redacted = True
            if page_num_fallback is not None:
                self.window._refresh_thumbnail(page_num_fallback)
        else:
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

    def execute(self):
        """Rotate page by angle_delta degrees and update display."""
        success, _res = pdf_handler.rotate_page(self.window.doc, self.page_index, self.angle_delta)
        if success:
            self._apply_rotation_ui()

    def undo(self):
        """Revert page rotation by -angle_delta degrees and update display."""
        success, _res = pdf_handler.rotate_page(self.window.doc, self.page_index, -self.angle_delta)
        if success:
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
        if getattr(self.window, 'selected_text', None) == self.target_object:
            self.window.pending_format_change_obj = self.target_object
            self.window.before_format_change_state = copy.deepcopy(self.target_object.__dict__)
            if hasattr(self.window, '_update_text_format_controls'):
                self.window._update_text_format_controls(self.target_object)
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