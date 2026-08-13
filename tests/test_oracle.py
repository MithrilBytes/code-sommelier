"""Differential oracles: recompute a metric independently and demand agreement.

An expected-value test written beside the fixture that produced it encodes the
author's model twice and then agrees with itself forever. These tests get their
answer from somewhere else entirely - git plumbing, or a line count written
without reference to how collect.py counts lines - so the two only agree when
both are right.

Where sommelier's definition is deliberate rather than incidental, the oracle
matches it on purpose and says so. Three rules matter:

* line counts use str.splitlines(), which counts a final line with no trailing
  newline and splits on \\r and \\f as well as \\n. The fixtures here are written
  with ordinary trailing newlines and no exotic separators, so wc -l and
  splitlines() agree and the oracle stays honest.
* every file is read to a 64 KiB cap. The fixtures here are far smaller.
* over SOURCE_SAMPLE_LIMIT files the scan switches to a stratified sample and
  the scan-derived numbers describe the sample, not the repository. Every test
  asserts the sample and budget guards before comparing anything.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Sequence

from sommelier.collect import RepoMetrics, collect

from tests import fixtures

# Generous enough that the budget never fires on a loaded machine. A dropped
# analyzer would shrink the metrics and the oracle would "disagree" about
# arithmetic that was never performed.
ORACLE_BUDGET_SECONDS = 120.0

SOURCE_SUFFIXES = (".py", ".js", ".go", ".rb")


def git_lines(root: Path, args: Sequence[str]) -> list[str]:
    """Raw git output, split into lines. The oracle's source of truth."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return [line for line in proc.stdout.splitlines() if line]


class OracleCase(unittest.TestCase):
    """Shared guards. Nothing derived from a scan is comparable without them."""

    def measure(self, root: Path) -> RepoMetrics:
        metrics = collect(root, budget_seconds=ORACLE_BUDGET_SECONDS)
        self.assertEqual(
            metrics.dropped,
            (),
            "an analyzer was dropped, so the metrics describe a partial run",
        )
        self.assertFalse(
            metrics.palate.sampled,
            "the file scan sampled, so scan metrics describe a subset",
        )
        return metrics


class GitHistoryOracleTest(OracleCase):
    """git computes the answer, not the test. As independent as it gets."""

    def setUp(self) -> None:
        self.fixture = fixtures.healthy_python_repo()
        self.addCleanup(self.fixture.cleanup)
        self.root = self.fixture.path
        self.metrics = self.measure(self.root)

    def test_commit_count_matches_rev_list(self) -> None:
        expected = int(git_lines(self.root, ["rev-list", "--count", "HEAD"])[0])
        self.assertEqual(self.metrics.git.commit_count, expected)

    def test_author_count_matches_distinct_an(self) -> None:
        # %an, not %aN: .mailmap is deliberately not applied, and the key is
        # the raw name string, so two emails under one name count once.
        names = git_lines(self.root, ["log", "--pretty=format:%an"])
        self.assertEqual(self.metrics.git.author_count, len(set(names)))

    def test_top_author_matches_manual_tally(self) -> None:
        names = git_lines(self.root, ["log", "--pretty=format:%an"])
        tally = Counter(names)
        # Ties go to the lexicographically smallest name by codepoint.
        winner = min(tally, key=lambda name: (-tally[name], name))
        self.assertEqual(self.metrics.git.top_author_name, winner)
        self.assertEqual(self.metrics.git.top_author_commits, tally[winner])
        self.assertEqual(
            self.metrics.git.top_author_share,
            round(tally[winner] / sum(tally.values()), 4),
        )

    def test_commit_dates_are_the_extremes_of_author_dates(self) -> None:
        # Author dates, and the min/max across all commits rather than the
        # root commit and HEAD. A cherry-pick can make those differ.
        dates = sorted(git_lines(self.root, ["log", "--date=short", "--pretty=format:%ad"]))
        self.assertEqual(self.metrics.git.first_commit_date, dates[0])
        self.assertEqual(self.metrics.git.last_commit_date, dates[-1])
        self.assertEqual(self.metrics.git.first_commit_year, int(dates[0][:4]))
        self.assertEqual(self.metrics.git.last_commit_year, int(dates[-1][:4]))

    def test_last_subject_is_head_not_the_newest_date(self) -> None:
        expected = git_lines(self.root, ["log", "-1", "--pretty=format:%s"])[0]
        self.assertEqual(self.metrics.git.last_commit_subject, expected)

    def test_fix_ratio_matches_the_documented_pattern(self) -> None:
        # Subject line only, counted once per commit, never the body.
        pattern = re.compile(r"\bfix(e[sd])?\b", re.IGNORECASE)
        subjects = git_lines(self.root, ["log", "--pretty=format:%s"])
        hits = sum(1 for subject in subjects if pattern.search(subject))
        self.assertEqual(self.metrics.git.fix_commit_count, hits)
        self.assertEqual(self.metrics.git.fix_ratio, round(hits / len(subjects), 4))

    def test_longest_gap_is_over_distinct_days(self) -> None:
        days = sorted(
            {
                date.fromisoformat(value).toordinal()
                for value in git_lines(
                    self.root, ["log", "--date=short", "--pretty=format:%ad"]
                )
            }
        )
        expected = max(
            (later - earlier for earlier, later in zip(days, days[1:])),
            default=0,
        )
        self.assertEqual(self.metrics.git.longest_gap_days, expected)


