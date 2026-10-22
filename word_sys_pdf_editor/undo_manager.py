import copy
import re
from typing import Any, Optional, List, Dict, Tuple
try:
    import pymupdf as fitz
except ImportError:
    import fitz
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from . import pdf_handler
from .models import EditableText, EditableShape, EditableStroke, EditableImage, AcroFormField, MeasurementObject, StickyNoteObject
from .i18n import _

def _perform_ghost_erasure(window, target_object, page_num, properties_to_clear=None, session=None):
    """Redact original object strictly from snapshot without affecting any other objects."""
    if getattr(target_object, 'is_new', True) or getattr(target_object, '_ghost_redacted', False):
        return
    if getattr(target_object, 'is_patch', False):
        return

    from .models import DocumentSession
    sess = session if isinstance(session, DocumentSession) else None
    if sess is None:
        active = getattr(window, '_active_session', None)
        if isinstance(active, DocumentSession):
            sess = active

    if sess is not None and sess.doc is not None:
        doc = sess.doc
    else:
        doc = getattr(window, 'doc', None)

    if doc is None:
        return

    pdf_handler.restore_page_from_snapshot(doc, page_num)

    props = properties_to_clear or {}
    orig_bbox = props.get('bbox', getattr(target_object, 'original_bbox', getattr(target_object, 'bbox', None)))
    if not orig_bbox:
        return
    rot = props.get('rotation', getattr(target_object, 'original_rotation', getattr(target_object, 'rotation', 0.0)))

    if isinstance(target_object, (EditableShape, EditableStroke)):
        sw = props.get('stroke_width', getattr(target_object, 'stroke_width', 2.0))
        pad = max(sw / 2.0 + 1.5, 2.0)
        x0, y0, x1, y1 = orig_bbox
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    elif isinstance(target_object, EditableImage):
        x0, y0, x1, y1 = orig_bbox
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        w = x1 - x0
        h = y1 - y0
        if rot != 0.0:
            rad = math.radians(rot)
            nw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
            nh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
            redact_rect = fitz.Rect(cx - nw / 2.0 - 2.0, cy - nh / 2.0 - 2.0, cx + nw / 2.0 + 2.0, cy + nh / 2.0 + 2.0)
        else:
            redact_rect = fitz.Rect(x0 - 2.0, y0 - 2.0, x1 + 2.0, y1 + 2.0)
    else:
        redact_rect = fitz.Rect(orig_bbox)

    cx = (orig_bbox[0] + orig_bbox[2]) / 2.0
    cy = (orig_bbox[1] + orig_bbox[3]) / 2.0
    mat = pdf_handler.get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None

    applied_rects = []
    if mat and not isinstance(target_object, EditableImage):
        applied_rects.append((redact_rect.quad * mat).rect)
    else:
        applied_rects.append(redact_rect)

    try:
        page = doc.load_page(page_num)

        # Underline and strikethrough strip check for text
        strip_rects = []
        is_underlined = False
        is_strikethrough = False
        if isinstance(target_object, EditableText):
            is_underlined = (
                getattr(target_object, 'is_underline', False)
                or props.get('is_underline', False)
                or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', getattr(target_object, 'text', '')))
                or bool(re.search(r'(https?://[^\s]+|www\.[^\s]+)', props.get('text', '')))
            )
            is_strikethrough = (
                getattr(target_object, 'is_strikethrough', False)
                or props.get('is_strikethrough', False)
            )
            x0, y0, x1, y1 = orig_bbox
            baseline = props.get('baseline', getattr(target_object, 'original_baseline', getattr(target_object, 'baseline', y1)))
            font_sz = props.get('font_size', getattr(target_object, 'font_size', 12.0))
            line_height = font_sz * 1.2
            
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

            if not is_strikethrough:
                strike_test = fitz.Rect(x0 - 2.0, baseline - (font_sz * 0.3) - 2.0, x1 + 2.0, baseline - (font_sz * 0.3) + 2.0)
                strike_test_rect = (strike_test.quad * mat).rect if mat else strike_test
                try:
                    for d in page.get_drawings():
                        d_rect = d.get('rect')
                        if d_rect and d_rect.intersects(strike_test_rect) and d_rect.height <= 3.5:
                            overlap = min(d_rect.x1, strike_test_rect.x1) - max(d_rect.x0, strike_test_rect.x0)
                            if overlap >= min(4.0, (x1 - x0) * 0.4):
                                is_strikethrough = True
                                break
                except Exception:
                    pass

            text_val = props.get('text', getattr(target_object, 'text', ''))
            lines = text_val.split('\n')
            if is_underlined:
                for i in range(len(lines)):
                    s_rect = fitz.Rect(x0, baseline + (i * line_height) - 0.5, x1, baseline + (i * line_height) + 2.5)
                    strip_rects.append(s_rect)
                    if mat:
                        applied_rects.append((s_rect.quad * mat).rect)
                    else:
                        applied_rects.append(s_rect)

            if is_strikethrough:
                for i in range(len(lines)):
                    st_rect = fitz.Rect(x0, baseline + (i * line_height) - (font_sz * 0.3) - 1.0, x1, baseline + (i * line_height) - (font_sz * 0.3) + 1.0)
                    strip_rects.append(st_rect)
                    if mat:
                        applied_rects.append((st_rect.quad * mat).rect)
                    else:
                        applied_rects.append(st_rect)

        # Apply redaction ONLY for target_object
        if mat and not isinstance(target_object, EditableImage):
            page.add_redact_annot(redact_rect.quad * mat)
        else:
            page.add_redact_annot(redact_rect)

        # Execute redactions strictly isolated by object type
        if isinstance(target_object, EditableText):
            # Only redact text, NEVER redact graphics or images
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)

            # Clean up existing links overlapping target_object
            if hasattr(page, 'get_links'):
                for lk in page.get_links():
                    l_rect = lk.get('from')
                    if l_rect and (redact_rect.intersects(l_rect) or redact_rect.contains(l_rect) or l_rect.contains(redact_rect)):
                        try:
                            page.delete_link(lk)
                        except Exception:
                            pass

            # If underline strip exists, redact only vector graphics for the strip, NEVER text
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

            # Check other EditableText on the same page ONLY if PyMuPDF physically destroyed its text
            active_texts = (getattr(sess, 'editable_texts', None) if sess else getattr(window, 'editable_texts', [])) or []
            for other in active_texts:
                if other is not target_object and getattr(other, 'page_number', None) == page_num:
                    if getattr(other, '_ghost_redacted', False):
                        continue
                    if hasattr(other, 'bbox') and other.bbox:
                        ox0, oy0, ox1, oy1 = other.bbox
                        other_rect = fitz.Rect(ox0 - 0.5, oy0 - 0.5, ox1 + 0.5, oy1 + 0.5)
                        orot = getattr(other, 'original_rotation', getattr(other, 'rotation', 0.0))
                        if orot != 0.0:
                            ocx = (ox0 + ox1) / 2.0
                            ocy = (oy0 + oy1) / 2.0
                            omat = pdf_handler.get_rotation_matrix(ocx, ocy, orot)
                            other_rect = (other_rect.quad * omat).rect
                        intersects_any = any(ar.intersects(other_rect) for ar in applied_rects)
                        if intersects_any:
                            expected_text = getattr(other, 'original_text', getattr(other, 'text', '')).strip()
                            if expected_text:
                                clip_text = page.get_text("text", clip=other_rect).strip()
                                norm_expected = "".join(expected_text.split())
                                norm_clip = "".join(clip_text.split())
                                if norm_expected not in norm_clip:
                                    other._ghost_redacted = True

        elif isinstance(target_object, (EditableShape, EditableStroke)):
            # Only redact vector graphics, NEVER redact text or images (text=1 preserves text!)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except Exception:
                page.apply_redactions()

            # Check ONLY other shapes and strokes for vector clipping
            active_shapes = getattr(sess, 'editable_shapes', None) if sess else getattr(window, 'editable_shapes', [])
            active_strokes = getattr(sess, 'editable_strokes', None) if sess else getattr(window, 'editable_strokes', [])
            other_graphics = [s for s in active_shapes if s is not target_object and getattr(s, 'page_number', None) == page_num]
            other_graphics += [st for st in active_strokes if st is not target_object and getattr(st, 'page_number', None) == page_num]
            for other in other_graphics:
                if hasattr(other, 'bbox') and other.bbox:
                    ox0, oy0, ox1, oy1 = other.bbox
                    opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0)
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
                            break

        elif isinstance(target_object, EditableImage):
            # Only redact image, NEVER redact text or graphics
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=1)
            except TypeError:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)

            active_images = getattr(sess, 'editable_images', None) if sess else getattr(window, 'editable_images', [])
            for other in active_images:
                if other is not target_object and getattr(other, 'page_number', None) == page_num:
                    if hasattr(other, 'bbox') and other.bbox:
                        other_rect = fitz.Rect(other.bbox)
                        for ar in applied_rects:
                            if ar.intersects(other_rect):
                                other._ghost_redacted = True
                                break

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

        doc.load_page(page_num)
        pdf_handler.save_page_snapshot(doc, page_num, force=True)
        pdf_handler.invalidate_page_cache(doc, page_num)
        target_object._ghost_redacted = True
    except Exception as e:
        print(f"Warning: could not erase ghost from snapshot for page {page_num}: {e}")

