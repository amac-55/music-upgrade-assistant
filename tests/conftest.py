"""Synthetic, tiny-but-valid MP3/FLAC fixtures for tests, since there's no
audio encoder available in this environment. mutagen only needs a
syntactically valid header (MPEG frame sync / FLAC STREAMINFO block) to
report format/bitrate/duration and to read and write tags — it never
decodes actual audio — so hand-built headers with zeroed-out bodies are
sufficient stand-ins for real downloads.
"""

from __future__ import annotations

from pathlib import Path


def make_flac(path: Path, duration_sec: float = 3.0, sample_rate: int = 44100, channels: int = 2, bits: int = 16) -> Path:
    total_samples = int(sample_rate * duration_sec)
    packed = (sample_rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | total_samples
    streaminfo = (
        (4096).to_bytes(2, "big") + (4096).to_bytes(2, "big")
        + (0).to_bytes(3, "big") + (0).to_bytes(3, "big")
        + packed.to_bytes(8, "big") + b"\x00" * 16
    )
    block_header = bytes([0x80]) + len(streaminfo).to_bytes(3, "big")  # last-block flag set, type STREAMINFO
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC" + block_header + streaminfo + b"\x00" * 64)
    return path


_MP3_BITRATE_INDEX = {32: 1, 40: 2, 48: 3, 56: 4, 64: 5, 80: 6, 96: 7, 112: 8,
                       128: 9, 160: 10, 192: 11, 224: 12, 256: 13, 320: 14}
_MP3_SAMPLERATE_INDEX = {44100: 0, 48000: 1, 32000: 2}


def make_mp3(path: Path, bitrate_kbps: int = 320, sample_rate: int = 44100, num_frames: int = 50) -> Path:
    # MPEG1 Layer III, no CRC, stereo — frame size must match the bitrate
    # actually declared in the header or mutagen can't re-sync frame to frame.
    byte1 = 0xFB
    byte2 = (_MP3_BITRATE_INDEX[bitrate_kbps] << 4) | (_MP3_SAMPLERATE_INDEX[sample_rate] << 2)
    byte3 = 0x00
    header = bytes([0xFF, byte1, byte2, byte3])
    frame_size = 144 * bitrate_kbps * 1000 // sample_rate
    frame = header + b"\x00" * (frame_size - len(header))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frame * num_frames)
    return path
