"""Command-line entry point: sync (from the QuodLibet export), match
(scan Music - New), status, and review (launch the GTK4 UI).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, matcher
from .config import DEFAULT_CONFIG_PATH, Config


def _load_config(args: argparse.Namespace) -> Config:
    path = Path(args.config).expanduser() if args.config else None
    return Config.load(path)


def cmd_sync(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if not config.scope_export_path.exists():
        print(f"No scope export found at {config.scope_export_path}.")
        print("Enable and run the 'Export Upgrade Scope' QuodLibet plugin first.")
        return 1

    conn = db.connect(config.db_path)
    result = db.sync_tracks_from_export(
        conn,
        config.scope_export_path,
        scope_ratings=config.scope_ratings,
        upgrade_formats=config.upgrade_formats,
        min_bitrate_kbps=config.min_bitrate_kbps,
    )
    print(f"Sync: {result.added} added, {result.updated} updated, {result.out_of_scope} dropped out of scope")
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    config = _load_config(args)
    conn = db.connect(config.db_path)
    summary = matcher.run_matching(conn, config)
    print(f"Match: {summary['matched']} matched, {summary['no_candidate']} with no candidate")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = _load_config(args)
    conn = db.connect(config.db_path)
    counts: dict[str, int] = {}
    for row in db.get_scope_tracks(conn):
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    if not counts:
        print("No tracks in scope yet — run 'sync' first.")
        return 0
    for status, count in sorted(counts.items()):
        print(f"{status:>14}: {count}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    config = _load_config(args)
    conn = db.connect(config.db_path)
    from .ui.review_window import run as run_ui  # deferred: only 'review' needs GTK

    return run_ui(conn, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="music-upgrade",
        description="Match and replace low-bitrate library tracks with 320kbps/FLAC upgrades.",
    )
    parser.add_argument("--config", help=f"Path to config.toml (default: {DEFAULT_CONFIG_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="Sync scope from the QuodLibet export").set_defaults(func=cmd_sync)
    sub.add_parser("match", help="Scan Music - New and match candidates against tracks in scope").set_defaults(
        func=cmd_match
    )
    sub.add_parser("status", help="Show track counts by status").set_defaults(func=cmd_status)
    sub.add_parser("review", help="Open the batch review UI").set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