class Command:
    """Base class for undoable/redoable actions."""
    def __init__(self, window):
        """Initialise command with parent window context."""
        from .models import DocumentSession
        self.window = window
        active = getattr(window, '_active_session', None)
        self.session = active if isinstance(active, DocumentSession) else None

    def _get_target_session(self):
        from .models import DocumentSession
        if isinstance(self.session, DocumentSession):
            return self.session
        active = getattr(self.window, '_active_session', None)
        if isinstance(active, DocumentSession):
            return active
        return None

    def _get_doc(self):
        sess = self._get_target_session()
        if sess is not None and sess.doc is not None:
            return sess.doc
        return getattr(self.window, 'doc', None)

    def _get_collection(self, attr_name):
        sess = self._get_target_session()
        if sess is not None and hasattr(sess, attr_name):
            val = getattr(sess, attr_name)
            if val is not None:
                return val
        val = getattr(self.window, attr_name, None)
        return val if val is not None else []

    def _is_session_active(self):
        sess = self._get_target_session()
        if sess is None:
            return True
        active = getattr(self.window, '_active_session', None)
        return active is None or active is sess

    def execute(self):
        """Execute the command."""
        raise NotImplementedError

    def undo(self):
        """Undo the command."""
        raise NotImplementedError

    def redo(self):
        """Redo the command by executing it again."""
        self.execute()

    def _erase_ghost_if_needed(self, target_object, page_num, properties_to_clear=None):
        """Redact original object from snapshot if edited/moved."""
        _perform_ghost_erasure(self.window, target_object, page_num, properties_to_clear=properties_to_clear, session=self._get_target_session())

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
        if hasattr(self.window, 'refresh_annotations_list'):
            self.window.refresh_annotations_list()

    record = add_command

    def can_undo(self) -> bool:
        """Check if an undo action is available."""
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        """Check if a redo action is available."""
        return bool(self.redo_stack)

    def undo(self):
        """Undo the command."""
        if hasattr(self.window, 'commit_pending_format_change'):
            self.window.commit_pending_format_change()
        if not self.undo_stack:
            return
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        self._update_ui_callback()
        if hasattr(self.window, 'refresh_annotations_list'):
            self.window.refresh_annotations_list()
        self.window.pdf_view.queue_draw()

    def redo(self):
        """Redo the command."""
        if hasattr(self.window, 'commit_pending_format_change'):
            self.window.commit_pending_format_change()
        if not self.redo_stack:
            return
        command = self.redo_stack.pop()
        command.execute()
        self.undo_stack.append(command)
        self._update_ui_callback()
        if hasattr(self.window, 'refresh_annotations_list'):
            self.window.refresh_annotations_list()
        self.window.pdf_view.queue_draw()

    def clear(self):
        """Clear all undo and redo history."""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._update_ui_callback()

class EditObjectCommand(Command):
    """Command for object modifications (position, bounds, formatting, colors)."""
    def __init__(self, window, target_object, old_properties, new_properties):
        super().__init__(window)
        self.target_object = target_object
        self.old_properties = old_properties
        self.new_properties = new_properties

    def _erase_ghost_if_needed(self, page_num, properties_to_clear):
        """Erase ghost if needed."""
        _perform_ghost_erasure(self.window, self.target_object, page_num, properties_to_clear, session=self._get_target_session())

    def _apply_properties_to_pdf(self, properties_to_apply, properties_to_clear):
        """Apply properties to PDF."""
        page_num = getattr(self.target_object, 'page_number', None)
        if page_num is not None:
            self._erase_ghost_if_needed(page_num, properties_to_clear)
            
        if isinstance(self.target_object, MeasurementObject):
            return True

        doc = self._get_doc()
        if doc is None:
            return False

        texts = self._get_collection('editable_texts')
        shapes = self._get_collection('editable_shapes')
        images = self._get_collection('editable_images')
        strokes = self._get_collection('editable_strokes')
        measurements = self._get_collection('measurements')
        sticky_notes = self._get_collection('sticky_notes')

        if isinstance(self.target_object, EditableStroke):
            temp_obj = copy.deepcopy(self.target_object)
            temp_obj.__dict__.update(copy.deepcopy(properties_to_apply))
            temp_obj.original_bbox = properties_to_clear.get('bbox', temp_obj.bbox)
            if page_num is not None:
                pdf_handler.rebuild_page(
                    doc, page_num,
                    texts, shapes, images,
                    exclude_obj=self.target_object,
                    all_strokes=strokes,
                    all_measurements=measurements,
                    all_sticky_notes=sticky_notes
                )
            success, msg = pdf_handler.apply_object_edit(doc, temp_obj)
            if success:
                self.target_object.is_baked = True
                self.target_object._ghost_redacted = True
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
                    doc, page_num,
                    texts, shapes, images,
                    exclude_obj=self.target_object,
                    all_strokes=strokes,
                    all_measurements=measurements,
                    all_sticky_notes=sticky_notes
                )
            success, msg = pdf_handler.apply_object_edit(doc, temp_obj)
            if success:
                self.target_object.is_baked = True
                self.target_object._ghost_redacted = True
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
                doc, page_num_fallback,
                texts, shapes, images,
                exclude_obj=self.target_object,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )
        
        success, msg = pdf_handler.apply_object_edit(doc, temp_obj_for_pdf)
        if success:
            self.target_object.is_baked = True
            self.target_object._ghost_redacted = True
        else:
            from .ui_components import show_error_dialog
            show_error_dialog(self.window, _("err_during_op", msg))
        
        return success

    def _update_live_object(self, properties_to_apply):
        """Update live object."""
        orig_lt = getattr(self.target_object, 'linked_text', None)
        orig_lp = getattr(self.target_object, 'linked_patch', None)
        self.target_object.__dict__.update(copy.deepcopy(properties_to_apply))
        if orig_lt is not None:
            self.target_object.linked_text = orig_lt
        if orig_lp is not None:
            self.target_object.linked_patch = orig_lp
        self.target_object.original_bbox = self.target_object.bbox
        self.target_object.modified = False
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

    def execute(self):
        """Execute the command."""
        if self._apply_properties_to_pdf(self.new_properties, self.old_properties):
            self._update_live_object(self.new_properties)
            page_num = getattr(self.target_object, 'page_number', None)
            if self._is_session_active():
                if page_num is not None and hasattr(self.window, '_refresh_thumbnail'):
                    self.window._refresh_thumbnail(page_num)
                self.window.status_label.set_text(_("change_applied"))
                self.window.pdf_view.queue_draw()
            elif page_num is not None:
                doc = self._get_doc()
                if doc:
                    pdf_handler.invalidate_page_cache(doc, page_num)

    def undo(self):
        """Undo the command."""
        if self._apply_properties_to_pdf(self.old_properties, self.new_properties):
            self._update_live_object(self.old_properties)
            page_num = getattr(self.target_object, 'page_number', None)
            if self._is_session_active():
                if page_num is not None and hasattr(self.window, '_refresh_thumbnail'):
                    self.window._refresh_thumbnail(page_num)
                self.window.status_label.set_text(_("reverted"))
                self.window.pdf_view.queue_draw()
            elif page_num is not None:
                doc = self._get_doc()
                if doc:
                    pdf_handler.invalidate_page_cache(doc, page_num)

