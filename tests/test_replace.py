from pathlib import Path

import mutagen
import pytest
from mutagen.id3 import POPM
from mutagen.flac import FLAC
from mutagen.id3 import ID3

from musicupgrade import db, replace
from musicupgrade.config import Config

from conftest import make_flac, make_mp3


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        music_root=tmp_path / "Music",
        new_music_dir=tmp_path / "Music - New",
        backup_dir=tmp_path / "Music" / ".replaced-backup",
        db_path=tmp_path / "app.db",
        scope_export_path=tmp_path / "scope.json",
    )


@pytest.fixture
def conn(config):
    return db.connect(config.db_path)


def seed_track(conn, old_path: Path, **overrides) -> int:
    row = dict(
        old_path=str(old_path), artist="Queen", title="Bohemian Rhapsody", album="A Night at the Opera",
        tracknumber="1", rating=1.0, old_format="mp3", old_bitrate=128, duration_sec=354.0, status="approved",
    )
    row.update(overrides)
    cur = conn.execute(
        """INSERT INTO tracks (old_path, artist, title, album, tracknumber, rating,
           old_format, old_bitrate, duration_sec, status, last_synced_at)
           VALUES (:old_path,:artist,:title,:album,:tracknumber,:rating,
           :old_format,:old_bitrate,:duration_sec,:status,'now')""",
        row,
    )
    conn.commit()
    return cur.lastrowid


def test_apply_plan_moves_files_and_copies_tags(config, conn):
    old_path = config.music_root / "Queen" / "Bohemian Rhapsody.mp3"
    make_mp3(old_path, bitrate_kbps=128)
    old_audio_easy = mutagen.File(old_path, easy=True)
    old_audio_easy.add_tags()
    old_audio_easy["artist"] = ["Queen"]
    old_audio_easy["title"] = ["Bohemian Rhapsody"]
    old_audio_easy.save()

    new_path = config.new_music_dir / "queen_bohemian_rhapsody_flac.flac"
    make_flac(new_path, duration_sec=354.0)

    track_id = seed_track(conn, old_path)
    candidate_id = db.add_candidate(conn, track_id, str(new_path), "flac", 1000, 98.0, "exact_tag")
    conn.commit()

    plan = replace.build_plan(conn, track_id, candidate_id, config)
    outcome = replace.apply_plan(conn, plan, dry_run=False)

    assert outcome.ok, outcome.message
    assert not old_path.exists()
    assert not new_path.exists()
    final_path = config.music_root / "Queen" / "Bohemian Rhapsody.flac"
    assert final_path.exists()
    backup_path = config.backup_dir / "Queen" / "Bohemian Rhapsody.mp3"
    assert backup_path.exists()

    final_audio = mutagen.File(final_path, easy=True)
    assert final_audio["artist"] == ["Queen"]
    assert final_audio["title"] == ["Bohemian Rhapsody"]

    row = conn.execute("SELECT status FROM tracks WHERE id = ?", (track_id,)).fetchone()
    assert row["status"] == "replaced"

    action = conn.execute("SELECT * FROM actions WHERE track_id = ?", (track_id,)).fetchone()
    assert action["result"] == "ok"
    assert action["new_final_path"] == str(final_path)


def test_apply_plan_mp3_to_mp3_preserves_quodlibet_rating_and_extra_frames(config, conn):
    old_path = config.music_root / "Queen" / "Bohemian Rhapsody.mp3"
    make_mp3(old_path, bitrate_kbps=128)
    old_audio_easy = mutagen.File(old_path, easy=True)
    old_audio_easy.add_tags()
    old_audio_easy["artist"] = ["Queen"]
    old_audio_easy["title"] = ["Bohemian Rhapsody"]
    old_audio_easy["composer"] = ["4-Star"]
    old_audio_easy.save()
    old_id3 = ID3(old_path)
    old_id3.add(POPM(email="quodlibet@lists.sacredchao.net", rating=204, count=3))
    old_id3.save(old_path)

    new_path = config.new_music_dir / "br_320.mp3"
    make_mp3(new_path, bitrate_kbps=320)

    track_id = seed_track(conn, old_path)
    candidate_id = db.add_candidate(conn, track_id, str(new_path), "mp3", 320, 98.0, "exact_tag")
    conn.commit()

    plan = replace.build_plan(conn, track_id, candidate_id, config)
    outcome = replace.apply_plan(conn, plan, dry_run=False)

    assert outcome.ok, outcome.message
    final_id3 = ID3(plan.final_path)
    assert final_id3["TCOM"].text == ["4-Star"]
    popm = final_id3["POPM:quodlibet@lists.sacredchao.net"]
    assert popm.rating == 204
    assert popm.count == 3


