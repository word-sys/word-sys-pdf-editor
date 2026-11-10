from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import i18n
from .hardware import detect_hardware_spec

DEFAULT_TOOLBAR_TOOLS_ORDER: List[str] = [
    "select",
    "add_text",
    "add_image",
    "redact",
    "add_ellipse",
    "add_rectangle",
    "pen",
    "highlighter",
    "add_checkmark",
    "add_cross",
    "form_builder",
    "add_stamp",
    "measure_distance",
    "measure_area",
    "clone_patch",
    "place_signature",
]

# Metadata for each toolbar tool (icon, i18n label key, i18n tooltip key, shortcut badge)
TOOLBAR_TOOL_METADATA: Dict[str, Dict[str, str]] = {
    "select": {
        "icon": "input-mouse-symbolic",
        "label_key": "tool_select",
        "tip_key": "tool_select_tip",
        "shortcut": "S",
    },
    "add_text": {
        "icon": "insert-text-symbolic",
        "label_key": "tool_add_text",
        "tip_key": "tool_add_text_tip",
        "shortcut": "T",
    },
    "add_image": {
        "icon": "insert-image-symbolic",
        "label_key": "tool_add_image",
        "tip_key": "tool_add_image_tip",
        "shortcut": "I",
    },
    "redact": {
        "icon": "edit-clear-symbolic",
        "label_key": "tool_redact",
        "tip_key": "tool_redact_tip",
        "shortcut": "",
    },
    "add_ellipse": {
        "icon": "media-record-symbolic",
        "label_key": "tool_ellipse",
        "tip_key": "tool_ellipse_tip",
        "shortcut": "E",
    },
    "add_rectangle": {
        "icon": "checkbox-symbolic",
        "label_key": "tool_rectangle",
        "tip_key": "tool_rectangle_tip",
        "shortcut": "R",
    },
    "pen": {
        "icon": "document-edit-symbolic",
        "label_key": "tool_pen",
        "tip_key": "tool_pen_tip",
        "shortcut": "P",
    },
    "highlighter": {
        "icon": "marker-symbolic",
        "label_key": "tool_highlighter",
        "tip_key": "tool_highlighter_tip",
        "shortcut": "H",
    },
    "add_checkmark": {
        "icon": "emblem-ok-symbolic",
        "label_key": "tool_checkmark",
        "tip_key": "tool_checkmark_tip",
        "shortcut": "V",
    },
    "add_cross": {
        "icon": "window-close-symbolic",
        "label_key": "tool_cross",
        "tip_key": "tool_cross_tip",
        "shortcut": "X",
    },
    "form_builder": {
        "icon": "edit-select-all-symbolic",
        "label_key": "tool_form_builder",
        "tip_key": "tool_form_builder_tip",
        "shortcut": "F",
    },
    "add_stamp": {
        "icon": "tag-symbolic",
        "label_key": "tool_stamp",
        "tip_key": "tool_stamp_tip",
        "shortcut": "K",
    },
    "measure_distance": {
        "icon": "straighten-symbolic",
        "label_key": "tool_measure_distance",
        "tip_key": "tool_measure_distance_tip",
        "shortcut": "D",
    },
    "measure_area": {
        "icon": "view-grid-symbolic",
        "label_key": "tool_measure_area",
        "tip_key": "tool_measure_area_tip",
        "shortcut": "A",
    },
    "clone_patch": {
        "icon": "image-crop-symbolic",
        "label_key": "tool_clone_patch",
        "tip_key": "tool_clone_patch_tip",
        "shortcut": "C",
    },
    "place_signature": {
        "icon": "channel-secure-symbolic",
        "label_key": "tool_place_signature",
        "tip_key": "tool_place_signature_tip",
        "shortcut": "G",
    },
}