class AddObjectCommand(Command):
    """Command for newly added canvas objects."""
    def __init__(self, window, new_object):
        super().__init__(window)
        self.new_object = new_object
        self.is_text = isinstance(new_object, EditableText)
        self.is_shape = isinstance(new_object, EditableShape)
        self.is_stroke = isinstance(new_object, EditableStroke)
        self.is_image = not (self.is_text or self.is_shape or self.is_stroke)

    def _refresh_thumb(self):
        """Refresh thumb."""
        page_num = getattr(self.new_object, 'page_number', None)
        if page_num is not None and hasattr(self.window, '_refresh_thumbnail'):
            self.window._refresh_thumbnail(page_num)

    def execute(self):
        """Execute the command."""
        doc = self._get_doc()
        texts = self._get_collection('editable_texts')
        shapes = self._get_collection('editable_shapes')
        strokes = self._get_collection('editable_strokes')
        images = self._get_collection('editable_images')
        measurements = self._get_collection('measurements')
        sticky_notes = self._get_collection('sticky_notes')

        if self.is_text:
            if self.new_object not in texts:
                texts.append(self.new_object)
        elif self.is_shape:
            if self.new_object not in shapes:
                shapes.append(self.new_object)
        elif self.is_stroke:
            if self.new_object not in strokes:
                strokes.append(self.new_object)
        else:
            if self.new_object not in images:
                images.append(self.new_object)
                
        self.new_object.is_baked = True
        sess = self._get_target_session()
        fallback_page = getattr(sess, 'current_page_index', getattr(self.window, 'current_page_index', 0))
        page_num = getattr(self.new_object, 'page_number', fallback_page)
        if doc is not None:
            pdf_handler.rebuild_page(
                doc, page_num,
                texts,
                shapes,
                images,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )

        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
            self._refresh_thumb()
            self.window.status_label.set_text(_("object_added"))
            self.window._update_ui_state()
            self.window.pdf_view.queue_draw()
        elif doc is not None and page_num is not None:
            pdf_handler.invalidate_page_cache(doc, page_num)

    def undo(self):
        """Undo the command."""
        doc = self._get_doc()
        texts = self._get_collection('editable_texts')
        shapes = self._get_collection('editable_shapes')
        strokes = self._get_collection('editable_strokes')
        images = self._get_collection('editable_images')
        measurements = self._get_collection('measurements')
        sticky_notes = self._get_collection('sticky_notes')

        if self.is_text and self.new_object in texts:
            texts.remove(self.new_object)
        elif self.is_shape and self.new_object in shapes:
            shapes.remove(self.new_object)
        elif self.is_stroke and self.new_object in strokes:
            strokes.remove(self.new_object)
        elif self.is_image and self.new_object in images:
            images.remove(self.new_object)

        sess = self._get_target_session()
        fallback_page = getattr(sess, 'current_page_index', getattr(self.window, 'current_page_index', 0))
        page_num = getattr(self.new_object, 'page_number', fallback_page)
        if doc is not None:
            pdf_handler.rebuild_page(
                doc, page_num,
                texts,
                shapes,
                images,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )

        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
            self.window.status_label.set_text(_("reverted"))
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(page_num)
            self.window.pdf_view.queue_draw()
        elif doc is not None and page_num is not None:
            pdf_handler.invalidate_page_cache(doc, page_num)


class ReorderObjectCommand(Command):
    """Command for changing z-index / layer ordering of canvas objects."""
    def __init__(self, window, target_object, old_index, new_index, z_changes=None):
        super().__init__(window)
        self.target_object = target_object
        self.old_index = old_index
        self.new_index = new_index
        # list of (object, old_z_index, new_z_index)
        self.z_changes = z_changes

    _LIST_NAMES = ('editable_images', 'editable_shapes', 'editable_strokes', 'editable_texts')

    def _apply_z(self, use_new):
        if getattr(self, '_orig_lists', None) is None:
            self._orig_lists = {n: list(self._get_collection(n) or []) for n in self._LIST_NAMES}
        for obj, old_z, new_z in self.z_changes:
            obj.z_index = new_z if use_new else old_z
        for name in self._LIST_NAMES:
            col = self._get_collection(name)
            if col is None or len(col) <= 1:
                continue
            if use_new:
                col[:] = pdf_handler.sort_by_layer(col)
            else:
                orig = self._orig_lists[name]
                col[:] = [o for o in orig if o in col] + [o for o in col if o not in orig]

    def _get_target_collection(self):
        if isinstance(self.target_object, EditableText):
            return self._get_collection('editable_texts')
        elif isinstance(self.target_object, EditableShape):
            return self._get_collection('editable_shapes')
        elif isinstance(self.target_object, EditableStroke):
            return self._get_collection('editable_strokes')
        else:
            return self._get_collection('editable_images')

    def _refresh(self, status_msg=None):
        doc = self._get_doc()
        texts = self._get_collection('editable_texts')
        shapes = self._get_collection('editable_shapes')
        strokes = self._get_collection('editable_strokes')
        images = self._get_collection('editable_images')
        measurements = self._get_collection('measurements')
        sticky_notes = self._get_collection('sticky_notes')

        sess = self._get_target_session()
        fallback_page = getattr(sess, 'current_page_index', getattr(self.window, 'current_page_index', 0))
        page_num = getattr(self.target_object, 'page_number', fallback_page)
        if doc is not None:
            pdf_handler.rebuild_page(
                doc, page_num,
                texts,
                shapes,
                images,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )

        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(page_num)
            if status_msg and hasattr(self.window, 'status_label') and self.window.status_label:
                self.window.status_label.set_text(status_msg)
            self.window._update_ui_state()
            self.window.pdf_view.queue_draw()
        elif doc is not None and page_num is not None:
            pdf_handler.invalidate_page_cache(doc, page_num)

    def _lift_original_objects(self):
        """Bake original PDF objects that must take part in layering.

        The reordered object is always lifted. Any other original object that sits
        above an already-baked object in the new order is lifted too, otherwise it
        would stay below every baked object in the base stream.
        """
        ordered = [o for o, _old, _new in sorted(self.z_changes, key=lambda c: c[2])]
        baked_seen = False
        for obj in ordered:
            is_orig = (not getattr(obj, 'is_new', True)
                       and not getattr(obj, '_ghost_redacted', False)
                       and isinstance(obj, (EditableText, EditableImage, EditableShape, EditableStroke)))
            if is_orig and (obj is self.target_object or baked_seen):
                page_num = getattr(obj, 'page_number', None)
                if page_num is not None:
                    _perform_ghost_erasure(self.window, obj, page_num, session=self._get_target_session())
            if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False) \
                    or not isinstance(obj, (EditableText, EditableImage, EditableShape, EditableStroke)):
                baked_seen = True

    def execute(self):
        if self.z_changes:
            self._apply_z(True)
            self._lift_original_objects()
            self._refresh()
            return
        col = self._get_target_collection()
        if self.target_object in col:
            col.remove(self.target_object)
            insert_idx = max(0, min(len(col), self.new_index))
            col.insert(insert_idx, self.target_object)
            self._refresh()

    def undo(self):
        if self.z_changes:
            self._apply_z(False)
            self._refresh(_("reverted"))
            return
        col = self._get_target_collection()
        if self.target_object in col:
            col.remove(self.target_object)
            insert_idx = max(0, min(len(col), self.old_index))
            col.insert(insert_idx, self.target_object)
            self._refresh(_("reverted"))


