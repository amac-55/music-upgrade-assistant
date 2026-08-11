# Copy this file to ~/.quodlibet/plugins/scope_export.py, then enable
# "Export Upgrade Scope" under Music > Plugins in QuodLibet.
#
# Exports the library (path, tags, rating, format, bitrate, length) to a
# JSON file the Music Library Upgrade Assistant reads on each sync. Runs
# automatically whenever the library changes, and on demand via the
# "Export Now" button in this plugin's preferences pane.
#
# Verified against quodlibet/quodlibet on GitHub (main branch, Aug 2026):
# EventPlugin hook names (quodlibet/plugins/events.py), app.library access
# pattern (quodlibet/ext/events/searchprovider.py), and the ~#bitrate
# (kbps), ~#length (seconds), ~#rating (0.0-1.0), ~format (e.g. "FLAC",
# "MP3") tag semantics (quodlibet/formats/_audio.py, mp3.py, xiph.py).

from __future__ import annotations

import json
from pathlib import Path

from gi.repository import Gtk

from quodlibet import _, app, print_w
from quodlibet.plugins import ConfProp, PluginConfig
from quodlibet.plugins.events import EventPlugin
from quodlibet.qltk import Icons

DEFAULT_EXPORT_PATH = str(
    Path.home() / ".local" / "share" / "music-upgrade-assistant" / "quodlibet-scope.json"
)

_config = PluginConfig("upgrade_scope_export")


class _Config:
    export_path = ConfProp(_config, "export_path", DEFAULT_EXPORT_PATH)


CONFIG = _Config()


def export_library(library, path_str: str) -> int:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    entries = [
        {
            "path": song("~filename"),
            "artist": song("artist") or None,
            "title": song("title") or None,
            "album": song("album") or None,
            "tracknumber": song("tracknumber") or None,
            "rating": song("~#rating"),
            "format": (song("~format") or "").lower(),
            "bitrate": song("~#bitrate"),
            "length": song("~#length"),
        }
        for song in library
    ]

    # Write to a temp file and rename over the target so a reader on the
    # other end (polling for the file to reappear) never sees a half
    # written JSON file.
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(entries))
    tmp_path.replace(path)
    return len(entries)


class UpgradeScopeExport(EventPlugin):
    PLUGIN_ID = "upgrade_scope_export"
    PLUGIN_NAME = _("Export Upgrade Scope")
    PLUGIN_DESC = _(
        "Exports the library to a JSON file for the Music Library Upgrade "
        "Assistant. Runs whenever the library changes, or on demand below."
    )
    PLUGIN_ICON = Icons.DOCUMENT_SAVE

    def plugin_on_added(self, songs):
        self._export()

    def plugin_on_changed(self, songs):
        self._export()

    def plugin_on_removed(self, songs):
        self._export()

    def _export(self):
        try:
            export_library(app.library, CONFIG.export_path)
        except OSError as e:
            print_w(f"[upgrade_scope_export] export failed: {e}")

    def PluginPreferences(self, _parent):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        path_label = Gtk.Label(label=_("Export file path:"))
        path_label.set_xalign(0.0)

        entry = Gtk.Entry()
        entry.set_text(CONFIG.export_path)
        entry.set_width_chars(56)

        def path_changed(widget):
            CONFIG.export_path = widget.get_text()

        entry.connect("changed", path_changed)

        status_label = Gtk.Label(label="")
        status_label.set_xalign(0.0)

        def export_now(_button):
            try:
                count = export_library(app.library, CONFIG.export_path)
                status_label.set_text(_("Exported %d tracks.") % count)
            except OSError as e:
                status_label.set_text(_("Export failed: %s") % e)

        button = Gtk.Button(label=_("Export Now"))
        button.connect("clicked", export_now)

        box.pack_start(path_label, False, False, 0)
        box.pack_start(entry, False, False, 0)
        box.pack_start(button, False, False, 0)
        box.pack_start(status_label, False, False, 0)
        box.show_all()
        return box