# Built-in toolbar workflow presets
TOOLBAR_LAYOUT_PRESETS: Dict[str, Dict[str, Any]] = {
    "default": {
        "order": list(DEFAULT_TOOLBAR_TOOLS_ORDER),
        "visible": {tool_id: True for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER},
    },
    "essential": {
        "order": [
            "select",
            "add_text",
            "clone_patch",
            "add_image",
            "redact",
            "add_rectangle",
            "add_ellipse",
            "pen",
            "highlighter",
            "add_checkmark",
            "add_cross",
            "form_builder",
            "add_stamp",
            "measure_distance",
            "measure_area",
            "place_signature",
        ],
        "visible": {
            tool_id: (tool_id in {"select", "add_text", "clone_patch", "add_image"})
            for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER
        },
    },
    "annotation": {
        "order": [
            "select",
            "highlighter",
            "pen",
            "add_text",
            "add_rectangle",
            "add_ellipse",
            "add_stamp",
            "redact",
            "add_checkmark",
            "add_cross",
            "clone_patch",
            "add_image",
            "measure_distance",
            "measure_area",
            "form_builder",
            "place_signature",
        ],
        "visible": {
            tool_id: (
                tool_id
                in {
                    "select",
                    "highlighter",
                    "pen",
                    "add_text",
                    "add_rectangle",
                    "add_ellipse",
                    "add_stamp",
                    "redact",
                }
            )
            for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER
        },
    },
    "forms_signing": {
        "order": [
            "select",
            "form_builder",
            "add_text",
            "add_checkmark",
            "add_cross",
            "place_signature",
            "add_stamp",
            "clone_patch",
            "add_image",
            "redact",
            "add_rectangle",
            "add_ellipse",
            "pen",
            "highlighter",
            "measure_distance",
            "measure_area",
        ],
        "visible": {
            tool_id: (
                tool_id
                in {
                    "select",
                    "form_builder",
                    "add_text",
                    "add_checkmark",
                    "add_cross",
                    "place_signature",
                    "add_stamp",
                }
            )
            for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER
        },
    },
}

# Hamburger menu configurable item keys
HAMBURGER_DOCUMENT_ACTION_KEYS: Tuple[str, ...] = (
    "save_as",
    "compress_document",
    "protect_document",
    "digitally_sign_document",
    "inspect_digital_signatures",
    "merge_documents",
    "flatten_annotations",
    "manage_stamps",
    "sanitize_document",
    "ocr_document",
    "export_submenu",
)

HAMBURGER_INLINE_TOGGLE_KEYS: Tuple[str, ...] = (
    "toggle_continuous_scroll",
    "toggle_eco_mode",
    "toggle_ocr_overlay",
    "toggle_annotations",
    "confirm_delete",
    "auto_switch_to_select",
    "language_submenu",
)

ALL_HAMBURGER_ITEM_KEYS: Tuple[str, ...] = (
    HAMBURGER_DOCUMENT_ACTION_KEYS + HAMBURGER_INLINE_TOGGLE_KEYS
)

VALID_HAMBURGER_PRESETS: Tuple[str, ...] = (
    "standard",
    "minimal",
    "full",
    "custom",
)

HAMBURGER_MENU_PRESETS: Dict[str, Dict[str, bool]] = {
    "minimal": {
        **{k: (k in {"save_as", "export_submenu"}) for k in HAMBURGER_DOCUMENT_ACTION_KEYS},
        **{k: False for k in HAMBURGER_INLINE_TOGGLE_KEYS},
    },
    "standard": {
        **{k: True for k in HAMBURGER_DOCUMENT_ACTION_KEYS},
        **{k: False for k in HAMBURGER_INLINE_TOGGLE_KEYS},
    },
    "full": {
        **{k: True for k in HAMBURGER_DOCUMENT_ACTION_KEYS},
        **{k: True for k in HAMBURGER_INLINE_TOGGLE_KEYS},
    },
}

# SyncTeX external editor presets
SYNCTEX_EDITOR_PRESETS: Dict[str, str] = {
    "vscode": 'code -g "%f:%l"',
    "texstudio": 'texstudio "%f" -line %l',
    "vim": 'gvim --remote-silent +%l "%f"',
    "neovim": 'nvim --headless -c "e +%l %f"',
    "emacs": 'emacsclient --no-wait +%l "%f"',
    "kate": 'kate -l %l "%f"',
    "gedit": 'gedit +%l "%f"',
    "sublime": 'subl "%f:%l"',
}

VALID_SYNCTEX_PRESETS: Tuple[str, ...] = tuple(SYNCTEX_EDITOR_PRESETS.keys()) + ("custom",)


def _detect_default_eco_mode() -> bool:
    try:
        spec = detect_hardware_spec()
        return bool(spec.get("is_low_spec_hardware", False))
    except Exception:
        return False


def get_default_settings() -> Dict[str, Any]:
    """Return a fresh copy of the canonical default configuration dictionary."""
    return {
        "auto_switch_to_select": True,
        "keep_drawing_tools_active": True,
        "confirm_delete": False,
        "continuous_scroll": True,
        "is_eco_mode": _detect_default_eco_mode(),
        "auto_reload_modified_pdf": True,
        "show_ocr_overlay": False,
        "default_font_family": "Liberation Sans",
        "default_font_size": 11.0,
        "hamburger_menu_preset": "standard",
        "hamburger_visible_items": copy.deepcopy(HAMBURGER_MENU_PRESETS["standard"]),
        "toolbar_tools_order": list(DEFAULT_TOOLBAR_TOOLS_ORDER),
        "toolbar_visible_tools": {tool_id: True for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER},
        "synctex_enabled": True,
        "synctex_editor_preset": "vscode",
        "synctex_editor_command": SYNCTEX_EDITOR_PRESETS["vscode"],
    }