class DeleteObjectCommand(Command):
    """Command for deleting canvas objects with restoration on undo."""
    def __init__(self, window, deleted_object):
        super().__init__(window)
        self.deleted_object = deleted_object
        self.is_text = isinstance(deleted_object, EditableText)
        self.is_shape = isinstance(deleted_object, EditableShape)
        self.is_stroke = isinstance(deleted_object, EditableStroke)

    def execute(self):
        """Execute the command."""
        doc = self._get_doc()
        texts = self._get_collection('editable_texts')
        shapes = self._get_collection('editable_shapes')
        strokes = self._get_collection('editable_strokes')
        images = self._get_collection('editable_images')
        measurements = self._get_collection('measurements')
        sticky_notes = self._get_collection('sticky_notes')

        if self.is_text and self.deleted_object in texts:
            texts.remove(self.deleted_object)
        elif self.is_shape and self.deleted_object in shapes:
            shapes.remove(self.deleted_object)
        elif self.is_stroke and self.deleted_object in strokes:
            strokes.remove(self.deleted_object)
        elif not self.is_text and not self.is_shape and not self.is_stroke and self.deleted_object in images:
            images.remove(self.deleted_object)

        sess = self._get_target_session()
        fallback_page = getattr(sess, 'current_page_index', getattr(self.window, 'current_page_index', 0))
        page_num = getattr(self.deleted_object, 'page_number', fallback_page)
        if page_num is not None:
            self._erase_ghost_if_needed(self.deleted_object, page_num)
            
        if doc is not None:
            pdf_handler.rebuild_page(
                doc, page_num,
                texts,
                shapes,
                images,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )

        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
            self.window.status_label.set_text(_("object_deleted"))
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(page_num)
            self.window.pdf_view.queue_draw()
        elif doc is not None and page_num is not None:
            pdf_handler.invalidate_page_cache(doc, page_num)

    def undo(self):
        """Undo the command."""
        doc = self._get_doc()
        texts = self._get_collection('editable_texts')
        shapes = self._get_collection('editable_shapes')
        strokes = self._get_collection('editable_strokes')
        images = self._get_collection('editable_images')
        measurements = self._get_collection('measurements')
        sticky_notes = self._get_collection('sticky_notes')

        if self.is_text and self.deleted_object not in texts:
            texts.append(self.deleted_object)
        elif self.is_shape and self.deleted_object not in shapes:
            shapes.append(self.deleted_object)
        elif self.is_stroke:
            if self.deleted_object not in strokes:
                strokes.append(self.deleted_object)
        elif not self.is_text and not self.is_shape and not self.is_stroke and self.deleted_object not in images:
            images.append(self.deleted_object)

        sess = self._get_target_session()
        fallback_page = getattr(sess, 'current_page_index', getattr(self.window, 'current_page_index', 0))
        page_num = getattr(self.deleted_object, 'page_number', fallback_page)
        if doc is not None:
            pdf_handler.rebuild_page(
                doc, page_num,
                texts,
                shapes,
                images,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )

        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
            self.window.status_label.set_text(_("delete_reverted"))
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(page_num)
            self.window.pdf_view.queue_draw()
        elif doc is not None and page_num is not None:
            pdf_handler.invalidate_page_cache(doc, page_num)

class CompositeCommand(Command):
    """Composite command executing multiple atomic actions in a single undo step."""
    def __init__(self, window, commands):
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
        doc = self._get_doc()
        if not doc:
            return
        success, _res = pdf_handler.rotate_page(doc, self.page_index, self.angle_delta)
        if success:
            self._apply_rotation_ui()

    def undo(self):
        """Revert page rotation by -angle_delta degrees and update display."""
        doc = self._get_doc()
        if not doc:
            return
        success, _res = pdf_handler.rotate_page(doc, self.page_index, -self.angle_delta)
        if success:
            self._apply_rotation_ui()

    def _apply_rotation_ui(self):
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True
        if self._is_session_active():
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(self.page_index)
            if hasattr(self.window, 'current_page_index') and self.window.current_page_index == self.page_index:
                try:
                    doc = self._get_doc()
                    page = doc.load_page(self.page_index) if doc else None
                    if page:
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
        else:
            doc = self._get_doc()
            if doc:
                pdf_handler.invalidate_page_cache(doc, self.page_index)

class RotateObjectCommand(Command):
    """Command to rotate an object (text, image, shape, stroke) with full undo/redo."""
    def __init__(self, window, target_object, old_rotation: float, new_rotation: float):
        super().__init__(window)
        self.target_object = target_object
        self.old_rotation = float(old_rotation) % 360.0
        self.new_rotation = float(new_rotation) % 360.0

    def _apply_rotation(self, to_angle: float, from_angle: float):
        """Bake the rotation into the PDF page and update live object and UI."""
        page_num = getattr(self.target_object, 'page_number', None)
        doc = self._get_doc()
        if page_num is not None and doc:
            orig_rot = from_angle
            orig_bbox = getattr(self.target_object, 'original_bbox', getattr(self.target_object, 'bbox', None))
            props_to_clear = {'rotation': orig_rot, 'bbox': orig_bbox}
            self._erase_ghost_if_needed(self.target_object, page_num, properties_to_clear=props_to_clear)

            temp_obj = copy.deepcopy(self.target_object)
            if hasattr(temp_obj, 'set_rotation'):
                temp_obj.set_rotation(to_angle)
            else:
                temp_obj.rotation = float(to_angle) % 360.0

            texts = self._get_collection('editable_texts')
            shapes = self._get_collection('editable_shapes')
            images = self._get_collection('editable_images')
            strokes = self._get_collection('editable_strokes')
            measurements = self._get_collection('measurements')
            sticky_notes = self._get_collection('sticky_notes')

            pdf_handler.rebuild_page(
                doc, page_num,
                texts,
                shapes,
                images,
                exclude_obj=self.target_object,
                all_strokes=strokes,
                all_measurements=measurements,
                all_sticky_notes=sticky_notes
            )
            success, msg = pdf_handler.apply_object_edit(doc, temp_obj)
            if success:
                self.target_object.is_baked = True
                self.target_object._ghost_redacted = True
                if self._is_session_active() and hasattr(self.window, '_refresh_thumbnail'):
                    self.window._refresh_thumbnail(page_num)
            else:
                from .ui_components import show_error_dialog
                show_error_dialog(self.window, _("err_during_op", msg))

        if hasattr(self.target_object, 'set_rotation'):
            self.target_object.set_rotation(to_angle)
        else:
            self.target_object.rotation = float(to_angle) % 360.0

        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
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
        elif doc is not None and page_num is not None:
            pdf_handler.invalidate_page_cache(doc, page_num)

    def execute(self):
        """Apply new rotation angle."""
        self._apply_rotation(self.new_rotation, self.old_rotation)
        if self._is_session_active() and hasattr(self.window, 'status_label') and self.window.status_label:
            self.window.status_label.set_text(_("status_object_rotation", f"{self.new_rotation:.1f}°"))

    def undo(self):
        """Revert back to old rotation angle."""
        self._apply_rotation(self.old_rotation, self.new_rotation)
        if self._is_session_active() and hasattr(self.window, 'status_label') and self.window.status_label:
            self.window.status_label.set_text(_("status_object_rotation", f"{self.old_rotation:.1f}°"))


