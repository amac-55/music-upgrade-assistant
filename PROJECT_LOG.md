# Project Log

## Where we are (2026-08-11)

Phase 0 MVP is built and running end-to-end on the real Linux Mint machine. Confirmed working:

- QuodLibet plugin exports the library to JSON (12,569 tracks exported).
- `music-upgrade sync` pulls that into the app's database, filtered to 3/4-star tracks that aren't already upgraded — **2,493 tracks in scope**.
- `music-upgrade match` scans "Music - New" and matches candidates against tracks in scope — **23 matched, 2,470 with no candidate yet** (expected: most of the backlog doesn't have a downloaded replacement waiting).
- `music-upgrade review` opens the GTK4 batch review window successfully.

**Not yet done: actually approving and applying a replacement on a real file.** Everything up to opening the review window has been exercised live; clicking "Apply Approved" has only been tested against synthetic fixtures and unit tests, never a real track. **This should be the first thing tried next session** — start with one low-stakes track, in dry-run mode first, before trusting it on a batch.

## Architecture recap

- `src/musicupgrade/db.py` — SQLite state (tracks / candidates / actions tables). QuodLibet stays the source of truth for ratings; this DB tracks replacement progress only.
- `src/musicupgrade/scanner.py` + `audiofile.py` — reads tags/format/bitrate/duration from "Music - New"; also does the tag-copy-and-strip at replace time.
- `src/musicupgrade/matcher.py` — exact tag match → fuzzy match (with edition/remaster-suffix stripping) → filename fallback, gated by a quality check (FLAC or ≥320kbps MP3 only), with a duration tiebreak.
- `src/musicupgrade/replace.py` — the actual file-system change: copies tags onto the new file, archives the original (never deletes), moves the retagged file into place under the original's filename.
- `quodlibet-plugin/scope_export.py` — QuodLibet plugin, exports the library to JSON on library changes or on demand.
- `src/musicupgrade/ui/review_window.py` — GTK4 batch checklist + detail pane + apply flow.
- `src/musicupgrade/cli.py` — `music-upgrade sync|match|status|review`.

15 unit/integration tests in `tests/`, all passing on both the dev Mac and the real target machine.

## Environment specifics worth remembering

These took real debugging effort to pin down — worth reading before assuming anything about this setup:

- **QuodLibet is a Flatpak** (`io.github.quodlibet.QuodLibet`), not a native package. Despite having broad (`host`) filesystem permission, its own config directory is still redirected to `~/.var/app/io.github.quodlibet.QuodLibet/config/quodlibet/` — not `~/.config/quodlibet` or `~/.quodlibet` (both exist on this machine from history, but aren't what the Flatpak reads). Plugins go in `.../config/quodlibet/plugins/`. Launch/debug with `flatpak run io.github.quodlibet.QuodLibet`, there's no bare `quodlibet` command on PATH.
- **5-star rating scale**, not the 4-star default — 3★ = `0.6`, 4★ = `0.8`. This is now the configurable `scope_ratings` setting in `config.toml` rather than a hardcoded assumption, precisely because of this.
- **Older Python (3.10)** on the target machine (not 3.11+), so the app supports 3.10 via a `tomli` backport for `tomllib`.
- **PyGObject/GTK4 come from apt** (`python3-gi`, `gir1.2-gtk-4.0`), not pip — the venv needs `--system-site-packages`, and they're deliberately not listed as pip dependencies (would try to compile from source instead of using the apt one).
- The library lives on an external/removable drive, mounted under `/media/<user>/<drive-label>`. `new_music_dir` ("Music - New") is a *sibling* of `_Music`, not nested inside it — worth remembering since the design plan assumed nesting.

## Lessons learned

- **Verify unfamiliar APIs against real source before shipping to a machine you can't debug directly.** GTK3→4 changed enough (`Box.append()` vs `pack_start`, `Paned.set_start_child/end_child` vs `add1/add2`, `Dialog.run()` removed entirely) that writing from memory would likely have shipped bugs. Fetching actual GTK4 docs and QuodLibet's real plugin source caught this before the user ever ran the code — both the plugin and the review window worked on the first real try.
- **Give remote-terminal instructions one command at a time.** Pasting a block that mixed prose and commands led the user to copy-paste the whole thing into their shell, causing cascading errors and an accidental nested `git clone`. Small, unambiguous, single-command steps (with explicit "run just this line" when needed) avoided repeats of that.
- **Don't assume environment-specific values (rating scale, install method) — check.** Both the Flatpak-vs-native QuodLibet install and the 5-star rating scale were discovered by asking the user to run a read-only diagnostic and looking at the actual output, not by guessing harder.
- Setting up git/SSH/GitHub access from scratch (no prior git identity, no SSH keys, no `gh` CLI, no Homebrew on the dev Mac) was itself a real chunk of the session — worth doing this earlier next time a fresh project starts, before writing much code, so there's no backlog of "sync this file's contents by hand" pain.

## Known loose ends (not investigated yet)

- 12 tracks have a rating of `3.5` — outside QuodLibet's normal 0.0–1.0 range. Harmless (won't match any `scope_ratings` value) but likely a tagging artifact from another tool; worth a look.
- Several files fail to load in QuodLibet's own library scan: some MP3s (`can't sync to MPEG frame`) and the entire Beach Boys *Pet Sounds* FLAC album (`not a valid FLAC file`). Pre-existing corruption, unrelated to this app, noticed in the debug log — those files just won't appear in scope until fixed.

## Roadmap from here

1. **Finish validating Phase 0**: approve and apply one real replacement via the review UI (dry-run first), confirm the file lands correctly, tags are right, backup archive is correct, and QuodLibet picks up the change on its next library refresh with rating/playcount intact.
2. **Phase 1 rollout**: work through the current 23 matches, then the rest of the 2,470-track backlog as downloads land in "Music - New". Watch for matching edge cases (box sets/multi-disc, false-positive live/remix matches) and tune `fuzzy_match_threshold`/`auto_check_confidence` if needed.
3. **Phase 2**: broaden scope beyond 3/4-star ratings to all remaining under-quality tracks in album folders, once Phase 1 is largely clear. The pipeline already supports this via a parameterized scope — mainly needs a CLI/UI toggle.
4. **Phase 3 (optional)**: Nicotine+ plugin to auto-search/queue downloads for tracks with no candidate yet, feeding back into the same review flow. Not started — treat as a spike, the Nicotine+ scripting surface hasn't been prototyped.
5. Minor: investigate the `3.5`-rating tracks and the corrupted MP3/FLAC files noted above.

## Quick resume checklist

On Mint: `cd ~/music-upgrade-assistant && git pull && source .venv/bin/activate`, then `music-upgrade sync && music-upgrade match && music-upgrade review`.