def validate_toolbar_tools_order(order: Any) -> List[str]:
    """Validate and normalize toolbar tool ordering so all 16 canonical tools are present once."""
    if not isinstance(order, (list, tuple)):
        return list(DEFAULT_TOOLBAR_TOOLS_ORDER)
    valid_set = set(DEFAULT_TOOLBAR_TOOLS_ORDER)
    normalized: List[str] = []
    seen = set()
    for item in order:
        if isinstance(item, str) and item in valid_set and item not in seen:
            normalized.append(item)
            seen.add(item)
    for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER:
        if tool_id not in seen:
            normalized.append(tool_id)
            seen.add(tool_id)
    return normalized


def validate_toolbar_visible_tools(visible: Any) -> Dict[str, bool]:
    """Validate toolbar tool visibility map, ensuring 'select' is always visible."""
    result = {tool_id: True for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER}
    if isinstance(visible, dict):
        for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER:
            if tool_id in visible:
                result[tool_id] = bool(visible[tool_id])
    result["select"] = True
    return result


def validate_hamburger_visible_items(items: Any, preset: str = "standard") -> Dict[str, bool]:
    """Validate hamburger menu item visibility map."""
    base_preset = preset if preset in HAMBURGER_MENU_PRESETS else "standard"
    result = copy.deepcopy(HAMBURGER_MENU_PRESETS[base_preset])
    if isinstance(items, dict):
        for key in ALL_HAMBURGER_ITEM_KEYS:
            if key in items:
                result[key] = bool(items[key])
    return result


def validate_setting_value(key: str, value: Any) -> Any:
    """Validate and coerce a configuration value according to the canonical schema."""
    if key in {
        "auto_switch_to_select",
        "keep_drawing_tools_active",
        "confirm_delete",
        "confirm_delete_objects",
        "continuous_scroll",
        "is_eco_mode",
        "auto_reload_modified_pdf",
        "show_ocr_overlay",
        "synctex_enabled",
    }:
        return bool(value)

    if key == "default_font_family":
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "Liberation Sans"

    if key == "default_font_size":
        try:
            fval = float(value)
            return max(4.0, min(144.0, fval))
        except (TypeError, ValueError):
            return 11.0

    if key == "hamburger_menu_preset":
        if isinstance(value, str) and value in VALID_HAMBURGER_PRESETS:
            return value
        return "standard"

    if key == "hamburger_visible_items":
        return validate_hamburger_visible_items(value)

    if key == "toolbar_tools_order":
        return validate_toolbar_tools_order(value)

    if key == "toolbar_visible_tools":
        return validate_toolbar_visible_tools(value)

    if key == "synctex_editor_preset":
        if isinstance(value, str) and value in VALID_SYNCTEX_PRESETS:
            return value
        return "vscode"

    if key == "synctex_editor_command":
        if isinstance(value, str) and value.strip():
            return value.strip()
        return SYNCTEX_EDITOR_PRESETS["vscode"]

    return value


