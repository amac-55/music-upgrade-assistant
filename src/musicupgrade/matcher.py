"""Matches tracks in scope against files found in "Music - New".

Pipeline, per the design plan: exact tag match, then fuzzy tag match with a
duration tiebreak, then a filename fallback for downloads with missing or
garbled tags — all gated by a quality check (only FLAC or >=min bitrate MP3
is ever proposed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from . import db
from .audiofile import AudioInfo
from .config import Config
from .scanner import scan_new_music

_NORM_RE = re.compile(r"[^a-z0-9]+")

# Edition/remaster noise that legitimately varies between an old tag and a
# freshly-downloaded file of the *same* recording. Stripped before a second
# comparison pass so "Bohemian Rhapsody" still matches "Bohemian Rhapsody
# (Remastered 2011)" without loosening the match enough to let a genuinely
# different title (e.g. another track by the same artist) through.
_EDITION_NOISE_RE = re.compile(
    r"\b(remaster(ed)?|live|deluxe|edition|version|mono|stereo|bonus|"
    r"single|radio edit|edit|mix|anniversary|expanded|explicit|clean|\d{4})\b"
)


def normalize(s: str | None) -> str:
    if not s:
        return ""
    return _NORM_RE.sub(" ", s.lower()).strip()


def _strip_edition_noise(s: str) -> str:
    return _NORM_RE.sub(" ", _EDITION_NOISE_RE.sub(" ", s)).strip()


def _title_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    plain = fuzz.token_sort_ratio(a, b)
    stripped = fuzz.token_sort_ratio(_strip_edition_noise(a), _strip_edition_noise(b))
    return max(plain, stripped)


@dataclass
class TrackInfo:
    id: int
    old_path: str
    artist: str | None
    title: str | None
    album: str | None
    duration_sec: float | None


@dataclass
class MatchResult:
    candidate: AudioInfo
    score: float
    basis: str  # exact_tag | fuzzy_tag | filename_fallback


def find_candidates(track: TrackInfo, pool: list[AudioInfo], config: Config) -> list[MatchResult]:
    old_stem = normalize(Path(track.old_path).stem)
    track_artist, track_title = normalize(track.artist), normalize(track.title)
    has_track_tags = bool(track_artist) and bool(track_title)

    results: list[MatchResult] = []

    for c in pool:
        quality_ok = c.format == "flac" or (c.format == "mp3" and c.bitrate_kbps >= config.min_bitrate_kbps)
        if not quality_ok:
            continue

        cand_artist, cand_title = normalize(c.artist), normalize(c.title)
        has_cand_tags = bool(cand_artist) and bool(cand_title)

        base: float | None = None
        basis = ""

        if has_track_tags and has_cand_tags:
            artist_score = fuzz.ratio(track_artist, cand_artist)
            if artist_score >= 90:
                if track_title == cand_title:
                    base, basis = 100.0, "exact_tag"
                else:
                    base, basis = _title_score(track_title, cand_title), "fuzzy_tag"

        if base is None:
            cand_stem = normalize(c.path.stem)
            base = fuzz.token_sort_ratio(old_stem, cand_stem)
            if has_track_tags:
                base = max(base, _title_score(f"{track_artist} {track_title}", cand_stem))
            basis = "filename_fallback"

        duration_penalty = 0.0
        if track.duration_sec and c.duration_sec:
            delta = abs(track.duration_sec - c.duration_sec)
            over = max(0.0, delta - config.duration_tolerance_sec)
            duration_penalty = min(30.0, over * 3.0)

        album_penalty = 0.0
        if track.album and c.album:
            album_score = fuzz.token_sort_ratio(normalize(track.album), normalize(c.album))
            if album_score < 50:
                album_penalty = 8.0

        quality_bonus = 5.0 if c.format == "flac" else 0.0

        score = max(0.0, min(100.0, base - duration_penalty - album_penalty + quality_bonus))
        if score >= config.fuzzy_match_threshold:
            results.append(MatchResult(candidate=c, score=score, basis=basis))

    results.sort(key=lambda r: (-round(r.score, 1), 0 if r.candidate.format == "flac" else 1, str(r.candidate.path)))
    return results


def run_matching(conn, config: Config) -> dict[str, int]:
    """Re-scan Music - New and (re)match it against everything still open
    (pending / matched / no_candidate — never approved or replaced rows).
    """
    pool = scan_new_music(config.new_music_dir)
    tracks = db.get_scope_tracks(conn, statuses=("pending", "matched", "no_candidate"))

    summary = {"matched": 0, "no_candidate": 0}
    for row in tracks:
        track = TrackInfo(
            id=row["id"],
            old_path=row["old_path"],
            artist=row["artist"],
            title=row["title"],
            album=row["album"],
            duration_sec=row["duration_sec"],
        )
        matches = find_candidates(track, pool, config)

        db.clear_candidates(conn, track.id)
        for m in matches:
            db.add_candidate(
                conn, track.id, str(m.candidate.path), m.candidate.format,
                m.candidate.bitrate_kbps, m.score, m.basis,
            )

        new_status = "matched" if matches else "no_candidate"
        db.set_track_status(conn, track.id, new_status)
        summary[new_status] += 1

    conn.commit()
    return summary
