"""SQLite storage for the app's own state.

QuodLibet remains the source of truth for ratings; this DB is the source of
truth for *replacement progress* — what's in scope, what candidates were
found, what's been approved and applied. A re-sync from the QuodLibet scope
export (see quodlibet-plugin/scope_export.py) refreshes tag/rating data but
never overwrites a row already marked ``replaced`` or ``skipped``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Ratings QuodLibet stores for 3 and 4 stars, out of its default 4-star scale.
SCOPE_RATINGS_PHASE1 = (0.75, 1.0)

_ACTIVE_STATUSES = ("pending", "matched", "approved")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id              INTEGER PRIMARY KEY,
    old_path        TEXT UNIQUE NOT NULL,
    artist          TEXT,
    title           TEXT,
    album           TEXT,
    tracknumber     TEXT,
    rating          REAL,
    old_format      TEXT,
    old_bitrate     INTEGER,
    duration_sec    REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    last_synced_at  TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id              INTEGER PRIMARY KEY,
    track_id        INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    new_path        TEXT NOT NULL,
    new_format      TEXT,
    new_bitrate     INTEGER,
    match_score     REAL,
    match_basis     TEXT,
    discovered_at   TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id                INTEGER PRIMARY KEY,
    track_id          INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    candidate_id      INTEGER REFERENCES candidates(id),
    old_backup_path   TEXT,
    new_final_path    TEXT,
    approved_at       TEXT,
    applied_at        TEXT,
    result            TEXT
);

CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
CREATE INDEX IF NOT EXISTS idx_candidates_track ON candidates(track_id);
CREATE INDEX IF NOT EXISTS idx_actions_track ON actions(track_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    out_of_scope: int = 0


def sync_tracks_from_export(
    conn: sqlite3.Connection,
    export_path: Path,
    scope_ratings: tuple[float, ...] = SCOPE_RATINGS_PHASE1,
    upgrade_formats: tuple[str, ...] = ("flac", "mp3"),
    min_bitrate_kbps: int = 320,
) -> SyncResult:
    """Merge a QuodLibet scope export (JSON) into the tracks table.

    A library entry is in scope if its rating matches ``scope_ratings`` and
    it is *not already* an upgraded file (i.e. not FLAC, and not MP3 at or
    above ``min_bitrate_kbps`` already).
    """
    entries = json.loads(export_path.read_text())
    result = SyncResult()
    now = _now()
    seen_paths: set[str] = set()

    for entry in entries:
        rating = entry.get("rating")
        if rating not in scope_ratings:
            continue

        fmt = (entry.get("format") or "").lower()
        bitrate = entry.get("bitrate") or 0
        already_upgraded = fmt == "flac" or (fmt == "mp3" and bitrate >= min_bitrate_kbps)
        if already_upgraded:
            continue

        path = entry["path"]
        seen_paths.add(path)
        row = conn.execute("SELECT id, status FROM tracks WHERE old_path = ?", (path,)).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO tracks
                   (old_path, artist, title, album, tracknumber, rating,
                    old_format, old_bitrate, duration_sec, status, last_synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    path, entry.get("artist"), entry.get("title"), entry.get("album"),
                    entry.get("tracknumber"), rating, fmt, bitrate,
                    entry.get("length"), now,
                ),
            )
            result.added += 1
        elif row["status"] not in ("replaced", "skipped"):
            conn.execute(
                """UPDATE tracks SET artist=?, title=?, album=?, tracknumber=?,
                   rating=?, old_format=?, old_bitrate=?, duration_sec=?,
                   last_synced_at=? WHERE id=?""",
                (
                    entry.get("artist"), entry.get("title"), entry.get("album"),
                    entry.get("tracknumber"), rating, fmt, bitrate,
                    entry.get("length"), now, row["id"],
                ),
            )
            result.updated += 1

    # Anything previously in scope that's no longer in this export (rating
    # dropped, file removed) and hasn't been acted on yet drops out of scope.
    placeholders = ",".join("?" * len(seen_paths)) if seen_paths else "''"
    stale = conn.execute(
        f"""SELECT id FROM tracks
            WHERE status IN ({",".join("?" * len(_ACTIVE_STATUSES))})
            AND old_path NOT IN ({placeholders})""",
        (*_ACTIVE_STATUSES, *seen_paths),
    ).fetchall()
    for r in stale:
        conn.execute("UPDATE tracks SET status='out_of_scope' WHERE id=?", (r["id"],))
        result.out_of_scope += 1

    conn.commit()
    return result


def clear_candidates(conn: sqlite3.Connection, track_id: int) -> None:
    conn.execute("DELETE FROM candidates WHERE track_id = ?", (track_id,))


def add_candidate(
    conn: sqlite3.Connection,
    track_id: int,
    new_path: str,
    new_format: str,
    new_bitrate: int,
    match_score: float,
    match_basis: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO candidates (track_id, new_path, new_format, new_bitrate,
           match_score, match_basis, discovered_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (track_id, new_path, new_format, new_bitrate, match_score, match_basis, _now()),
    )
    return cur.lastrowid


def get_scope_tracks(conn: sqlite3.Connection, statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
    if statuses is None:
        return conn.execute("SELECT * FROM tracks ORDER BY artist, album, tracknumber").fetchall()
    placeholders = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT * FROM tracks WHERE status IN ({placeholders}) ORDER BY artist, album, tracknumber",
        statuses,
    ).fetchall()


def get_candidates(conn: sqlite3.Connection, track_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM candidates WHERE track_id = ? ORDER BY match_score DESC", (track_id,)
    ).fetchall()


def set_track_status(conn: sqlite3.Connection, track_id: int, status: str) -> None:
    conn.execute("UPDATE tracks SET status = ? WHERE id = ?", (status, track_id))
    conn.commit()


def record_action(
    conn: sqlite3.Connection,
    track_id: int,
    candidate_id: int,
    old_backup_path: str,
    new_final_path: str,
    result: str,
) -> int:
    now = _now()
    cur = conn.execute(
        """INSERT INTO actions (track_id, candidate_id, old_backup_path,
           new_final_path, approved_at, applied_at, result)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (track_id, candidate_id, old_backup_path, new_final_path, now, now, result),
    )
    conn.commit()
    return cur.lastrowid