class ReplaceImageCommand(Command):
    """Command for replacing an embedded image with full undo/redo support."""
    def __init__(self, window, target_image: EditableImage, new_raw_bytes: bytes):
        super().__init__(window)
        self.target_image = target_image
        self.old_image_bytes = target_image.image_bytes
        self.old_raw_bytes = getattr(target_image, 'raw_image_bytes', target_image.image_bytes)
        self.old_xref = getattr(target_image, 'xref', None)
        self.new_raw_bytes = new_raw_bytes
        self.new_image_bytes = None
        self.new_xref = None

    def execute(self):
        """Execute the image replacement on the PDF page."""
        doc = self._get_doc()
        if not doc:
            return False
        self.target_image.raw_image_bytes = self.new_raw_bytes
        success, err, new_xref = pdf_handler.replace_image_on_page(
            doc,
            self.target_image,
            self.new_raw_bytes
        )
        if success:
            self.new_image_bytes = self.target_image.image_bytes
            self.new_xref = new_xref
            sess = self._get_target_session()
            if sess is not None:
                sess.document_modified = True
            self.window.document_modified = True
            page_num = getattr(self.target_image, 'page_number', None)
            if self._is_session_active():
                if page_num is not None and hasattr(self.window, '_refresh_thumbnail'):
                    self.window._refresh_thumbnail(page_num)
                if hasattr(self.window, 'status_label') and self.window.status_label:
                    self.window.status_label.set_text(_("change_applied"))
                if hasattr(self.window, 'pdf_view'):
                    self.window.pdf_view.queue_draw()
                if hasattr(self.window, '_update_ui_state'):
                    self.window._update_ui_state()
            elif page_num is not None:
                pdf_handler.invalidate_page_cache(doc, page_num)
            return True
        else:
            from .ui_components import show_error_dialog
            show_error_dialog(self.window, _("err_during_op", err))
            return False

    def undo(self):
        """Revert the image replacement to the original image bytes."""
        doc = self._get_doc()
        if not doc:
            return False
        self.target_image.raw_image_bytes = self.old_raw_bytes
        success, err, reverted_xref = pdf_handler.replace_image_on_page(
            doc,
            self.target_image,
            self.old_image_bytes
        )
        if success:
            if self.old_xref:
                self.target_image.xref = self.old_xref
            sess = self._get_target_session()
            if sess is not None:
                sess.document_modified = True
            self.window.document_modified = True
            page_num = getattr(self.target_image, 'page_number', None)
            if self._is_session_active():
                if page_num is not None and hasattr(self.window, '_refresh_thumbnail'):
                    self.window._refresh_thumbnail(page_num)
                if hasattr(self.window, 'status_label') and self.window.status_label:
                    self.window.status_label.set_text(_("reverted"))
                if hasattr(self.window, 'pdf_view'):
                    self.window.pdf_view.queue_draw()
                if hasattr(self.window, '_update_ui_state'):
                    self.window._update_ui_state()
            elif page_num is not None:
                pdf_handler.invalidate_page_cache(doc, page_num)
            return True
        else:
            from .ui_components import show_error_dialog
            show_error_dialog(self.window, _("err_during_op", err))
            return False


class EditFormFieldCommand(Command):
    """Command representing an interactive AcroForm field value modification."""
    def __init__(self, window, target_field, old_value, new_value):
        super().__init__(window)
        self.target_field = target_field
        self.old_value = old_value
        self.new_value = new_value

    def execute(self):
        self._apply_val(self.new_value)

    def undo(self):
        self._apply_val(self.old_value)

    def _apply_val(self, val):
        self.target_field.set_value(val)
        doc = self._get_doc()
        if doc:
            pdf_handler.update_acroform_field_value(
                doc,
                self.target_field.page_number,
                self.target_field.xref,
                val
            )
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True
        if self._is_session_active():
            if hasattr(self.window, '_refresh_form_field_widget_value'):
                self.window._refresh_form_field_widget_value(self.target_field)
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
        elif doc is not None and getattr(self.target_field, 'page_number', None) is not None:
            pdf_handler.invalidate_page_cache(doc, self.target_field.page_number)


class AddFormFieldCommand(Command):
    """Command representing insertion of a new AcroForm interactive field."""
    def __init__(self, window, page_number: int, field_type: str, rect: tuple,
                 field_name: str, default_value: Any = None, choice_values: Optional[list] = None,
                 is_multiline: bool = False):
        super().__init__(window)
        self.page_number = page_number
        self.field_type = field_type
        self.rect = rect
        self.field_name = field_name
        self.default_value = default_value
        self.choice_values = choice_values
        self.is_multiline = is_multiline
        self.created_xref = None

    def execute(self):
        doc = self._get_doc()
        if not doc or getattr(doc, 'is_closed', False):
            return
        w = pdf_handler.add_form_widget(
            doc,
            self.page_number,
            self.field_type,
            self.rect,
            self.field_name,
            self.default_value,
            choice_values=self.choice_values,
            is_multiline=self.is_multiline
        )
        if w:
            self.created_xref = getattr(w, "xref", None)
        self._refresh()

    def undo(self):
        doc = self._get_doc()
        if not doc or getattr(doc, 'is_closed', False):
            return
        pdf_handler.delete_form_widget(
            doc,
            self.created_xref or self.field_name,
            page_index=self.page_number
        )
        if getattr(self.window, 'selected_form_field', None) and (
            getattr(self.window.selected_form_field, 'xref', None) == self.created_xref or
            getattr(self.window.selected_form_field, 'field_name', None) == self.field_name
        ):
            self.window.selected_form_field = None
        self._refresh()

    def _refresh(self):
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True
        doc = self._get_doc()
        if self._is_session_active():
            if hasattr(self.window, '_load_acroform_fields_for_page'):
                self.window._load_acroform_fields_for_page(self.page_number)
            elif doc:
                fields, _ = pdf_handler.extract_acroform_fields(doc, page_index=self.window.current_page_index)
                self.window.form_fields = fields
                if hasattr(self.window, '_create_form_field_overlays'):
                    self.window._create_form_field_overlays()
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(self.page_number)
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
        elif doc is not None and self.page_number is not None:
            pdf_handler.invalidate_page_cache(doc, self.page_number)


