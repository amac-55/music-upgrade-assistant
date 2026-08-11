"""GTK4 batch review UI: one table of matched tracks, a detail pane for
overriding a match or skipping a track, and a single gated "Apply Approved"
action. This module needs GTK4 + PyGObject, which is only available on the
Linux Mint target machine — it can't be run or visually tested from here.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import db, matcher, replace  # noqa: E402
from ..config import Config  # noqa: E402

(
    COL_CHECKED,
    COL_OLD,
    COL_OLD_FMT,
    COL_NEW,
    COL_NEW_FMT,
    COL_SCORE,
    COL_BASIS,
    COL_TRACK_ID,
    COL_CANDIDATE_ID,
) = range(9)


def _fmt_score(score: float) -> str:
    return f"{score:.1f}%"


def _fmt_quality(fmt: str | None, bitrate: int | None) -> str:
    return f"{(fmt or '?').upper()} {bitrate or 0}kbps"


class ReviewWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, conn, config: Config):
        super().__init__(application=app, title="Music Library Upgrade Assistant")
        self.conn = conn
        self.config = config
        self.set_default_size(1040, 640)

        self._build_ui()
        self.reload_rows()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        dry_run_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dry_run_label = Gtk.Label(label="Dry run")
        self.dry_run_switch = Gtk.Switch()
        self.dry_run_switch.set_active(True)
        dry_run_box.append(dry_run_label)
        dry_run_box.append(self.dry_run_switch)
        header.pack_start(dry_run_box)

        rescan_button = Gtk.Button(label="Rescan Music - New")
        rescan_button.connect("clicked", self.on_rescan)
        header.pack_start(rescan_button)

        apply_button = Gtk.Button(label="Apply Approved")
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", self.on_apply)
        header.pack_end(apply_button)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(720)
        root.append(paned)

        paned.set_start_child(self._build_table())
        paned.set_end_child(self._build_detail_pane())

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0.0)
        self.status_label.set_margin_top(6)
        self.status_label.set_margin_bottom(6)
        self.status_label.set_margin_start(12)
        root.append(self.status_label)

    def _build_table(self) -> Gtk.Widget:
        # bool checked | old track | old quality | candidate | new quality |
        # score | basis | track_id | candidate_id
        self.store = Gtk.ListStore(bool, str, str, str, str, str, str, int, int)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.get_selection().connect("changed", self.on_selection_changed)

        toggle_renderer = Gtk.CellRendererToggle()
        toggle_renderer.connect("toggled", self.on_toggle)
        self.tree.append_column(Gtk.TreeViewColumn("", toggle_renderer, active=COL_CHECKED))
        self.tree.append_column(Gtk.TreeViewColumn("Old track", Gtk.CellRendererText(), text=COL_OLD))
        self.tree.append_column(Gtk.TreeViewColumn("Old quality", Gtk.CellRendererText(), text=COL_OLD_FMT))
        self.tree.append_column(Gtk.TreeViewColumn("Candidate", Gtk.CellRendererText(), text=COL_NEW))
        self.tree.append_column(Gtk.TreeViewColumn("New quality", Gtk.CellRendererText(), text=COL_NEW_FMT))
        self.tree.append_column(Gtk.TreeViewColumn("Confidence", Gtk.CellRendererText(), text=COL_SCORE))
        self.tree.append_column(Gtk.TreeViewColumn("Basis", Gtk.CellRendererText(), text=COL_BASIS))

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.tree)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        return scroller

    def _build_detail_pane(self) -> Gtk.Widget:
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detail.set_margin_top(12)
        detail.set_margin_bottom(12)
        detail.set_margin_start(12)
        detail.set_margin_end(12)
        detail.set_size_request(300, -1)

        self.detail_title = Gtk.Label(label="Select a row")
        self.detail_title.set_xalign(0.0)
        self.detail_title.set_wrap(True)
        detail.append(self.detail_title)

        self.detail_tags = Gtk.Label(label="")
        self.detail_tags.set_xalign(0.0)
        self.detail_tags.set_wrap(True)
        detail.append(self.detail_tags)

        override_label = Gtk.Label(label="Use a different candidate:")
        override_label.set_xalign(0.0)
        detail.append(override_label)

        self.candidate_combo = Gtk.ComboBoxText()
        self.candidate_combo.connect("changed", self.on_candidate_override)
        detail.append(self.candidate_combo)

        skip_button = Gtk.Button(label="Skip this track")
        skip_button.connect("clicked", self.on_skip)
        detail.append(skip_button)

        return detail

    # ---------------------------------------------------------- data load

    def reload_rows(self) -> None:
        self.store.clear()
        for track in db.get_scope_tracks(self.conn, statuses=("matched",)):
            candidates = db.get_candidates(self.conn, track["id"])
            if not candidates:
                continue
            best = candidates[0]
            checked = best["match_score"] >= self.config.auto_check_confidence
            self.store.append(
                [
                    checked,
                    f"{track['artist'] or '?'} - {track['title'] or '?'}",
                    _fmt_quality(track["old_format"], track["old_bitrate"]),
                    Path(best["new_path"]).name,
                    _fmt_quality(best["new_format"], best["new_bitrate"]),
                    _fmt_score(best["match_score"]),
                    best["match_basis"],
                    track["id"],
                    best["id"],
                ]
            )
        self._update_status()

    def _update_status(self, extra: str = "") -> None:
        total = len(self.store)
        checked = sum(1 for row in self.store if row[COL_CHECKED])
        text = f"{checked} of {total} checked"
        if extra:
            text = f"{extra} — {text}"
        self.status_label.set_text(text)

    # ------------------------------------------------------------ events

    def on_toggle(self, _renderer, path) -> None:
        self.store[path][COL_CHECKED] = not self.store[path][COL_CHECKED]
        self._update_status()

    def on_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, treeiter = selection.get_selected()
        if treeiter is None:
            self.detail_title.set_text("Select a row")
            self.detail_tags.set_text("")
            self.candidate_combo.remove_all()
            return

        track_id = model[treeiter][COL_TRACK_ID]
        track = self.conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        self.detail_title.set_text(f"{track['artist']} — {track['title']}")
        self.detail_tags.set_text(
            f"Album: {track['album'] or '(none)'}\n"
            f"Old file: {track['old_path']}\n"
            f"{_fmt_quality(track['old_format'], track['old_bitrate'])}, "
            f"rating {track['rating']}"
        )

        self.candidate_combo.handler_block_by_func(self.on_candidate_override)
        self.candidate_combo.remove_all()
        current_candidate_id = model[treeiter][COL_CANDIDATE_ID]
        active_index = 0
        for i, c in enumerate(db.get_candidates(self.conn, track_id)):
            label = (
                f"{Path(c['new_path']).name}  "
                f"({_fmt_quality(c['new_format'], c['new_bitrate'])}, {_fmt_score(c['match_score'])})"
            )
            self.candidate_combo.append(str(c["id"]), label)
            if c["id"] == current_candidate_id:
                active_index = i
        self.candidate_combo.set_active(active_index)
        self.candidate_combo.handler_unblock_by_func(self.on_candidate_override)

    def on_candidate_override(self, combo: Gtk.ComboBoxText) -> None:
        model, treeiter = self.tree.get_selection().get_selected()
        if treeiter is None:
            return
        candidate_id_str = combo.get_active_id()
        if candidate_id_str is None:
            return

        candidate = self.conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (int(candidate_id_str),)
        ).fetchone()
        model[treeiter][COL_NEW] = Path(candidate["new_path"]).name
        model[treeiter][COL_NEW_FMT] = _fmt_quality(candidate["new_format"], candidate["new_bitrate"])
        model[treeiter][COL_SCORE] = _fmt_score(candidate["match_score"])
        model[treeiter][COL_BASIS] = candidate["match_basis"]
        model[treeiter][COL_CANDIDATE_ID] = candidate["id"]

    def on_skip(self, _button: Gtk.Button) -> None:
        model, treeiter = self.tree.get_selection().get_selected()
        if treeiter is None:
            return
        track_id = model[treeiter][COL_TRACK_ID]
        db.set_track_status(self.conn, track_id, "skipped")
        self.conn.commit()
        model.remove(treeiter)
        self._update_status()

    def on_rescan(self, _button: Gtk.Button) -> None:
        summary = matcher.run_matching(self.conn, self.config)
        self.reload_rows()
        self._update_status(f"Rescanned: {summary['matched']} matched, {summary['no_candidate']} no candidate")

    def on_apply(self, _button: Gtk.Button) -> None:
        approvals = [(row[COL_TRACK_ID], row[COL_CANDIDATE_ID]) for row in self.store if row[COL_CHECKED]]
        if not approvals:
            self._update_status("Nothing checked")
            return

        dry_run = self.dry_run_switch.get_active()
        verb = "Preview" if dry_run else "Replace"
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"{verb} {len(approvals)} track(s)?",
            secondary_text=(
                "Dry run — no files will be touched."
                if dry_run
                else "Originals are archived, not deleted, but this moves and retags files on disk."
            ),
        )
        dialog.connect("response", self._on_apply_confirmed, approvals, dry_run)
        dialog.present()

    def _on_apply_confirmed(
        self, dialog: Gtk.MessageDialog, response: int, approvals: list[tuple[int, int]], dry_run: bool
    ) -> None:
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return

        outcomes = replace.run_batch(self.conn, approvals, self.config, dry_run=dry_run)
        ok = sum(1 for o in outcomes if o.ok)
        failed = len(outcomes) - ok

        if dry_run:
            self._update_status(f"Dry run: {ok} would apply, {failed} would fail")
        else:
            self._update_status(f"Applied: {ok} replaced, {failed} failed")
            self.reload_rows()


class ReviewApp(Gtk.Application):
    def __init__(self, conn, config: Config):
        super().__init__(application_id="net.amac.music_upgrade_assistant")
        self.conn = conn
        self.config = config

    def do_activate(self) -> None:
        win = ReviewWindow(self, self.conn, self.config)
        win.present()


def run(conn, config: Config) -> int:
    app = ReviewApp(conn, config)
    # Deliberately not sys.argv: that still holds our own CLI's leftover
    # positional args (e.g. "review"), which GApplication would otherwise
    # try to interpret as files to open.
    return app.run(None)