class FileScanOracleTest(OracleCase):
    """Line counts recomputed from the file set git says belongs to the repo."""

    def setUp(self) -> None:
        self.fixture = fixtures.healthy_python_repo()
        self.addCleanup(self.fixture.cleanup)
        self.root = self.fixture.path
        self.metrics = self.measure(self.root)

    def project_files(self) -> list[str]:
        """Tracked plus untracked-not-ignored: what git calls the project."""
        return git_lines(
            self.root, ["ls-files", "--cached", "--others", "--exclude-standard"]
        )

    def source_files(self) -> list[str]:
        return [
            name for name in self.project_files() if name.endswith(SOURCE_SUFFIXES)
        ]

    def test_source_file_count_matches_git_inventory(self) -> None:
        self.assertEqual(self.metrics.palate.inventory, "git")
        self.assertEqual(
            self.metrics.palate.source_file_count, len(self.source_files())
        )

    def test_total_lines_match_an_independent_count(self) -> None:
        expected = sum(
            len((self.root / name).read_text(encoding="utf-8").splitlines())
            for name in self.source_files()
        )
        self.assertEqual(self.metrics.palate.total_lines, expected)

    def test_total_lines_also_match_wc(self) -> None:
        # Second oracle, different tool. Only sound because these fixtures end
        # every file with a newline; wc -l counts terminators, not lines.
        names = self.source_files()
        for name in names:
            self.assertTrue(
                (self.root / name).read_bytes().endswith(b"\n"),
                f"{name} has no trailing newline; wc -l would undercount",
            )
        proc = subprocess.run(
            ["wc", "-l", *names],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        counts = [
            int(line.split()[0]) for line in proc.stdout.splitlines() if line.strip()
        ]
        total = counts[-1] if len(names) > 1 else counts[0]
        self.assertEqual(self.metrics.palate.total_lines, total)

    def test_largest_file_is_the_longest_of_the_set(self) -> None:
        measured = {
            name: len((self.root / name).read_text(encoding="utf-8").splitlines())
            for name in self.source_files()
        }
        expected = max(measured.values())
        self.assertEqual(self.metrics.palate.largest_file_lines, expected)
        self.assertIsNotNone(self.metrics.palate.largest_file_path)
        winner = self.metrics.palate.largest_file_path
        assert winner is not None  # narrowed for mypy; asserted above
        self.assertEqual(measured[winner], expected)

    def test_average_lines_is_total_over_count(self) -> None:
        expected = round(
            self.metrics.palate.total_lines / self.metrics.palate.source_file_count, 4
        )
        self.assertEqual(self.metrics.palate.average_lines, expected)


class AuthorIdentityOracleTest(OracleCase):
    """The author key is the raw %an, and .mailmap is deliberately not applied.

    This was found by mutation: switching the log format from %an to %aN
    passed the entire suite. It is not a harmless change - a mailmap exists
    precisely to collapse identities, so applying one moves author_count,
    top_author_share, and the bus-factor finding that reads them. The
    behaviour needed pinning in whichever direction it is meant to point.
    """

    def setUp(self) -> None:
        self.fixture = fixtures.Fixture("mailmapped")
        self.addCleanup(self.fixture.cleanup)
        root = self.fixture.path
        fixtures.git_init(root)

        # One human, two spellings, plus a second human so the tally has
        # something to rank against.
        fixtures.write_tree(root, {"a.py": "value = 1\n"})
        fixtures.git_commit(
            root, "Add a value", day="2024-01-01",
            author_name=fixtures.ADA_NAME, author_email=fixtures.ADA_EMAIL,
        )
        fixtures.write_tree(root, {"b.py": "value = 2\n"})
        fixtures.git_commit(
            root, "Add another value", day="2024-01-02",
            author_name="A. Lovelace", author_email="alt@example.invalid",
        )
        fixtures.write_tree(root, {"c.py": "value = 3\n"})
        fixtures.git_commit(
            root, "Add a third value", day="2024-01-03",
            author_name=fixtures.GRACE_NAME, author_email=fixtures.GRACE_EMAIL,
        )
        # Committed after the history it describes, exactly as a real one is.
        fixtures.write_tree(
            root,
            {
                ".mailmap": (
                    f"{fixtures.ADA_NAME} <{fixtures.ADA_EMAIL}> "
                    f"A. Lovelace <alt@example.invalid>\n"
                )
            },
        )
        fixtures.git_commit(
            root, "Add a mailmap", day="2024-01-04",
            author_name=fixtures.GRACE_NAME, author_email=fixtures.GRACE_EMAIL,
        )
        self.root = root
        self.metrics = self.measure(root)

    def test_the_fixture_actually_exercises_the_difference(self) -> None:
        """Without this, the assertions below could pass for the wrong reason."""
        raw = set(git_lines(self.root, ["log", "--pretty=format:%an"]))
        mapped = set(git_lines(self.root, ["log", "--pretty=format:%aN"]))
        self.assertEqual(len(raw), 3, "the fixture should hold three raw names")
        self.assertEqual(len(mapped), 2, "the mailmap should collapse two of them")

    def test_author_count_uses_raw_names_not_the_mailmap(self) -> None:
        self.assertEqual(self.metrics.git.author_count, 3)

    def test_top_author_share_uses_raw_names(self) -> None:
        # Grace has 2 of 4 either way; Ada's two spellings must stay apart.
        self.assertEqual(self.metrics.git.top_author_name, fixtures.GRACE_NAME)
        self.assertEqual(self.metrics.git.top_author_commits, 2)
        self.assertEqual(self.metrics.git.top_author_share, 0.5)


class NeglectedRepoOracleTest(OracleCase):
    """The messy fixture: vendored trees and committed sediment must not leak."""

    def setUp(self) -> None:
        self.fixture = fixtures.neglected_js_repo()
        self.addCleanup(self.fixture.cleanup)
        self.root = self.fixture.path
        self.metrics = self.measure(self.root)

    def test_source_count_excludes_vendored_trees(self) -> None:
        listed = git_lines(
            self.root, ["ls-files", "--cached", "--others", "--exclude-standard"]
        )
        # node_modules is pruned by name regardless of what git reports, so the
        # oracle applies the same prune rather than pretending it does not.
        expected = [
            name
            for name in listed
            if name.endswith(SOURCE_SUFFIXES)
            and not any(part == "node_modules" for part in Path(name).parts)
        ]
        self.assertEqual(self.metrics.palate.source_file_count, len(expected))

    def test_commit_count_matches_rev_list(self) -> None:
        expected = int(git_lines(self.root, ["rev-list", "--count", "HEAD"])[0])
        self.assertEqual(self.metrics.git.commit_count, expected)


if __name__ == "__main__":
    unittest.main()
