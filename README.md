# Music Library Upgrade Assistant

A tool for replacing low-bitrate tracks in a long-running [QuodLibet](https://quodlibet.readthedocs.io/) music library with 320kbps/FLAC upgrades, without doing the whole find-download-move-retag dance by hand for every track.

It starts with your 3/4-star rated tracks (the ones worth upgrading first), matches them against files you've already downloaded into a "Music - New" folder, and lets you review and approve replacements in a batch before anything touches disk. Nothing is auto-replaced — every change goes through the review UI first, and originals are archived rather than deleted.

See [`PROJECT_LOG.md`](PROJECT_LOG.md) for current status, environment notes, and the roadmap.

## How it works

1. A QuodLibet plugin exports your library (path, tags, rating, format, bitrate) to a JSON file.
2. `music-upgrade sync` pulls that into a local database, filtered to tracks in scope.
3. `music-upgrade match` scans your "Music - New" folder and matches candidates against tracks in scope (exact tag match → fuzzy match → filename fallback, gated by a quality check).
4. `music-upgrade review` opens a GTK4 window to approve matches as a batch. Approved replacements: copy the old file's tags onto the new file, archive the original, move the retagged file into place under the original's filename.

## Requirements

- Linux, with QuodLibet installed (native or Flatpak)
- Python 3.10+
- GTK4 + PyGObject for the review UI — install via your package manager, e.g. on Debian/Ubuntu-based systems:
  ```
  sudo apt-get install python3-gi gir1.2-gtk-4.0
  ```

## Setup

```
git clone https://github.com/amac-55/music-upgrade-assistant.git
cd music-upgrade-assistant
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `--system-site-packages` flag matters: PyGObject/GTK come from your system package manager, not pip, so the venv needs to see them.

### Configure

```
mkdir -p ~/.config/music-upgrade-assistant
cp config.example.toml ~/.config/music-upgrade-assistant/config.toml
```

Edit that file with your real paths. Note `scope_ratings` in particular — QuodLibet's rating float for "3 stars"/"4 stars" depends on the number-of-stars setting in QuodLibet's own preferences, so it isn't always the 4-star default. `config.example.toml` explains how to check your actual values.

### Install the QuodLibet plugin

Copy `quodlibet-plugin/scope_export.py` into QuodLibet's plugins folder, then enable **Export Upgrade Scope** under QuodLibet's Plugins list and click **Export Now**.

Where that plugins folder actually is depends on your install:

- Native install: `~/.config/quodlibet/plugins/` (or the legacy `~/.quodlibet/plugins/`, if that's what already exists on your system)
- Flatpak install (`io.github.quodlibet.QuodLibet`): `~/.var/app/io.github.quodlibet.QuodLibet/config/quodlibet/plugins/`

## Usage

```
music-upgrade sync    # pull the latest scope from the QuodLibet export
music-upgrade match   # scan "Music - New" and match candidates
music-upgrade status  # show track counts by status
music-upgrade review  # open the batch review UI
```

## Development

```
pip install -e ".[dev]"
python -m pytest -q
```

## License

[MIT](LICENSE)
