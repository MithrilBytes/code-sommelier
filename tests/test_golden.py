"""Whole tasting cards, frozen byte for byte.

The unit tests check that a finding fires. These check what the reader
actually sees, which is the part nothing else covers: wrapping, column
alignment, which template each course drew, and the order the courses
arrive in. A prose edit that changes a card now shows up as a diff to
approve rather than as silence.

Three things have to be nailed down or a golden rots on its own:

* The clock. `date.today()` is read in exactly one place, and its value
  becomes `days_since_last_commit`, from which judge() reconstructs today
  for every date-relative sentence. It is frozen here by substituting the
  `date` class collect.py imported. Freezing it also settles the timezone
  problem: `date.today()` is local time while git author dates are not, so
  an unfrozen golden made on a laptop fails in a UTC runner for part of
  every day.
* The budget. collect() defaults to ten seconds and quietly drops
  analyzers when a loaded machine overruns it. A dropped analyzer changes
  the metrics, the score, and therefore the card.
* The seed. Line selection is crc32 of the repository's directory name,
  which the fixtures fix.

To approve a deliberate change, regenerate and read the diff before
committing it:

    SOMMELIER_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden
"""

from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path
from typing import Callable, Type
from unittest.mock import patch

import sommelier.collect as collect_module
from sommelier.collect import RepoMetrics, collect
from sommelier.judge import judge
from sommelier.render import render_card, render_sober
from sommelier.voice import pour

from tests import fixtures

GOLDEN_DIR = Path(__file__).parent / "golden"

# Far enough past every fixture's last commit to be stable, and chosen once
# so the bands each fixture lands in never move. Any change to this date
# rewrites every golden, which is the point: it is an input, not a detail.
FROZEN_TODAY = date(2026, 8, 12)

# Large enough that the budget never fires. The default ten seconds is a
# product decision for a person at a terminal, not a test fixture.
GOLDEN_BUDGET_SECONDS = 120.0

UPDATING = bool(os.environ.get("SOMMELIER_UPDATE_GOLDEN"))


def frozen_date_class(today: date) -> Type[date]:
    """A date subclass whose today() is fixed.

    Substituting the class rather than the module keeps fromisoformat and
    every other constructor working, which collect.py relies on to parse
    git output.
    """

    class FrozenDate(date):
        @classmethod
        def today(cls) -> "FrozenDate":
            return cls(today.year, today.month, today.day)

    return FrozenDate


class GoldenCase(unittest.TestCase):
    def measure(self, root: Path) -> RepoMetrics:
        with patch.object(collect_module, "date", frozen_date_class(FROZEN_TODAY)):
            metrics = collect(root, budget_seconds=GOLDEN_BUDGET_SECONDS)
        self.assertEqual(
            metrics.dropped,
            (),
            "an analyzer was dropped; the card would describe a partial run",
        )
        self.assertFalse(
            metrics.palate.sampled, "the file scan sampled; the card is not comparable"
        )
        return metrics

    def assert_golden(self, name: str, actual: str) -> None:
        path = GOLDEN_DIR / name
        if UPDATING:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8")
            self.skipTest(f"rewrote {name}")
        self.assertTrue(
            path.exists(),
            f"{name} does not exist; run with SOMMELIER_UPDATE_GOLDEN=1 to create it",
        )
        self.assertEqual(
            actual,
            path.read_text(encoding="utf-8"),
            f"{name} changed. Read the diff, then rerun with "
            f"SOMMELIER_UPDATE_GOLDEN=1 if the change is intended.",
        )

    def check(
        self, builder: Callable[[], fixtures.Fixture], slug: str, *, seed: int | None
    ) -> None:
        fixture = builder()
        self.addCleanup(fixture.cleanup)
        metrics = self.measure(fixture.path)
        judgement = judge(metrics)
        card = render_card(pour(metrics, judgement, seed=seed))
        suffix = "default-seed" if seed is None else f"seed{seed}"
        self.assert_golden(f"{slug}.{suffix}.txt", card + "\n")


class GoldenCardTest(GoldenCase):
    def test_healthy_python_repo(self) -> None:
        self.check(fixtures.healthy_python_repo, "healthy-python", seed=None)

    def test_neglected_js_repo(self) -> None:
        self.check(fixtures.neglected_js_repo, "neglected-js", seed=None)

    def test_bare_directory(self) -> None:
        self.check(fixtures.bare_directory, "bare-directory", seed=None)

    def test_git_repo_without_commits(self) -> None:
        self.check(fixtures.git_repo_without_commits, "no-commits", seed=None)

    def test_empty_directory(self) -> None:
        self.check(fixtures.empty_directory, "empty-directory", seed=None)

    def test_unknown_language_repo(self) -> None:
        self.check(fixtures.unknown_language_repo, "unknown-language", seed=None)

    def test_deep_and_long_repo(self) -> None:
        self.check(fixtures.deep_and_long_repo, "deep-and-long", seed=None)

    def test_explicit_seed_overrides_the_name(self) -> None:
        # A second reading of one repository, proving --seed reaches every
        # course and not only the tasting number.
        self.check(fixtures.healthy_python_repo, "healthy-python", seed=42)


class GoldenSoberTest(GoldenCase):
    """The metrics table. No prose, so this one moves only when a number does."""

    def test_healthy_python_sober(self) -> None:
        fixture = fixtures.healthy_python_repo()
        self.addCleanup(fixture.cleanup)
        metrics = self.measure(fixture.path)
        table = render_sober(metrics, judge(metrics))
        # The resolved repository path is the one absolute string in the
        # output and it lives in a fresh temp directory every run.
        redacted = table.replace(str(fixture.path), "<REPO>")
        self.assert_golden("healthy-python.sober.txt", redacted + "\n")


class FrozenClockTest(unittest.TestCase):
    """The freeze itself, because every golden above depends on it holding."""

    def test_frozen_clock_moves_days_since_last_commit(self) -> None:
        fixture = fixtures.healthy_python_repo()
        self.addCleanup(fixture.cleanup)
        readings = []
        for today in (date(2026, 8, 12), date(2027, 9, 16)):
            with patch.object(collect_module, "date", frozen_date_class(today)):
                readings.append(
                    collect(
                        fixture.path, budget_seconds=GOLDEN_BUDGET_SECONDS
                    ).git.days_since_last_commit
                )
        self.assertEqual(readings[1] - readings[0], 400)

    def test_frozen_clock_leaves_date_parsing_intact(self) -> None:
        # collect.py parses every git date through this class, so a
        # substitute that only knew how to answer today() would break the
        # thing it was meant to stabilise.
        frozen = frozen_date_class(FROZEN_TODAY)
        self.assertEqual(frozen.fromisoformat("2019-11-03"), date(2019, 11, 3))
        self.assertEqual(frozen.today(), FROZEN_TODAY)


if __name__ == "__main__":
    unittest.main()
