"""The replace procedure: turns an approved (track, candidate) pair into
file-system changes. Runs only for rows the review UI has approved — see
the design plan's six-step sequence. The original file is archived, never
deleted, so a bad match is a five-second undo rather than a lost file.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import db
from .audiofile import copy_tags
from .config import Config


@dataclass
class ReplacePlan:
    track_id: int
    candidate_id: int
    old_path: Path
    new_path: Path
    final_path: Path
    backup_path: Path


@dataclass
class ReplaceOutcome:
    plan: ReplacePlan
    ok: bool
    message: str


def build_plan(conn, track_id: int, candidate_id: int, config: Config) -> ReplacePlan:
    track = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    candidate = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if track is None or candidate is None:
        raise ValueError(f"Unknown track_id={track_id} or candidate_id={candidate_id}")
    if candidate["track_id"] != track_id:
        raise ValueError(f"candidate {candidate_id} does not belong to track {track_id}")

    old_path = Path(track["old_path"])
    new_path = Path(candidate["new_path"])
    ext = ".flac" if candidate["new_format"] == "flac" else ".mp3"
    final_path = old_path.with_name(old_path.stem + ext)

    try:
        rel = old_path.relative_to(config.music_root)
    except ValueError:
        rel = Path(old_path.name)
    backup_path = config.backup_dir / rel

    return ReplacePlan(track_id, candidate_id, old_path, new_path, final_path, backup_path)


def _record_failure(conn, plan: ReplacePlan, message: str) -> ReplaceOutcome:
    db.record_action(conn, plan.track_id, plan.candidate_id, "", "", f"error: {message}")
    return ReplaceOutcome(plan, False, message)


def apply_plan(conn, plan: ReplacePlan, dry_run: bool = False) -> ReplaceOutcome:
    if dry_run:
        return ReplaceOutcome(plan, True, "dry run — no files touched")

    if not plan.old_path.exists():
        return _record_failure(conn, plan, f"original file missing: {plan.old_path}")
    if not plan.new_path.exists():
        return _record_failure(conn, plan, f"candidate file missing: {plan.new_path}")
    if plan.final_path.exists() and plan.final_path != plan.old_path:
        return _record_failure(conn, plan, f"a file already exists at the destination: {plan.final_path}")

    try:
        copy_tags(plan.old_path, plan.new_path)
    except Exception as exc:
        return _record_failure(conn, plan, f"tag copy failed: {exc}")

    plan.backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(plan.old_path), str(plan.backup_path))

    try:
        plan.final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(plan.new_path), str(plan.final_path))
    except Exception as exc:
        shutil.move(str(plan.backup_path), str(plan.old_path))  # best-effort undo
        return _record_failure(conn, plan, f"move into place failed, original restored: {exc}")

    db.record_action(conn, plan.track_id, plan.candidate_id, str(plan.backup_path), str(plan.final_path), "ok")
    db.set_track_status(conn, plan.track_id, "replaced")
    return ReplaceOutcome(plan, True, "replaced")


def run_batch(
    conn, approvals: list[tuple[int, int]], config: Config, dry_run: bool = False
) -> list[ReplaceOutcome]:
    """approvals: list of (track_id, candidate_id) pairs the review UI approved."""
    outcomes = []
    for track_id, candidate_id in approvals:
        if not dry_run:
            db.set_track_status(conn, track_id, "approved")
        plan = build_plan(conn, track_id, candidate_id, config)
        outcomes.append(apply_plan(conn, plan, dry_run=dry_run))
    return outcomes
