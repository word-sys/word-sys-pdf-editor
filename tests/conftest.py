"""Test helpers for environments without the Linux PyGObject packages."""

import sys
import types


try:
    import gi  # noqa: F401
except ImportError:
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args: None

    repository = types.ModuleType("gi.repository")

    class _GObjectBase:
        def __init__(self, **properties):
            for name, value in properties.items():
                setattr(self, name, value)

    class _Property:
        def __init__(self, **_kwargs):
            pass

    repository.GObject = types.SimpleNamespace(
        GObject=_GObjectBase,
        Property=_Property,
    )
    repository.GdkPixbuf = types.SimpleNamespace(Pixbuf=object)
    repository.GLib = types.SimpleNamespace(idle_add=lambda callback: callback())

    gi.repository = repository
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