class SettingsManager:
    """Schema-validated configuration manager with atomic JSON persistence and change listeners."""

    def __init__(self, config_file: Optional[Path] = None):
        self._config_file: Optional[Path] = Path(config_file) if config_file else None
        self._listeners: Dict[Optional[str], List[Callable[[str, Any], None]]] = {}
        self._defaults: Dict[str, Any] = get_default_settings()
        if self._config_file is not None:
            self._custom_store: Dict[str, Any] = self._load_from_file(self._config_file)
        else:
            self._custom_store = None

    @property
    def config_file(self) -> Path:
        if self._config_file is not None:
            return self._config_file
        return i18n._CONFIG_FILE

    def _get_backing_store(self) -> Dict[str, Any]:
        if self._custom_store is not None:
            return self._custom_store
        return i18n._settings

    def _load_from_file(self, path: Path) -> Dict[str, Any]:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception:
            pass
        return {}

    def _save_backing_store(self) -> None:
        store = self._get_backing_store()
        if self._config_file is None:
            i18n._save_settings(store)
            return
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self._config_file.parent / f".{self._config_file.name}.tmp.{os.getpid()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self._config_file)
        except Exception as e:
            print(f"Warning: Could not save settings to {self._config_file}: {e}")

    def reload(self) -> None:
        """Reload configuration from disk into the backing store."""
        loaded = self._load_from_file(self.config_file)
        store = self._get_backing_store()
        store.clear()
        store.update(loaded)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a validated setting value, resolving legacy aliases and schema defaults."""
        store = self._get_backing_store()

        # Resolve legacy / cross-key aliases
        if key == "confirm_delete":
            if "confirm_delete" in store:
                return validate_setting_value("confirm_delete", store["confirm_delete"])
            if "confirm_delete_objects" in store:
                return validate_setting_value("confirm_delete", store["confirm_delete_objects"])
            return self._defaults["confirm_delete"] if default is None else bool(default)

        if key == "confirm_delete_objects":
            if "confirm_delete_objects" in store:
                return validate_setting_value("confirm_delete_objects", store["confirm_delete_objects"])
            if "confirm_delete" in store:
                return validate_setting_value("confirm_delete_objects", store["confirm_delete"])
            return True if default is None else bool(default)

        if key == "continuous_scroll":
            if "continuous_scroll" in store:
                return validate_setting_value("continuous_scroll", store["continuous_scroll"])
            if "view_mode" in store:
                return store["view_mode"] == "continuous"
            return self._defaults["continuous_scroll"] if default is None else bool(default)

        if key == "is_eco_mode":
            if "is_eco_mode" in store and store["is_eco_mode"] is not None:
                return validate_setting_value("is_eco_mode", store["is_eco_mode"])
            if "eco_mode" in store and store["eco_mode"] is not None:
                return validate_setting_value("is_eco_mode", store["eco_mode"])
            return _detect_default_eco_mode() if default is None else bool(default)

        if key == "hamburger_visible_items":
            preset = self.get("hamburger_menu_preset", "standard")
            if preset in HAMBURGER_MENU_PRESETS and "hamburger_visible_items" not in store:
                return copy.deepcopy(HAMBURGER_MENU_PRESETS[preset])
            raw_items = store.get("hamburger_visible_items")
            return validate_hamburger_visible_items(raw_items, preset=preset)

        if key == "toolbar_tools_order":
            if "toolbar_tools_order" in store:
                return validate_toolbar_tools_order(store["toolbar_tools_order"])
            return list(DEFAULT_TOOLBAR_TOOLS_ORDER)

        if key == "toolbar_visible_tools":
            if "toolbar_visible_tools" in store:
                return validate_toolbar_visible_tools(store["toolbar_visible_tools"])
            return {tool_id: True for tool_id in DEFAULT_TOOLBAR_TOOLS_ORDER}

        if key in store:
            return validate_setting_value(key, store[key])

        if key in self._defaults:
            return copy.deepcopy(self._defaults[key])

        return default

    def set(self, key: str, value: Any, notify: bool = True) -> Any:
        """Validate, persist, and broadcast a setting update."""
        store = self._get_backing_store()
        validated = validate_setting_value(key, value)

        if key in ("confirm_delete", "confirm_delete_objects"):
            store["confirm_delete"] = validated
            store["confirm_delete_objects"] = validated
            self._save_backing_store()
            if notify:
                self._notify_listeners("confirm_delete", validated)
                if key != "confirm_delete":
                    self._notify_listeners("confirm_delete_objects", validated)
            return validated

        if key == "continuous_scroll":
            store["continuous_scroll"] = validated
            store["view_mode"] = "continuous" if validated else "single"
            self._save_backing_store()
            if notify:
                self._notify_listeners("continuous_scroll", validated)
            return validated

        if key == "is_eco_mode":
            store["is_eco_mode"] = validated
            store["eco_mode"] = validated
            self._save_backing_store()
            if notify:
                self._notify_listeners("is_eco_mode", validated)
            return validated

        if key == "hamburger_menu_preset":
            store["hamburger_menu_preset"] = validated
            if validated in HAMBURGER_MENU_PRESETS:
                preset_items = copy.deepcopy(HAMBURGER_MENU_PRESETS[validated])
                store["hamburger_visible_items"] = preset_items
            self._save_backing_store()
            if notify:
                self._notify_listeners("hamburger_menu_preset", validated)
                if validated in HAMBURGER_MENU_PRESETS:
                    self._notify_listeners(
                        "hamburger_visible_items",
                        copy.deepcopy(store["hamburger_visible_items"]),
                    )
            return validated

        if key == "hamburger_visible_items":
            store["hamburger_visible_items"] = copy.deepcopy(validated)
            matched_preset = "custom"
            for preset_name, preset_map in HAMBURGER_MENU_PRESETS.items():
                if validated == preset_map:
                    matched_preset = preset_name
                    break
            store["hamburger_menu_preset"] = matched_preset
            self._save_backing_store()
            if notify:
                self._notify_listeners("hamburger_visible_items", copy.deepcopy(validated))
                self._notify_listeners("hamburger_menu_preset", matched_preset)
            return validated

        if key == "synctex_editor_preset":
            store["synctex_editor_preset"] = validated
            if validated in SYNCTEX_EDITOR_PRESETS:
                cmd = SYNCTEX_EDITOR_PRESETS[validated]
                store["synctex_editor_command"] = cmd
            self._save_backing_store()
            if notify:
                self._notify_listeners("synctex_editor_preset", validated)
                if validated in SYNCTEX_EDITOR_PRESETS:
                    self._notify_listeners("synctex_editor_command", store["synctex_editor_command"])
            return validated

        store[key] = copy.deepcopy(validated)
        self._save_backing_store()
        if notify:
            self._notify_listeners(key, copy.deepcopy(validated))
        return validated

    def update(self, mapping: Dict[str, Any], notify: bool = True) -> None:
        """Batch-update multiple settings atomically."""
        if not isinstance(mapping, dict):
            return
        for k, v in mapping.items():
            self.set(k, v, notify=notify)

    def apply_toolbar_preset(self, preset_name: str, notify: bool = True) -> bool:
        """Apply one of the named toolbar layout presets ('default', 'essential', 'annotation', 'forms_signing')."""
        if preset_name not in TOOLBAR_LAYOUT_PRESETS:
            return False
        preset = TOOLBAR_LAYOUT_PRESETS[preset_name]
        self.set("toolbar_tools_order", list(preset["order"]), notify=notify)
        self.set("toolbar_visible_tools", dict(preset["visible"]), notify=notify)
        return True

    def reset_toolbar_to_default(self, notify: bool = True) -> None:
        """Restore toolbar tool ordering and visibility to factory defaults."""
        self.apply_toolbar_preset("default", notify=notify)

    def reset_to_defaults(self, preserve_language: bool = True, notify: bool = True) -> None:
        """Reset all preferences to canonical defaults."""
        store = self._get_backing_store()
        saved_lang = store.get("language")
        defaults = get_default_settings()
        store.clear()
        if preserve_language and saved_lang:
            store["language"] = saved_lang
        for k, v in defaults.items():
            store[k] = copy.deepcopy(v)
        store["confirm_delete_objects"] = defaults["confirm_delete"]
        store["view_mode"] = "continuous" if defaults["continuous_scroll"] else "single"
        store["eco_mode"] = defaults["is_eco_mode"]
        self._save_backing_store()
        if notify:
            for k, v in defaults.items():
                self._notify_listeners(k, copy.deepcopy(v))

    def get_all(self) -> Dict[str, Any]:
        """Return a complete validated dictionary of all canonical settings."""
        return {k: self.get(k) for k in self._defaults}

    def subscribe(
        self,
        callback: Callable[[str, Any], None],
        key: Optional[str] = None,
    ) -> Callable[[], None]:
        """Register a listener callback for a specific setting key or all keys (key=None).

        Returns an unsubscribe callable.
        """
        bucket = self._listeners.setdefault(key, [])
        if callback not in bucket:
            bucket.append(callback)

        def _unsubscribe() -> None:
            self.unsubscribe(callback, key=key)

        return _unsubscribe

    add_listener = subscribe

    def unsubscribe(
        self,
        callback: Callable[[str, Any], None],
        key: Optional[str] = None,
    ) -> None:
        """Remove a previously registered listener callback."""
        bucket = self._listeners.get(key)
        if bucket and callback in bucket:
            bucket.remove(callback)

    remove_listener = unsubscribe

    def _notify_listeners(self, key: str, value: Any) -> None:
        specific = list(self._listeners.get(key, []))
        wildcard = list(self._listeners.get(None, []))
        for cb in specific + wildcard:
            try:
                cb(key, value)
            except Exception as e:
                print(f"Warning: Settings listener error for '{key}': {e}")


_default_manager: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    """Return the process-wide singleton SettingsManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = SettingsManager()
    return _default_manager


def get_pref(key: str, default: Any = None) -> Any:
    """Convenience wrapper around get_settings_manager().get(key, default)."""
    return get_settings_manager().get(key, default)


def set_pref(key: str, value: Any, notify: bool = True) -> Any:
    """Convenience wrapper around get_settings_manager().set(key, value, notify=notify)."""
    return get_settings_manager().set(key, value, notify=notify)
