import json
from pathlib import Path

import pytest

from musicupgrade import db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "library.db")


def write_export(tmp_path, entries) -> Path:
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(entries))
    return path


def entry(path, rating=0.75, fmt="mp3", bitrate=192, **kw):
    base = {
        "path": path, "artist": "Queen", "title": "Bohemian Rhapsody", "album": "A Night at the Opera",
        "tracknumber": "1", "rating": rating, "format": fmt, "bitrate": bitrate, "length": 240.0,
    }
    base.update(kw)
    return base


def test_sync_adds_in_scope_tracks(conn, tmp_path):
    export = write_export(tmp_path, [entry("/music/a.mp3")])

    result = db.sync_tracks_from_export(conn, export)

    assert result.added == 1
    rows = db.get_scope_tracks(conn)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["rating"] == 0.75


def test_sync_skips_already_upgraded_files(conn, tmp_path):
    export = write_export(tmp_path, [
        entry("/music/flac-already.flac", fmt="flac", bitrate=1000),
        entry("/music/mp3-already-320.mp3", fmt="mp3", bitrate=320),
        entry("/music/low-rating.mp3", rating=0.5),
    ])

    db.sync_tracks_from_export(conn, export)

    assert db.get_scope_tracks(conn) == []


def test_sync_never_overwrites_replaced_rows(conn, tmp_path):
    export = write_export(tmp_path, [entry("/music/a.mp3")])
    db.sync_tracks_from_export(conn, export)
    track_id = db.get_scope_tracks(conn)[0]["id"]
    db.set_track_status(conn, track_id, "replaced")

    export2 = write_export(tmp_path, [entry("/music/a.mp3", title="Changed Title")])
    db.sync_tracks_from_export(conn, export2)

    row = db.get_scope_tracks(conn, statuses=("replaced",))[0]
    assert row["title"] == "Bohemian Rhapsody"


def test_sync_marks_out_of_scope_when_dropped_from_export(conn, tmp_path):
    export = write_export(tmp_path, [entry("/music/a.mp3")])
    db.sync_tracks_from_export(conn, export)

    export2 = write_export(tmp_path, [])
    result = db.sync_tracks_from_export(conn, export2)

    assert result.out_of_scope == 1
    row = db.get_scope_tracks(conn, statuses=("out_of_scope",))[0]
    assert row["old_path"] == "/music/a.mp3"


def test_candidates_roundtrip(conn, tmp_path):
    export = write_export(tmp_path, [entry("/music/a.mp3")])
    db.sync_tracks_from_export(conn, export)
    track_id = db.get_scope_tracks(conn)[0]["id"]

    db.add_candidate(conn, track_id, "/new/a.flac", "flac", 1000, 97.5, "exact_tag")
    conn.commit()

    candidates = db.get_candidates(conn, track_id)
    assert len(candidates) == 1
    assert candidates[0]["new_path"] == "/new/a.flac"

    db.clear_candidates(conn, track_id)
    assert db.get_candidates(conn, track_id) == []