class DeleteFormFieldCommand(Command):
    """Command representing deletion of an AcroForm interactive field."""
    def __init__(self, window, target_field: AcroFormField):
        super().__init__(window)
        self.page_number = target_field.page_number
        self.field_type = target_field.field_type
        self.rect = target_field.rect
        self.field_name = target_field.field_name
        self.field_value = target_field.value
        self.choice_values = target_field.choice_values
        self.is_multiline = getattr(target_field, 'is_multiline', False)
        self.xref = getattr(target_field, 'xref', None)

    def execute(self):
        doc = self._get_doc()
        if not doc or getattr(doc, 'is_closed', False):
            return
        pdf_handler.delete_form_widget(
            doc,
            self.xref or self.field_name,
            page_index=self.page_number
        )
        if getattr(self.window, 'selected_form_field', None) and (
            getattr(self.window.selected_form_field, 'xref', None) == self.xref or
            getattr(self.window.selected_form_field, 'field_name', None) == self.field_name
        ):
            self.window.selected_form_field = None
        self._refresh()

    def undo(self):
        doc = self._get_doc()
        if not doc or getattr(doc, 'is_closed', False):
            return
        w = pdf_handler.add_form_widget(
            doc,
            self.page_number,
            self.field_type,
            self.rect,
            self.field_name,
            self.field_value,
            choice_values=self.choice_values,
            is_multiline=self.is_multiline
        )
        if w:
            self.xref = getattr(w, "xref", self.xref)
        self._refresh()

    def _refresh(self):
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True
        doc = self._get_doc()
        if self._is_session_active():
            if hasattr(self.window, '_load_acroform_fields_for_page'):
                self.window._load_acroform_fields_for_page(self.page_number)
            elif doc:
                fields, _ = pdf_handler.extract_acroform_fields(doc, page_index=self.window.current_page_index)
                self.window.form_fields = fields
                if hasattr(self.window, '_create_form_field_overlays'):
                    self.window._create_form_field_overlays()
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(self.page_number)
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
        elif doc is not None and self.page_number is not None:
            pdf_handler.invalidate_page_cache(doc, self.page_number)


class MoveResizeFormFieldCommand(Command):
    """Command representing repositioning or resizing of an AcroForm interactive field."""
    def __init__(self, window, target_field: AcroFormField, old_rect: tuple, new_rect: tuple):
        super().__init__(window)
        self.page_number = getattr(target_field, 'page_number', getattr(window, 'current_page_index', 0))
        self.target_field = target_field
        self.old_rect = old_rect
        self.new_rect = new_rect
        self.xref = getattr(target_field, 'xref', None)
        self.field_name = getattr(target_field, 'field_name', '')

    def execute(self):
        self._apply_rect(self.new_rect)

    def undo(self):
        self._apply_rect(self.old_rect)

    def _apply_rect(self, rect: tuple):
        doc = self._get_doc()
        if not doc or getattr(doc, 'is_closed', False):
            return
        self.target_field.rect = rect
        pdf_handler.update_form_widget_geometry(
            doc,
            self.xref or self.field_name,
            rect,
            page_index=self.page_number
        )
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True
        if self._is_session_active():
            if hasattr(self.window, '_update_tab_dirty_state'):
                self.window._update_tab_dirty_state()
            if hasattr(self.window, '_update_form_field_overlay_positions'):
                self.window._update_form_field_overlay_positions()
            if hasattr(self.window, '_refresh_thumbnail'):
                self.window._refresh_thumbnail(self.page_number)
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
        elif doc is not None and self.page_number is not None:
            pdf_handler.invalidate_page_cache(doc, self.page_number)


class EditFormFieldChoicesCommand(Command):
    """Command representing modification of choice options for a dropdown/combobox field."""
    def __init__(self, window, target_field: AcroFormField, old_choices: list, new_choices: list):
        super().__init__(window)
        self.page_number = getattr(target_field, 'page_number', getattr(window, 'current_page_index', 0))
        self.target_field = target_field
        self.old_choices = list(old_choices)
        self.new_choices = list(new_choices)
        self.xref = getattr(target_field, 'xref', None)
        self.field_name = getattr(target_field, 'field_name', '')

    def execute(self):
        self._apply_choices(self.new_choices)

    def undo(self):
        self._apply_choices(self.old_choices)

    def _apply_choices(self, choices: list):
        doc = self._get_doc()
        if not doc or getattr(doc, 'is_closed', False):
            return
        self.target_field.choice_values = list(choices)
        if getattr(self.target_field, 'value', '') not in choices and choices:
            self.target_field.value = choices[0]
        pdf_handler.update_form_widget_choices(
            doc,
            self.xref or self.field_name,
            choices,
            page_index=self.page_number
        )
        sess = self._get_target_session()
        if sess is not None:
            sess.document_modified = True
        self.window.document_modified = True
        if self._is_session_active():
            if hasattr(self.window, '_update_tab_dirty_state'):
                self.window._update_tab_dirty_state()
            if hasattr(self.window, '_form_field_overlay_widgets'):
                ed = self.window._form_field_overlay_widgets.get(getattr(self.target_field, 'field_id', None))
                if ed and isinstance(ed.get("widget"), Gtk.DropDown):
                    dd = ed["widget"]
                    dd.set_model(Gtk.StringList.new(choices))
                    ed["display_items"] = list(choices)
                    ed["export_items"] = list(choices)
                    if dd.get_selected() >= len(choices):
                        dd.set_selected(0)
            if hasattr(self.window, '_update_form_builder_controls_for_selected'):
                self.window._update_form_builder_controls_for_selected()
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
        elif doc is not None and self.page_number is not None:
            pdf_handler.invalidate_page_cache(doc, self.page_number)


class CalibrateScaleCommand(Command):
    """Command to apply, update, or reset drawing scale calibration."""
    def __init__(self, window, old_calibration, new_calibration, page_index=None, entire_document=True):
        super().__init__(window)
        self.old_calibration = old_calibration
        self.new_calibration = new_calibration
        self.page_index = page_index
        self.entire_document = entire_document

    def execute(self):
        self.window._apply_scale_calibration_state(
            self.new_calibration,
            page_index=self.page_index,
            entire_document=self.entire_document
        )

    def undo(self):
        self.window._apply_scale_calibration_state(
            self.old_calibration,
            page_index=self.page_index,
            entire_document=self.entire_document
        )


class AddMeasurementCommand(Command):
    """Command to add a linear distance or area measurement."""
    def __init__(self, window, measurement):
        super().__init__(window)
        self.measurement = measurement

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._add_measurement_to_session(self.measurement, session=sess)
        except TypeError:
            self.window._add_measurement_to_session(self.measurement)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._remove_measurement_from_session(self.measurement, session=sess)
        except TypeError:
            self.window._remove_measurement_from_session(self.measurement)


class DeleteMeasurementCommand(Command):
    """Command to delete a linear distance or area measurement."""
    def __init__(self, window, measurement):
        super().__init__(window)
        self.measurement = measurement

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._remove_measurement_from_session(self.measurement, session=sess)
        except TypeError:
            self.window._remove_measurement_from_session(self.measurement)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._add_measurement_to_session(self.measurement, session=sess)
        except TypeError:
            self.window._add_measurement_to_session(self.measurement)


class AddStickyNoteCommand(Command):
    """Command to add a sticky note / comment annotation."""
    def __init__(self, window, note):
        super().__init__(window)
        self.note = note

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._add_sticky_note_to_session(self.note, session=sess)
        except TypeError:
            self.window._add_sticky_note_to_session(self.note)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._remove_sticky_note_from_session(self.note, session=sess)
        except TypeError:
            self.window._remove_sticky_note_from_session(self.note)


class DeleteStickyNoteCommand(Command):
    """Command to delete a sticky note / comment annotation."""
    def __init__(self, window, note):
        super().__init__(window)
        self.note = note

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._remove_sticky_note_from_session(self.note, session=sess)
        except TypeError:
            self.window._remove_sticky_note_from_session(self.note)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._add_sticky_note_to_session(self.note, session=sess)
        except TypeError:
            self.window._add_sticky_note_to_session(self.note)


