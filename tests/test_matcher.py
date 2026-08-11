from pathlib import Path

import pytest

from musicupgrade.audiofile import AudioInfo
from musicupgrade.config import Config
from musicupgrade.matcher import TrackInfo, find_candidates


@pytest.fixture
def config() -> Config:
    return Config(
        music_root=Path("/music"),
        new_music_dir=Path("/music/Music - New"),
        backup_dir=Path("/music/.replaced-backup"),
        db_path=Path("/tmp/x.db"),
        scope_export_path=Path("/tmp/scope.json"),
    )


def make_candidate(path: str, artist=None, title=None, album=None, fmt="mp3", bitrate=320, duration=240.0) -> AudioInfo:
    return AudioInfo(
        path=Path(path), artist=artist, title=title, album=album,
        tracknumber=None, format=fmt, bitrate_kbps=bitrate, duration_sec=duration,
    )


def test_exact_tag_match(config):
    track = TrackInfo(id=1, old_path="/music/Queen/song.mp3", artist="Queen", title="Bohemian Rhapsody", album=None, duration_sec=240.0)
    pool = [make_candidate("/new/bohemian.mp3", artist="Queen", title="Bohemian Rhapsody", duration=241.0)]

    results = find_candidates(track, pool, config)

    assert len(results) == 1
    assert results[0].basis == "exact_tag"
    assert results[0].score >= 95


def test_fuzzy_tag_match_with_remaster_suffix(config):
    track = TrackInfo(id=1, old_path="/music/Queen/song.mp3", artist="Queen", title="Bohemian Rhapsody", album=None, duration_sec=240.0)
    pool = [make_candidate("/new/br.mp3", artist="Queen", title="Bohemian Rhapsody (Remastered 2011)", duration=241.0)]

    results = find_candidates(track, pool, config)

    assert len(results) == 1
    assert results[0].basis == "fuzzy_tag"
    assert results[0].score >= config.fuzzy_match_threshold


def test_filename_fallback_when_candidate_tags_missing(config):
    track = TrackInfo(id=1, old_path="/music/Queen/Bohemian Rhapsody.mp3", artist="Queen", title="Bohemian Rhapsody", album=None, duration_sec=240.0)
    pool = [make_candidate("/new/Queen - Bohemian Rhapsody.mp3", artist=None, title=None, duration=240.0)]

    results = find_candidates(track, pool, config)

    assert len(results) == 1
    assert results[0].basis == "filename_fallback"


def test_quality_gate_rejects_low_bitrate(config):
    track = TrackInfo(id=1, old_path="/music/Queen/song.mp3", artist="Queen", title="Bohemian Rhapsody", album=None, duration_sec=240.0)
    pool = [make_candidate("/new/br.mp3", artist="Queen", title="Bohemian Rhapsody", bitrate=192, duration=240.0)]

    results = find_candidates(track, pool, config)

    assert results == []


def test_flac_preferred_over_mp3_when_both_match(config):
    track = TrackInfo(id=1, old_path="/music/Queen/song.mp3", artist="Queen", title="Bohemian Rhapsody", album=None, duration_sec=240.0)
    pool = [
        make_candidate("/new/br.mp3", artist="Queen", title="Bohemian Rhapsody", fmt="mp3", bitrate=320, duration=240.0),
        make_candidate("/new/br.flac", artist="Queen", title="Bohemian Rhapsody", fmt="flac", bitrate=1000, duration=240.0),
    ]

    results = find_candidates(track, pool, config)

    assert len(results) == 2
    assert results[0].candidate.format == "flac"


def test_large_duration_mismatch_penalized_out(config):
    # Same title/artist but a very different length (e.g. a live version) —
    # exact tag match alone shouldn't be enough to clear the bar.
    track = TrackInfo(id=1, old_path="/music/Queen/song.mp3", artist="Queen", title="Bohemian Rhapsody", album=None, duration_sec=240.0)
    pool = [make_candidate("/new/br-live.mp3", artist="Queen", title="Bohemian Rhapsody", duration=360.0)]

    results = find_candidates(track, pool, config)

    assert results == []
