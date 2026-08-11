"""Reading and writing tags across the two formats this library cares about:
MP3 (ID3) and FLAC (Vorbis comments). Shared by the scanner (reads new
downloads and, via the QuodLibet plugin, the existing library) and the
replace procedure (copies tags from an old file onto its replacement).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, POPM

SUPPORTED_EXTENSIONS = (".mp3", ".flac")

# Common tag fields we care about, as (EasyID3/VComment key) -> AudioInfo field.
_TAG_FIELDS = ("artist", "title", "album", "tracknumber", "genre", "date")

# QuodLibet's own default save email (quodlibet.const.EMAIL) — the key it
# reads/writes rating and play count under, as a POPM frame for ID3 or
# "rating:<email>" / "playcount:<email>" Vorbis comments for FLAC.
_QL_RATING_EMAIL = "quodlibet@lists.sacredchao.net"


@dataclass
class AudioInfo:
    path: Path
    artist: str | None
    title: str | None
    album: str | None
    tracknumber: str | None
    format: str  # "mp3" | "flac"
    bitrate_kbps: int
    duration_sec: float


def _first(easy_audio, key: str) -> str | None:
    values = easy_audio.get(key)
    if not values:
        return None
    return str(values[0])


def read_audio_info(path: Path) -> AudioInfo | None:
    """Read the handful of tags + audio properties the matcher needs.

    Returns None for unsupported extensions or files mutagen can't parse
    (corrupt download, wrong extension, etc.) rather than raising — callers
    scan whole directory trees and a single bad file shouldn't abort that.
    """
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return None
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        return None
    if audio is None or audio.info is None:
        return None

    fmt = "flac" if ext == ".flac" else "mp3"
    bitrate = getattr(audio.info, "bitrate", 0) or 0
    return AudioInfo(
        path=path,
        artist=_first(audio, "artist"),
        title=_first(audio, "title"),
        album=_first(audio, "album"),
        tracknumber=_first(audio, "tracknumber"),
        format=fmt,
        bitrate_kbps=round(bitrate / 1000),
        duration_sec=float(getattr(audio.info, "length", 0.0)),
    )


def _read_cover_art(path: Path) -> tuple[bytes, str] | None:
    ext = path.suffix.lower()
    if ext == ".mp3":
        try:
            id3 = ID3(path)
        except ID3NoHeaderError:
            return None
        for tag in id3.values():
            if isinstance(tag, APIC):
                return bytes(tag.data), tag.mime
        return None
    if ext == ".flac":
        flac = FLAC(path)
        if flac.pictures:
            pic = flac.pictures[0]
            return bytes(pic.data), pic.mime
        return None
    return None


def _read_rating(source: Path) -> tuple[float, int] | None:
    """Read QuodLibet's rating/play count from source, if it wrote one.

    Returns (rating 0.0-1.0, playcount) or None if source has no QuodLibet
    rating frame/comment under _QL_RATING_EMAIL.
    """
    ext = source.suffix.lower()
    if ext == ".mp3":
        try:
            id3 = ID3(source)
        except ID3NoHeaderError:
            return None
        frame = id3.get(f"POPM:{_QL_RATING_EMAIL}")
        if frame is None:
            return None
        return frame.rating / 255.0, frame.count
    if ext == ".flac":
        flac = FLAC(source)
        rating = flac.get(f"rating:{_QL_RATING_EMAIL}")
        if not rating:
            return None
        playcount = flac.get(f"playcount:{_QL_RATING_EMAIL}")
        return float(rating[0]), int(playcount[0]) if playcount else 0
    return None


def copy_tags(source: Path, dest: Path) -> None:
    """Strip dest's existing tags and replace them with source's.

    Same-format copies (mp3 -> mp3, flac -> flac) copy every frame/comment
    wholesale for full fidelity — comments, composer/conductor, and
    QuodLibet's own POPM rating/playcount all carry over untouched.

    Cross-format copies (mp3 -> flac) can't carry raw frames across, so they
    fall back to the common fields in _TAG_FIELDS plus embedded cover art,
    with QuodLibet's rating/playcount explicitly translated to the
    destination format's convention (POPM for ID3, rating:/playcount:
    comments for Vorbis) since neither is a _TAG_FIELDS entry.
    """
    source_ext = source.suffix.lower()
    dest_ext = dest.suffix.lower()
    rating = _read_rating(source)

    if source_ext == ".mp3" and dest_ext == ".mp3":
        try:
            src_id3 = ID3(source)
        except ID3NoHeaderError:
            src_id3 = ID3()
        src_id3.save(dest)
        return
    if source_ext == ".flac" and dest_ext == ".flac":
        src_flac = FLAC(source)
        dest_flac = FLAC(dest)
        dest_flac.delete()
        dest_flac.clear_pictures()
        for key, values in src_flac.items():
            dest_flac[key] = values
        for pic in src_flac.pictures:
            dest_flac.add_picture(pic)
        dest_flac.save()
        return

    src_audio = mutagen.File(source, easy=True)
    if src_audio is None:
        raise ValueError(f"Could not read tags from {source}")
    src_values = {field: src_audio[field] for field in _TAG_FIELDS if field in src_audio}
    cover = _read_cover_art(source)

    if dest_ext == ".mp3":
        dest_audio = mutagen.File(dest, easy=True)
        dest_audio.delete()
        if dest_audio.tags is None:
            dest_audio.add_tags()
        for field, values in src_values.items():
            dest_audio[field] = values
        dest_audio.save()
        if cover:
            data, mime = cover
            id3 = ID3(dest)
            id3.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
            id3.save(dest)
        if rating:
            rating_float, playcount = rating
            id3 = ID3(dest)
            id3.add(POPM(email=_QL_RATING_EMAIL, rating=round(255 * rating_float), count=playcount))
            id3.save(dest)
    elif dest_ext == ".flac":
        flac = FLAC(dest)
        flac.delete()
        flac.clear_pictures()
        for field, values in src_values.items():
            flac[field] = values
        if cover:
            data, mime = cover
            pic = Picture()
            pic.data = data
            pic.mime = mime
            pic.type = 3
            flac.add_picture(pic)
        if rating:
            rating_float, playcount = rating
            flac[f"rating:{_QL_RATING_EMAIL}"] = str(rating_float)
            if playcount:
                flac[f"playcount:{_QL_RATING_EMAIL}"] = str(playcount)
        flac.save()
    else:
        raise ValueError(f"Unsupported destination format: {dest}")
