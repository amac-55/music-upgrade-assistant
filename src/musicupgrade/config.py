from __future__ import annotations

try:
    import tomllib  # stdlib on 3.11+
except ImportError:
    import tomli as tomllib  # backport on 3.10
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "music-upgrade-assistant" / "config.toml"


@dataclass(frozen=True)
class Config:
    music_root: Path
    new_music_dir: Path
    backup_dir: Path
    db_path: Path
    scope_export_path: Path
    min_bitrate_kbps: int = 320
    upgrade_formats: tuple[str, ...] = ("flac", "mp3")
    auto_check_confidence: float = 90.0
    fuzzy_match_threshold: float = 85.0
    duration_tolerance_sec: float = 3.0

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"No config at {path}. Copy config.example.toml there (or pass "
                f"--config) and edit the paths for this machine."
            )
        with path.open("rb") as f:
            raw = tomllib.load(f)

        paths = raw.get("paths", {})
        for key in ("music_root", "new_music_dir", "backup_dir", "db_path", "scope_export_path"):
            if key not in paths:
                raise ValueError(f"config [paths] is missing '{key}'")

        matching = raw.get("matching", {})
        return cls(
            music_root=Path(paths["music_root"]).expanduser(),
            new_music_dir=Path(paths["new_music_dir"]).expanduser(),
            backup_dir=Path(paths["backup_dir"]).expanduser(),
            db_path=Path(paths["db_path"]).expanduser(),
            scope_export_path=Path(paths["scope_export_path"]).expanduser(),
            min_bitrate_kbps=matching.get("min_bitrate_kbps", 320),
            upgrade_formats=tuple(matching.get("upgrade_formats", ["flac", "mp3"])),
            auto_check_confidence=matching.get("auto_check_confidence", 90.0),
            fuzzy_match_threshold=matching.get("fuzzy_match_threshold", 85.0),
            duration_tolerance_sec=matching.get("duration_tolerance_sec", 3.0),
        )