def test_apply_plan_mp3_to_flac_translates_quodlibet_rating(config, conn):
    old_path = config.music_root / "Queen" / "Bohemian Rhapsody.mp3"
    make_mp3(old_path, bitrate_kbps=128)
    old_audio_easy = mutagen.File(old_path, easy=True)
    old_audio_easy.add_tags()
    old_audio_easy["artist"] = ["Queen"]
    old_audio_easy["title"] = ["Bohemian Rhapsody"]
    old_audio_easy.save()
    old_id3 = ID3(old_path)
    old_id3.add(POPM(email="quodlibet@lists.sacredchao.net", rating=204, count=3))
    old_id3.save(old_path)

    new_path = config.new_music_dir / "br.flac"
    make_flac(new_path)

    track_id = seed_track(conn, old_path)
    candidate_id = db.add_candidate(conn, track_id, str(new_path), "flac", 1000, 98.0, "exact_tag")
    conn.commit()

    plan = replace.build_plan(conn, track_id, candidate_id, config)
    outcome = replace.apply_plan(conn, plan, dry_run=False)

    assert outcome.ok, outcome.message
    final_flac = FLAC(plan.final_path)
    assert final_flac["rating:quodlibet@lists.sacredchao.net"] == ["0.8"]
    assert final_flac["playcount:quodlibet@lists.sacredchao.net"] == ["3"]


def test_dry_run_touches_nothing(config, conn):
    old_path = config.music_root / "Queen" / "Bohemian Rhapsody.mp3"
    make_mp3(old_path)
    new_path = config.new_music_dir / "br.flac"
    make_flac(new_path)

    track_id = seed_track(conn, old_path)
    candidate_id = db.add_candidate(conn, track_id, str(new_path), "flac", 1000, 98.0, "exact_tag")
    conn.commit()

    plan = replace.build_plan(conn, track_id, candidate_id, config)
    outcome = replace.apply_plan(conn, plan, dry_run=True)

    assert outcome.ok
    assert old_path.exists()
    assert new_path.exists()
    row = conn.execute("SELECT status FROM tracks WHERE id = ?", (track_id,)).fetchone()
    assert row["status"] == "approved"


def test_missing_candidate_file_records_failure_without_touching_original(config, conn):
    old_path = config.music_root / "Queen" / "Bohemian Rhapsody.mp3"
    make_mp3(old_path)

    track_id = seed_track(conn, old_path)
    missing_new_path = config.new_music_dir / "does-not-exist.flac"
    candidate_id = db.add_candidate(conn, track_id, str(missing_new_path), "flac", 1000, 98.0, "exact_tag")
    conn.commit()

    plan = replace.build_plan(conn, track_id, candidate_id, config)
    outcome = replace.apply_plan(conn, plan, dry_run=False)

    assert not outcome.ok
    assert old_path.exists()
    row = conn.execute("SELECT status FROM tracks WHERE id = ?", (track_id,)).fetchone()
    assert row["status"] == "approved"  # unchanged — safe to retry


def test_run_batch_marks_approved_before_applying(config, conn):
    old_path = config.music_root / "Queen" / "Bohemian Rhapsody.mp3"
    make_mp3(old_path)
    new_path = config.new_music_dir / "br.flac"
    make_flac(new_path)

    track_id = seed_track(conn, old_path, status="matched")
    candidate_id = db.add_candidate(conn, track_id, str(new_path), "flac", 1000, 98.0, "exact_tag")
    conn.commit()

    outcomes = replace.run_batch(conn, [(track_id, candidate_id)], config, dry_run=False)

    assert len(outcomes) == 1
    assert outcomes[0].ok
    row = conn.execute("SELECT status FROM tracks WHERE id = ?", (track_id,)).fetchone()
    assert row["status"] == "replaced"