class EditStickyNoteCommand(Command):
    """Command to modify a sticky note's content, author, color, or icon."""
    def __init__(self, window, note, old_state: dict, new_state: dict):
        super().__init__(window)
        self.note = note
        self.old_state = dict(old_state)
        self.new_state = dict(new_state)

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._apply_sticky_note_state(self.note, self.new_state, session=sess)
        except TypeError:
            self.window._apply_sticky_note_state(self.note, self.new_state)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._apply_sticky_note_state(self.note, self.old_state, session=sess)
        except TypeError:
            self.window._apply_sticky_note_state(self.note, self.old_state)


class MoveStickyNoteCommand(Command):
    """Command to move a sticky note position."""
    def __init__(self, window, note, old_pos: tuple, new_pos: tuple):
        super().__init__(window)
        self.note = note
        self.old_pos = tuple(old_pos)
        self.new_pos = tuple(new_pos)

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._set_sticky_note_pos(self.note, self.new_pos[0], self.new_pos[1], session=sess)
        except TypeError:
            self.window._set_sticky_note_pos(self.note, self.new_pos[0], self.new_pos[1])

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._set_sticky_note_pos(self.note, self.old_pos[0], self.old_pos[1], session=sess)
        except TypeError:
            self.window._set_sticky_note_pos(self.note, self.old_pos[0], self.old_pos[1])


class AddRedactionCommand(Command):
    """Command to add a visual staged redaction mark."""
    def __init__(self, window, mark):
        super().__init__(window)
        self.mark = mark

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._add_redaction_mark_to_session(self.mark, session=sess)
        except TypeError:
            self.window._add_redaction_mark_to_session(self.mark)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._remove_redaction_mark_from_session(self.mark, session=sess)
        except TypeError:
            self.window._remove_redaction_mark_from_session(self.mark)


class DeleteRedactionCommand(Command):
    """Command to delete a visual staged redaction mark."""
    def __init__(self, window, mark):
        super().__init__(window)
        self.mark = mark

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._remove_redaction_mark_from_session(self.mark, session=sess)
        except TypeError:
            self.window._remove_redaction_mark_from_session(self.mark)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._add_redaction_mark_to_session(self.mark, session=sess)
        except TypeError:
            self.window._add_redaction_mark_to_session(self.mark)


class EditRedactionCommand(Command):
    """Command to modify a redaction mark's bounding box, fill color, or overlay text."""
    def __init__(self, window, mark, old_state: dict, new_state: dict):
        super().__init__(window)
        self.mark = mark
        self.old_state = dict(old_state)
        self.new_state = dict(new_state)

    def execute(self):
        sess = self._get_target_session()
        try:
            self.window._apply_redaction_mark_state(self.mark, self.new_state, session=sess)
        except TypeError:
            self.window._apply_redaction_mark_state(self.mark, self.new_state)

    def undo(self):
        sess = self._get_target_session()
        try:
            self.window._apply_redaction_mark_state(self.mark, self.old_state, session=sess)
        except TypeError:
            self.window._apply_redaction_mark_state(self.mark, self.old_state)


class FlattenCommand(Command):
    """Command to flatten annotations into page content streams with complete undo/redo support."""
    def __init__(self, window, page_indices: List[int], include_forms: bool = False):
        super().__init__(window)
        self.page_indices = list(page_indices)
        self.include_forms = include_forms

        # Snapshot full state before flattening
        doc = self._get_doc()
        self.pre_pdf_bytes = doc.tobytes() if doc else None
        self.pre_editable_strokes = copy.deepcopy(self._get_collection('editable_strokes'))
        self.pre_editable_shapes = copy.deepcopy(self._get_collection('editable_shapes'))
        self.pre_measurement_objects = copy.deepcopy(self._get_collection('measurement_objects'))
        self.pre_editable_texts = copy.deepcopy(self._get_collection('editable_texts'))
        self.pre_editable_images = copy.deepcopy(self._get_collection('editable_images'))
        self.pre_form_fields = copy.deepcopy(self._get_collection('form_fields'))
        sess = self._get_target_session()
        self.pre_document_modified = getattr(sess, 'document_modified', getattr(self.window, 'document_modified', False))

    def execute(self):
        """Execute flattening on targeted pages."""
        # Collect in-memory canvas objects for the targeted pages
        session_objects_by_page = {}
        for p in self.page_indices:
            objs = []
            for stroke in self._get_collection('editable_strokes'):
                if getattr(stroke, 'page_number', None) == p:
                    objs.append(stroke)
            for shape in self._get_collection('editable_shapes'):
                if getattr(shape, 'page_number', None) == p:
                    objs.append(shape)
            for m in self._get_collection('measurement_objects'):
                if getattr(m, 'page_number', None) == p:
                    objs.append(m)
            for t in self._get_collection('editable_texts'):
                if getattr(t, 'page_number', None) == p:
                    objs.append(t)
            for img in self._get_collection('editable_images'):
                if getattr(img, 'page_number', None) == p:
                    objs.append(img)
            if objs:
                session_objects_by_page[p] = objs

        # Call backend flattening in pdf_handler
        doc = self._get_doc()
        if doc:
            pdf_handler.flatten_document_annotations(
                doc,
                self.page_indices,
                include_forms=self.include_forms,
                session_objects_by_page=session_objects_by_page
            )

        sess = self._get_target_session()
        targets = [sess, self.window] if sess else [self.window]
        for target in targets:
            if hasattr(target, 'editable_strokes') and getattr(target, 'editable_strokes') is not None:
                target.editable_strokes = [s for s in target.editable_strokes if getattr(s, 'page_number', None) not in self.page_indices]
            if hasattr(target, 'editable_shapes') and getattr(target, 'editable_shapes') is not None:
                target.editable_shapes = [s for s in target.editable_shapes if getattr(s, 'page_number', None) not in self.page_indices]
            if hasattr(target, 'measurement_objects') and getattr(target, 'measurement_objects') is not None:
                target.measurement_objects = [m for m in target.measurement_objects if getattr(m, 'page_number', None) not in self.page_indices]
            if hasattr(target, 'editable_texts') and getattr(target, 'editable_texts') is not None:
                target.editable_texts = [t for t in target.editable_texts if getattr(t, 'page_number', None) not in self.page_indices]
            if hasattr(target, 'editable_images') and getattr(target, 'editable_images') is not None:
                target.editable_images = [img for img in target.editable_images if getattr(img, 'page_number', None) not in self.page_indices]
            if self.include_forms and hasattr(target, 'form_fields') and getattr(target, 'form_fields') is not None:
                target.form_fields = [f for f in target.form_fields if getattr(f, 'page_number', None) not in self.page_indices]

        if sess:
            sess.document_modified = True
        self.window.document_modified = True

        if self._is_session_active():
            if hasattr(self.window, 'load_page') and getattr(self.window, 'current_page_index', None) in self.page_indices:
                self.window.load_page(self.window.current_page_index, reload_objects=True)
            # Clear active selection if the selected object was on one of the flattened pages
            sel = getattr(self.window, 'get_selected_object', lambda: None)()
            if sel and getattr(sel, 'page_number', None) in self.page_indices:
                if hasattr(self.window, 'clear_selection'):
                    self.window.clear_selection()
            if hasattr(self.window, '_refresh_thumbnail'):
                for p in self.page_indices:
                    self.window._refresh_thumbnail(p)
            if hasattr(self.window, 'refresh_annotations_list'):
                self.window.refresh_annotations_list()
            if hasattr(self.window, 'status_label') and self.window.status_label:
                self.window.status_label.set_text(_("status_flatten_done").format(len(self.page_indices)))
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()

    def undo(self):
        """Revert flattening by restoring exact pre-flatten document state and objects."""
        doc = self._get_doc()
        if self.pre_pdf_bytes and doc:
            restore_doc = fitz.open(stream=self.pre_pdf_bytes, filetype="pdf")
            for i in range(doc.page_count - 1, -1, -1):
                doc.delete_page(i)
            doc.insert_pdf(restore_doc)
            pdf_handler.invalidate_page_cache(doc)

        sess = self._get_target_session()
        targets = [sess, self.window] if sess else [self.window]
        for target in targets:
            if hasattr(target, 'editable_strokes'):
                target.editable_strokes = copy.deepcopy(self.pre_editable_strokes)
            if hasattr(target, 'editable_shapes'):
                target.editable_shapes = copy.deepcopy(self.pre_editable_shapes)
            if hasattr(target, 'measurement_objects'):
                target.measurement_objects = copy.deepcopy(self.pre_measurement_objects)
            if hasattr(target, 'editable_texts'):
                target.editable_texts = copy.deepcopy(self.pre_editable_texts)
            if hasattr(target, 'editable_images'):
                target.editable_images = copy.deepcopy(self.pre_editable_images)
            if hasattr(target, 'form_fields'):
                target.form_fields = copy.deepcopy(self.pre_form_fields)
            if hasattr(target, 'document_modified'):
                target.document_modified = self.pre_document_modified

        if self._is_session_active():
            if hasattr(self.window, 'load_page') and getattr(self.window, 'current_page_index', None) in self.page_indices:
                self.window.load_page(self.window.current_page_index, reload_objects=True)
            if hasattr(self.window, '_refresh_thumbnail'):
                for p in self.page_indices:
                    self.window._refresh_thumbnail(p)
            if hasattr(self.window, 'refresh_annotations_list'):
                self.window.refresh_annotations_list()
            if hasattr(self.window, 'status_label') and self.window.status_label:
                self.window.status_label.set_text(_("reverted"))
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()


