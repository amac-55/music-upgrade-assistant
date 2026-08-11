"""Walks the "Music - New" folder and reads tags/format/bitrate/duration
for every candidate file, ready for the matcher to score against tracks
in scope.
"""

from __future__ import annotations

from pathlib import Path

from .audiofile import SUPPORTED_EXTENSIONS, AudioInfo, read_audio_info


def scan_new_music(new_music_dir: Path) -> list[AudioInfo]:
    if not new_music_dir.is_dir():
        raise FileNotFoundError(f"Music - New folder not found: {new_music_dir}")

    found: list[AudioInfo] = []
    for path in sorted(new_music_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        info = read_audio_info(path)
        if info is not None:
            found.append(info)
    return found
