"""Differential oracles: recompute a metric independently and demand agreement.

An expected-value test written beside the fixture that produced it encodes the
author's model twice and then agrees with itself forever. These tests get their
answer from somewhere else entirely - git plumbing, or a line count written
without reference to how collect.py counts lines - so the two only agree when
both are right.

Where sommelier's definition is deliberate rather than incidental, the oracle
matches it on purpose and says so. Three rules matter:

* line counts use str.splitlines(), which counts a final line with no trailing
  newline and splits on \\r and \\f as well as \\n. Most fixtures here are
  written with ordinary trailing newlines and no exotic separators, so wc -l
  and splitlines() agree and the oracle stays honest. Where a fixture is built
  from exotic separators on purpose, splitlines() alone is the oracle and wc is
  not consulted, because wc counts newline bytes rather than lines.
* lines and markers are counted over the whole file, at any size. This used to
  read "every file is read to a 64 KiB cap, and the fixtures here are far
  smaller", which is how the cap survived: no fixture in this module was large
  enough to notice it. LargeFileOracleTest, ChunkSeamOracleTest and
  CorpusLineCountOracleTest are the fixtures that notice. The structural
  analysis still stops at a cap and records that it stopped, so nesting depth
  and function length are not compared against a whole-file oracle here.
* over SOURCE_SAMPLE_LIMIT files the scan switches to a stratified sample and
  the scan-derived numbers describe the sample, not the repository. Every test
  asserts the sample and budget guards before comparing anything.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Sequence

from sommelier.collect import (
    BINARY_SNIFF_BYTES,
    MAX_READ_BYTES,
    RepoMetrics,
    STREAM_CHUNK_BYTES,
    collect,
)

from tests import corpus, fixtures

# Generous enough that the budget never fires on a loaded machine. A dropped
# analyzer would shrink the metrics and the oracle would "disagree" about
# arithmetic that was never performed.
ORACLE_BUDGET_SECONDS = 120.0

SOURCE_SUFFIXES = (".py", ".js", ".go", ".rb")

# The reader takes the first BINARY_SNIFF_BYTES to decide whether the file is
# binary, then STREAM_CHUNK_BYTES at a time. Those two offsets are the seams,
# and a fixture that never reaches one cannot say anything about them.
SEAM_OFFSETS = (BINARY_SNIFF_BYTES, BINARY_SNIFF_BYTES + STREAM_CHUNK_BYTES)

LARGE_FILE_LINES = 4000
LARGE_FILE_NAME = "big.py"


def large_python_source(lines: int) -> str:
    """A file of exactly `lines` lines, wide enough to outgrow the read cap."""
    body = [
        f"CONSTANT_{index} = {index}  # padding, so the file outgrows the cap"
        for index in range(lines)
    ]
    return "\n".join(body) + "\n"


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


class LargeFileOracleTest(OracleCase):
    """A file past the read cap, counted by a reader that has no cap.

    This is the case the module could not reach. Every fixture above fits
    inside a single read, so a truncated count and a complete one are the
    same number and the oracle agreed with the defect. On psf/requests the
    difference was 1,850 against 3,094, a 40 percent undercount printed as
    the largest file with no mark on it.

    The oracle is the file itself, read once in one piece and split by
    CPython, which knows nothing about chunks, caps or budgets.
    """

    def setUp(self) -> None:
        self.fixture = fixtures.Fixture("large-file")
        self.addCleanup(self.fixture.cleanup)
        self.root = self.fixture.path
        fixtures.write_tree(
            self.root,
            {
                LARGE_FILE_NAME: large_python_source(LARGE_FILE_LINES),
                "small.py": "value = 1\n",
            },
        )
        self.big = self.root / LARGE_FILE_NAME
        self.metrics = self.measure(self.root)

    def independent_count(self) -> int:
        """The whole file, in one piece, split by somebody else's code."""
        return len(self.big.read_text(encoding="utf-8").splitlines())

    def test_the_fixture_reaches_past_the_cap_that_used_to_truncate(self) -> None:
        """Without this the test could pass on a file the cap never touched."""
        payload = self.big.read_bytes()
        self.assertGreater(len(payload), MAX_READ_BYTES * 2)
        truncated = len(
            payload[:MAX_READ_BYTES].decode("utf-8", errors="replace").splitlines()
        )
        self.assertLess(
            truncated,
            self.independent_count(),
            "a capped read would report the same number, so nothing is proved",
        )

    def test_largest_file_lines_matches_an_independent_count(self) -> None:
        self.assertEqual(self.metrics.palate.largest_file_path, LARGE_FILE_NAME)
        self.assertEqual(
            self.metrics.palate.largest_file_lines, self.independent_count()
        )
        self.assertEqual(self.metrics.palate.largest_file_lines, LARGE_FILE_LINES)

    def test_total_lines_match_an_independent_count(self) -> None:
        expected = sum(
            len((self.root / name).read_text(encoding="utf-8").splitlines())
            for name in (LARGE_FILE_NAME, "small.py")
        )
        self.assertEqual(self.metrics.palate.total_lines, expected)

    def test_the_count_also_matches_wc(self) -> None:
        # Second oracle, different tool. Sound here because the fixture ends
        # every line with a newline and holds no exotic separator.
        if shutil.which("wc") is None:
            self.skipTest("wc is not available on this machine")
        payload = self.big.read_bytes()
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(payload.count(b"\n"), self.independent_count())
        proc = subprocess.run(
            ["wc", "-l", LARGE_FILE_NAME],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        self.assertEqual(
            self.metrics.palate.largest_file_lines, int(proc.stdout.split()[0])
        )

    def test_the_read_is_recorded_as_complete_and_the_analysis_is_not(self) -> None:
        """The structural cap survives. Saying nothing about it did not."""
        coverage = self.metrics.coverage
        self.assertTrue(coverage.lines_complete)
        self.assertEqual(coverage.truncated_files, 0)
        self.assertFalse(coverage.structural_scan_complete)


class ChunkSeamOracleTest(OracleCase):
    """The seams between reads, where a streamed count can gain or lose a line.

    A seam can fall inside a line, between a carriage return and the newline
    that completes it, or inside a multi byte character. None of those is
    reachable by a fixture that fits in one read, and each is a place where
    the reassembly can quietly invent a line or drop one. The oracle is
    str.splitlines() over the whole payload, which is the definition the
    streamed splitter is written to reproduce.
    """

    def counted(self, payload: bytes) -> int:
        """What collect reports for one file holding exactly these bytes."""
        with fixtures.Fixture("seam") as fixture:
            (fixture.path / "body.py").write_bytes(payload)
            metrics = self.measure(fixture.path)
        return metrics.palate.largest_file_lines

    def expected(self, payload: bytes) -> int:
        """What CPython says, splitting the whole payload in one piece."""
        return len(payload.decode("utf-8", errors="replace").splitlines())

    def payload_across(self, seam: int, marker: bytes, *, before: int = 1) -> bytes:
        """Bytes whose `marker` starts `before` bytes ahead of `seam`.

        The lead is plain ASCII lines, so a byte offset and a character
        offset are the same number and the arithmetic stays readable.
        """
        filler = b"value = 1\n"
        start = seam - before
        lead = filler * (start // len(filler))
        pad = start - len(lead)
        if pad:
            lead += b"#" * (pad - 1) + b"\n"
        payload = lead + marker + filler * 400
        self.assertEqual(
            payload[start : start + len(marker)],
            marker,
            "the fixture does not put the marker where the test claims",
        )
        return payload

    def test_a_carriage_return_and_its_newline_land_in_different_chunks(self) -> None:
        for seam in SEAM_OFFSETS:
            with self.subTest(seam=seam):
                payload = self.payload_across(seam, b"\r\n")
                self.assertEqual(payload[seam - 1 : seam + 1], b"\r\n")
                self.assertEqual(self.counted(payload), self.expected(payload))

    def test_a_carriage_return_alone_ends_the_chunk(self) -> None:
        """A lone CR is a line break, and the next chunk must not undo it."""
        for seam in SEAM_OFFSETS:
            with self.subTest(seam=seam):
                payload = self.payload_across(seam, b"\rvalue = 2\n")
                self.assertEqual(self.counted(payload), self.expected(payload))

    def test_a_multi_byte_character_straddles_a_seam(self) -> None:
        # Four bytes in UTF-8, from a range no house rule bans.
        glyph = chr(0x10437).encode("utf-8")
        self.assertEqual(len(glyph), 4)
        for before in (1, 2, 3):
            for seam in SEAM_OFFSETS:
                with self.subTest(before=before, seam=seam):
                    payload = self.payload_across(seam, glyph + b"\n", before=before)
                    self.assertGreaterEqual(payload[seam], 0x80)
                    self.assertLess(payload[seam], 0xC0)
                    self.assertEqual(self.counted(payload), self.expected(payload))

    def test_exotic_separators_and_a_missing_final_newline(self) -> None:
        """splitlines() breaks on more than the newline, and so must the stream.

        wc is not consulted here on purpose: it counts newline bytes, and
        this payload is mostly separators that are not one.
        """
        separators = (0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029)
        block = "".join(
            f"value {index}{chr(point)}" for index, point in enumerate(separators)
        )
        payload = (block * 1200 + "tail with no final newline").encode("utf-8")
        self.assertGreater(len(payload), SEAM_OFFSETS[-1])
        self.assertEqual(self.counted(payload), self.expected(payload))


class CorpusLineCountOracleTest(OracleCase):
    """The pinned corpus, recounted with a reader that shares no code.

    A synthetic fixture holds what somebody thought to put in it. These are
    real files: a 3,094 line test module, a quarter megabyte of generated
    documentation, a 2,878 line Rust suite. Three of the ten are longer than
    a single read, which is why three of the ten used to be reported wrong.

    Skips without the cache, which is populated by hand:

        python3 -m tests.corpus --sync
    """

    def setUp(self) -> None:
        # Reading the cache asks git which commit each clone sits on.
        fixtures.require_git()
        self.cached = [
            entry
            for entry in corpus.load_manifest()
            if corpus.cached_commit(entry) is not None
        ]
        if not self.cached:
            self.skipTest(
                "corpus cache is empty; run `python3 -m tests.corpus --sync`"
            )

    def test_largest_file_lines_matches_an_independent_count(self) -> None:
        past_the_cap = 0
        for entry in self.cached:
            with self.subTest(entry.slug):
                metrics = self.measure(entry.path)
                rel = metrics.palate.largest_file_path
                self.assertIsNotNone(rel, f"{entry.slug} reports no largest file")
                assert rel is not None  # narrowed for mypy; asserted above
                payload = entry.path.joinpath(*rel.split("/")).read_bytes()
                expected = len(
                    payload.decode("utf-8", errors="replace").splitlines()
                )
                self.assertEqual(
                    metrics.palate.largest_file_lines,
                    expected,
                    f"{entry.slug} says {rel} is "
                    f"{metrics.palate.largest_file_lines} lines, and it is "
                    f"{expected}",
                )
                if payload.endswith(b"\n") and payload.count(b"\n") == expected:
                    self.assert_wc_agrees(entry.path, rel, expected)
                if len(payload) <= MAX_READ_BYTES:
                    continue
                past_the_cap += 1
                truncated = len(
                    payload[:MAX_READ_BYTES]
                    .decode("utf-8", errors="replace")
                    .splitlines()
                )
                self.assertNotEqual(
                    metrics.palate.largest_file_lines,
                    truncated,
                    f"{entry.slug} still reports the capped count for {rel}",
                )
        self.assertGreater(
            past_the_cap,
            0,
            "no cached repository has a largest file past the read cap, so "
            "this test cannot show that the cap is gone",
        )

    def assert_wc_agrees(self, root: Path, rel: str, expected: int) -> None:
        """Second oracle, and a different tool, where wc -l is comparable."""
        if shutil.which("wc") is None:
            return
        proc = subprocess.run(
            ["wc", "-l", rel],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        self.assertEqual(int(proc.stdout.split()[0]), expected)


if __name__ == "__main__":
    unittest.main()