class EmbedOCRTextCommand(Command):
    """Command to embed a transparent searchable OCR text layer (render_mode=3) with undo/redo support."""

    def __init__(
        self,
        window,
        page_indices: List[int],
        ocr_results: Optional[Dict[int, Any]] = None,
        ocr_words_by_page: Optional[Dict[int, List[Dict[str, Any]]]] = None,
        language: str = "eng",
        dpi: int = 150,
    ):
        super().__init__(window)
        self.page_indices = list(page_indices)
        self.language = language
        self.dpi = dpi
        self.last_result: Dict[str, Any] = {}

        doc = self._get_doc()
        self.pre_snapshots: Dict[int, bytes] = {}
        self.ocr_words_by_page: Dict[int, List[Dict[str, Any]]] = (
            copy.deepcopy(ocr_words_by_page) if ocr_words_by_page is not None else {}
        )

        if doc is not None:
            for p in self.page_indices:
                if 0 <= p < len(doc):
                    pdf_handler.save_page_snapshot(doc, p)
                    snap = pdf_handler._page_snapshots.get((id(doc), p))
                    if snap is not None:
                        self.pre_snapshots[p] = snap
                    if p not in self.ocr_words_by_page and ocr_results and p in ocr_results:
                        ocr_doc = ocr_results[p]
                        try:
                            self.ocr_words_by_page[p] = pdf_handler.extract_ocr_words_for_page(doc[p], ocr_doc)
                        finally:
                            try:
                                ocr_doc.close()
                            except Exception:
                                pass

        self.pre_editable_texts = copy.deepcopy(self._get_collection('editable_texts'))
        sess = self._get_target_session()
        self.pre_document_modified = getattr(
            sess, 'is_modified', getattr(self.window, 'document_modified', False)
        )

    def _invalidate_objects_cache(self, pages: List[int]):
        sess = self._get_target_session()
        for target in ([sess, self.window] if sess else [self.window]):
            cache = getattr(target, '_page_objects_cache', None)
            if isinstance(cache, dict):
                for p in pages:
                    cache.pop(p, None)
            cache2 = getattr(target, 'page_objects_cache', None)
            if isinstance(cache2, dict):
                for p in pages:
                    cache2.pop(p, None)

    def execute(self):
        doc = self._get_doc()
        if not doc:
            return
        for p, snap in self.pre_snapshots.items():
            pdf_handler._page_pre_ocr_snapshots[(id(doc), p)] = snap

        self.last_result = pdf_handler.embed_ocr_text_layer(
            doc,
            page_numbers=self.page_indices,
            ocr_words_by_page=self.ocr_words_by_page if self.ocr_words_by_page else None,
            language=self.language,
            dpi=self.dpi,
            replace_existing=True,
        )

        # Cache any newly computed OCR words so redo does not re-run OCR
        for p in self.page_indices:
            if p not in self.ocr_words_by_page and 0 <= p < len(doc):
                self.ocr_words_by_page[p] = pdf_handler.extract_ocr_words_for_page(doc[p], doc[p])

        self._invalidate_objects_cache(self.page_indices)

        sess = self._get_target_session()
        curr_page = getattr(
            sess, 'current_page_index', getattr(self.window, 'current_page_index', 0)
        )
        if curr_page in self.page_indices and 0 <= curr_page < len(doc):
            extracted_texts, _ = pdf_handler.extract_editable_text(doc, curr_page)
            new_user_texts = [
                t for t in self.pre_editable_texts
                if getattr(t, 'page_number', None) == curr_page and getattr(t, 'is_new', False)
            ]
            combined = list(extracted_texts or []) + copy.deepcopy(new_user_texts)
            for target in ([sess, self.window] if sess else [self.window]):
                if hasattr(target, 'editable_texts'):
                    target.editable_texts = copy.deepcopy(combined)

        if sess is not None:
            sess.is_modified = True
            if hasattr(sess, 'document_modified'):
                sess.document_modified = True
        if hasattr(self.window, 'document_modified'):
            self.window.document_modified = True

        if self._is_session_active():
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
            if hasattr(self.window, 'status_label') and self.window.status_label:
                self.window.status_label.set_text(
                    _("ocr_msg_completed", self.last_result.get("pages_processed", len(self.page_indices)))
                )
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()

    def undo(self):
        doc = self._get_doc()
        if doc is not None:
            for p in self.page_indices:
                if not pdf_handler.restore_pre_ocr_page(doc, p):
                    snap = self.pre_snapshots.get(p)
                    if snap is not None:
                        pdf_handler._page_snapshots[(id(doc), p)] = snap
                        pdf_handler.restore_page_from_snapshot(doc, p)

        self._invalidate_objects_cache(self.page_indices)

        sess = self._get_target_session()
        for target in ([sess, self.window] if sess else [self.window]):
            if hasattr(target, 'editable_texts'):
                target.editable_texts = copy.deepcopy(self.pre_editable_texts)
            if hasattr(target, 'is_modified'):
                target.is_modified = self.pre_document_modified
            if hasattr(target, 'document_modified'):
                target.document_modified = self.pre_document_modified

        if self._is_session_active():
            if hasattr(self.window, '_update_ui_state'):
                self.window._update_ui_state()
            if hasattr(self.window, 'status_label') and self.window.status_label:
                self.window.status_label.set_text(_("reverted"))
            if hasattr(self.window, 'pdf_view') and self.window.pdf_view:
                self.window.pdf_view.queue_draw()
