"""Measurements of real repositories, compared against committed snapshots.

These catch what neither the fixtures nor the property tests can: a change
that is correct on everything anyone thought to build, and wrong on a tree
somebody actually wrote. The whole corpus takes a few seconds.

They skip when the cache is absent, so a clone of this repository still
runs a green suite without touching the network. Populate it with:

    python3 -m tests.corpus --sync

A snapshot difference is not automatically a failure - improving a metric
changes them by design. Read the diff, then approve it with:

    python3 -m tests.corpus --snapshot
"""

from __future__ import annotations

import json
import unittest
from typing import Any, cast
from unittest.mock import patch

import sommelier.collect as collect_module
from sommelier.collect import collect
from sommelier.judge import BANDS, REFUSALS, judge
from sommelier.render import render_card
from sommelier.voice import pour

from tests import corpus


class CorpusSnapshotTest(unittest.TestCase):
    def test_manifest_is_well_formed(self) -> None:
        """Runs without the cache, so a bad manifest is caught either way."""
        entries = corpus.load_manifest()
        self.assertGreaterEqual(len(entries), 5)
        slugs = [entry.slug for entry in entries]
        self.assertEqual(len(slugs), len(set(slugs)), "duplicate slug in the manifest")
        for entry in entries:
            with self.subTest(entry.slug):
                self.assertEqual(
                    len(entry.commit), 40, "pin the full commit, not an abbreviation"
                )
                self.assertTrue(entry.url.startswith("https://"))
                self.assertTrue(entry.note, "say why the entry earns its place")

    def test_every_entry_has_a_snapshot(self) -> None:
        for entry in corpus.load_manifest():
            with self.subTest(entry.slug):
                self.assertTrue(
                    corpus.snapshot_path(entry).exists()
                    and corpus.judgement_path(entry).exists(),
                    f"no snapshot for {entry.slug}; run "
                    f"`python3 -m tests.corpus --sync --snapshot`",
                )

    def test_measurements_match_the_snapshots(self) -> None:
        entries = corpus.load_manifest()
        cached = [e for e in entries if corpus.cached_commit(e) is not None]
        if not cached:
            self.skipTest(
                "corpus cache is empty; run `python3 -m tests.corpus --sync`"
            )

        for entry in cached:
            with self.subTest(entry.slug):
                self.assertEqual(
                    corpus.cached_commit(entry),
                    entry.commit,
                    f"{entry.slug} is checked out at the wrong commit; "
                    f"run `python3 -m tests.corpus --sync`",
                )
                expected: dict[str, Any] = corpus.read_snapshot(entry)
                actual = corpus.measure(entry)
                # Compared half by half, so the failure names which layer moved.
                self.assertEqual(
                    actual["metrics"],
                    expected["metrics"],
                    f"{entry.slug} MEASURES differently than its snapshot. This is "
                    f"a collect layer change. Read the diff; if intended, rerun "
                    f"`python3 -m tests.corpus --snapshot`.",
                )
                self.assertEqual(
                    actual["judgement"],
                    expected["judgement"],
                    f"{entry.slug} is JUDGED differently than its snapshot, on "
                    f"identical measurements. Read the diff; if intended, rerun "
                    f"`python3 -m tests.corpus --snapshot`.",
                )


class CorpusInvariantTest(unittest.TestCase):
    """Properties that must hold for every real repository, snapshot aside.

    A snapshot says "this number was 59". These say "this number can never
    be negative", which keeps holding after someone approves a new
    snapshot without reading it closely.
    """

    def setUp(self) -> None:
        self.cached = [
            e for e in corpus.load_manifest() if corpus.cached_commit(e) is not None
        ]
        if not self.cached:
            self.skipTest(
                "corpus cache is empty; run `python3 -m tests.corpus --sync`"
            )

    def test_invariants_hold_across_the_corpus(self) -> None:
        for entry in self.cached:
            with self.subTest(entry.slug):
                payload = corpus.measure(entry)
                metrics = payload["metrics"]
                palate = metrics["palate"]
                git = metrics["git"]
                judgement = payload["judgement"]

                self.assertEqual(palate["inventory"], "git")
                self.assertFalse(palate["sampled"], "corpus entry large enough to sample")
                self.assertGreaterEqual(palate["source_file_count"], 0)
                self.assertGreaterEqual(palate["total_lines"], 0)
                self.assertLessEqual(
                    palate["largest_file_lines"],
                    palate["total_lines"],
                    "one file cannot hold more lines than the whole repository",
                )
                self.assertGreaterEqual(git["commit_count"], 1)
                self.assertGreaterEqual(git["author_count"], 1)
                self.assertLessEqual(git["top_author_commits"], git["commit_count"])
                self.assertGreaterEqual(git["fix_commit_count"], 0)
                self.assertLessEqual(git["fix_commit_count"], git["commit_count"])
                self.assertLessEqual(
                    git["first_commit_date"],
                    git["last_commit_date"],
                    "the first commit cannot postdate the last",
                )
                self.assertGreaterEqual(git["days_since_last_commit"], 0)
                self.assert_scoring_is_coherent(judgement)

    def assert_scoring_is_coherent(self, judgement: dict[str, Any]) -> None:
        """The score, its band and its denominator have to agree with each other.

        A snapshot says the number was 83. This says the number is inside the
        band it claims, that a refused repository carries a reason rather than
        a quietly zeroed score, and that the denominator was printed.
        """
        bands = cast(
            "tuple[tuple[str, int, int, str], ...]", BANDS["score_bands"]
        )
        edges = {name: (low, high) for name, low, high, _ in bands}
        self.assertGreater(judgement["total_dimensions"], 0)
        self.assertLessEqual(
            judgement["scored_dimensions"], judgement["total_dimensions"]
        )
        if judgement["score"] is None:
            self.assertEqual("unscoreable", judgement["band"])
            self.assertIn(judgement["refusal"], REFUSALS)
            return
        self.assertIsNone(judgement["refusal"])
        low, high = edges[judgement["band"]]
        self.assertTrue(
            low <= judgement["score"] <= high,
            f"score {judgement['score']} is outside band {judgement['band']}",
        )

    def test_card_renders_for_every_entry(self) -> None:
        """No real repository may crash the renderer or emit an overlong line."""
        for entry in self.cached:
            with self.subTest(entry.slug):
                with patch.object(
                    collect_module,
                    "date",
                    corpus.frozen_date_class(corpus.FROZEN_TODAY),
                ):
                    metrics = collect(
                        entry.path, budget_seconds=corpus.CORPUS_BUDGET_SECONDS
                    )
                card = render_card(pour(metrics, judge(metrics)))
                self.assertTrue(card.startswith("CODE SOMMELIER"))
                for line in card.splitlines():
                    self.assertLessEqual(len(line), 79, f"{entry.slug}: {line!r}")


if __name__ == "__main__":
    unittest.main()
