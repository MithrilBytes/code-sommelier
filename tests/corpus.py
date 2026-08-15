"""A corpus of real repositories, pinned, measured, and snapshotted.

The synthetic fixtures are built to exercise a rule, so they only ever
contain what someone thought to put there. They cannot produce a Xcode
DerivedData directory, a 6,000 commit history, a repository whose entire
content is .gitignore templates, or a C file from 2016 that nobody has
touched since. Those turn up here.

Every entry is pinned to a commit, so the measurements are a property of
the manifest and not of whatever those projects merged this morning. The
clock is frozen the same way the golden cards freeze it, which fixes the
one metric that would otherwise drift daily and, through the judging
bands, drag the score with it.

The clones are large and the network is not the test suite's business, so
the cache is populated by hand and the tests skip cleanly without it:

    python3 -m tests.corpus --sync        # clone or fetch, then check out the pins
    python3 -m tests.corpus --snapshot    # rewrite the expected measurements
    python3 -m tests.corpus --status      # what is cached, and at which commit
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence, Type
from unittest.mock import patch

import sommelier.collect as collect_module
from sommelier.collect import collect
from sommelier.judge import judge

HERE = Path(__file__).parent
MANIFEST_PATH = HERE / "corpus_manifest.json"
SNAPSHOT_DIR = HERE / "corpus_snapshots"
CACHE_DIR = HERE / "corpus_cache"

# Shared with tests/test_golden.py on purpose: one frozen date across the
# suite means one thing to change when it ever needs changing.
FROZEN_TODAY = date(2026, 8, 12)

# Real repositories are bigger than fixtures and the budget must never be
# what decides the result. A truncated run is a failure, not a smaller
# number.
CORPUS_BUDGET_SECONDS = 300.0


@dataclass(frozen=True)
class Entry:
    slug: str
    url: str
    commit: str
    note: str

    @property
    def path(self) -> Path:
        return CACHE_DIR / self.slug


def load_manifest() -> list[Entry]:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [Entry(**item) for item in raw["repositories"]]


def frozen_date_class(today: date) -> Type[date]:
    class FrozenDate(date):
        @classmethod
        def today(cls) -> "FrozenDate":
            return cls(today.year, today.month, today.day)

    return FrozenDate


def run_git(args: Sequence[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    return proc.stdout.strip()


def cached_commit(entry: Entry) -> str | None:
    """The commit the cache is actually sitting on, or None if absent."""
    if not (entry.path / ".git").exists():
        return None
    try:
        return run_git(["rev-parse", "HEAD"], cwd=entry.path)
    except subprocess.CalledProcessError:
        return None


def measure(entry: Entry) -> dict[str, Any]:
    """The snapshot for one repository: metrics plus what they were judged."""
    with patch.object(collect_module, "date", frozen_date_class(FROZEN_TODAY)):
        metrics = collect(entry.path, budget_seconds=CORPUS_BUDGET_SECONDS)
    judgement = judge(metrics)

    if metrics.dropped:
        raise RuntimeError(
            f"{entry.slug}: analyzers dropped {[d.name for d in metrics.dropped]}; "
            "the budget decided this result, so it is not a measurement"
        )

    from sommelier.render import render_json

    payload: dict[str, Any] = json.loads(render_json(metrics, judgement))
    # The only machine-unstable value in the document. Everything else is
    # sorted, rounded, and pinned by the manifest commit.
    payload["metrics"]["path"] = "<CACHE>"
    payload["metrics"]["name"] = entry.slug
    return payload


def snapshot_path(entry: Entry) -> Path:
    """The measurement half. Kept separate from the judgement on purpose.

    Everything above collect is being rewritten: the score, the content plan,
    the grammar. Those phases move every judgement in the corpus at once. If
    the two halves shared a file, a measurement regression riding along in a
    1,300 line judgement diff would be invisible. Split, the metrics file not
    moving is itself the evidence that collect was untouched.
    """
    return SNAPSHOT_DIR / f"{entry.slug}.metrics.json"


def judgement_path(entry: Entry) -> Path:
    return SNAPSHOT_DIR / f"{entry.slug}.judgement.json"


def _dump(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_snapshot(entry: Entry, payload: dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _dump(snapshot_path(entry), payload["metrics"])
    _dump(judgement_path(entry), payload["judgement"])
    legacy = SNAPSHOT_DIR / f"{entry.slug}.json"
    if legacy.exists():
        legacy.unlink()


def read_snapshot(entry: Entry) -> dict[str, Any]:
    """The two halves recombined into the shape measure() returns."""
    return {
        "metrics": json.loads(snapshot_path(entry).read_text(encoding="utf-8")),
        "judgement": json.loads(judgement_path(entry).read_text(encoding="utf-8")),
    }


# --- command line ----------------------------------------------------


def sync() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for entry in load_manifest():
        if not (entry.path / ".git").exists():
            print(f"cloning {entry.slug}")
            run_git(["clone", "--quiet", entry.url, str(entry.path)])
        current = cached_commit(entry)
        if current != entry.commit:
            print(f"checking out {entry.slug} at {entry.commit[:12]}")
            try:
                run_git(["fetch", "--quiet", "origin", entry.commit], cwd=entry.path)
            except subprocess.CalledProcessError:
                run_git(["fetch", "--quiet", "--all"], cwd=entry.path)
            run_git(["checkout", "--quiet", "--detach", entry.commit], cwd=entry.path)
    print(f"cache ready at {CACHE_DIR}")
    return 0


def snapshot() -> int:
    missing = [e.slug for e in load_manifest() if cached_commit(e) is None]
    if missing:
        print(f"not cached: {', '.join(missing)}. Run --sync first.", file=sys.stderr)
        return 1
    for entry in load_manifest():
        write_snapshot(entry, measure(entry))
        print(f"snapshot {entry.slug}")
    return 0


def status() -> int:
    for entry in load_manifest():
        current = cached_commit(entry)
        if current is None:
            state = "absent"
        elif current == entry.commit:
            state = "pinned"
        else:
            state = f"WRONG COMMIT {current[:12]}"
        has_snap = "snapshot" if snapshot_path(entry).exists() else "no snapshot"
        print(f"{entry.slug:28} {state:22} {has_snap}")
    return 0


def main(argv: Sequence[str]) -> int:
    commands = {"--sync": sync, "--snapshot": snapshot, "--status": status}
    if len(argv) != 1 or argv[0] not in commands:
        print(f"usage: python3 -m tests.corpus [{' | '.join(commands)}]", file=sys.stderr)
        return 2
    return commands[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
