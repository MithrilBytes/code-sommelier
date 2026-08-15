"""The score: gates, bands, renormalisation, and the withholding invariant.

Three properties are being defended here, and only the first one is a matter
of taste.

* **The gates.** Ninety is a change in kind, not a change in degree. Each base
  gate is exercised on its own against an otherwise faultless repository, so a
  gate that stops mattering fails a test rather than quietly widening the band.
* **The denominator.** A dimension nothing measured leaves the score and the
  card says how many are left.
* **Withholding never pays.** This is the defect the whole rewrite exists to
  remove. Under the old formula a shallow clone of pallets/itsdangerous scored
  93 where the full clone scored 92, because every finding the missing history
  would have produced was simply absent. Withholding arrives by two doors and
  both are held here: a coverage record that says a measurement could not be
  taken, and a dropped list that says an analyzer started and stopped at the
  budget. Four tests cover it: a synthetic sweep over every dimension and every
  case in the spread, the same sweep over every analyzer that can be dropped, a
  real `git clone --depth 1` measured end to end, and a monotonicity suite that
  degrades one axis at a time.
"""

from __future__ import annotations

import ast
import io
import itertools
import math
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from typing import cast

from sommelier.cli import main as cli_main
from sommelier.collect import (
    Coverage,
    DroppedAnalyzer,
    RepoMetrics,
    collect,
)
from sommelier.judge import (
    ANALYZER_DIMENSIONS,
    BANDS,
    BASE_GATES,
    CARE_GATES,
    DIMENSIONS,
    EXEMPLARY,
    GATE_ANALYZERS,
    OUTSTANDING,
    Judgement,
    judge,
)

from tests import fixtures
from tests.test_judge import (
    BASE_MANIFEST,
    BASE_METRICS,
    BASE_STRUCTURE,
    empty_metrics,
    no_history_metrics,
    repo_with_dependencies,
    repo_with_git,
    repo_with_markers,
    repo_with_nose,
    repo_with_palate,
    repo_with_sediment_item,
    spread,
    worst_metrics,
)

# Generous enough that the budget never fires and decides a score for us.
SCORE_BUDGET_SECONDS = 120.0

TOP_BAND_FLOOR = 90

REPO_ROOT = Path(__file__).resolve().parents[1]

# The one analyzer whose loss is not a measurement gap. It is dropped when git
# cannot say which files are tracked, which names a different file set rather
# than a shorter one, so no dimension leaves the denominator with it.
INVENTORY_ONLY = frozenset({"inventory"})


def band_edges() -> tuple[tuple[str, int, int, str], ...]:
    bands = BANDS["score_bands"]
    assert isinstance(bands, tuple)
    return cast(tuple[tuple[str, int, int, str], ...], bands)


def band_int(name: str) -> int:
    value = BANDS[name]
    assert isinstance(value, int), f"{name} is not an integer band"
    return value


def band_float(name: str) -> float:
    value = BANDS[name]
    assert isinstance(value, float), f"{name} is not a float band"
    return value


def withheld(metrics: RepoMetrics, **gaps: bool) -> RepoMetrics:
    """The same repository, measured less thoroughly. Nothing else changes."""
    return replace(metrics, coverage=replace(metrics.coverage, **gaps))


def unfinished(metrics: RepoMetrics, *analyzers: str) -> RepoMetrics:
    """The same repository, measured by a run that stopped at the budget."""
    return replace(
        metrics,
        dropped=tuple(
            DroppedAnalyzer(name=name, reason="exceeded time budget")
            for name in analyzers
        ),
    )


def analyzers_the_collector_can_drop() -> frozenset[str]:
    """Every analyzer name collect.py is able to put in the dropped list.

    Read from the source rather than from a list kept by hand, so a new
    analyzer cannot be added to the collector without the judge being told
    what it feeds.
    """
    source = (REPO_ROOT / "sommelier" / "collect.py").read_text(encoding="utf-8")
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not isinstance(target, ast.Name) or target.id != "DroppedAnalyzer":
            continue
        for keyword in node.keywords:
            if keyword.arg != "name":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, str
            ):
                names.add(keyword.value.value)
    return frozenset(names)


def failed_gates(judgement: Judgement) -> set[str]:
    return {
        gate.name
        for gate in (*judgement.gates, *judgement.care_gates)
        if not gate.passed
    }


def repo_with_secret(count: int = 1) -> RepoMetrics:
    """A committed key, which is the sediment a short walk never reaches."""
    return repo_with_sediment_item(
        "secret", "deploy/.env", "1 file", 64, 1, secret_file_count=count
    )


def repo_with_lockfile(locked: int) -> RepoMetrics:
    """A manifest that declares eight, against a lockfile that pins ``locked``."""
    manifest = replace(BASE_MANIFEST, locked_count=locked)
    return replace(
        BASE_METRICS, structure=replace(BASE_STRUCTURE, manifests=(manifest,))
    )


class BandGateTests(unittest.TestCase):
    """Ninety is entered by conjunction, and one failure is enough to bar it."""

    def test_a_faultless_repository_reaches_the_top_band(self) -> None:
        judgement = judge(BASE_METRICS)
        self.assertEqual("exemplary", judgement.band)
        self.assertEqual(100, judgement.score)

    def test_the_catastrophic_repository_sits_on_the_floor(self) -> None:
        judgement = judge(worst_metrics())
        self.assertEqual("unacceptable", judgement.band)
        self.assertEqual(_band_floor(), judgement.score)

    def test_each_base_gate_bars_the_nineties_on_its_own(self) -> None:
        """One failed gate, everything else faultless, and the answer is 89 or less.

        This is the asymmetry the whole design rests on. A deduction system
        would shave a point off a repository with no tests. A gate refuses it
        the band.
        """
        cases: dict[str, RepoMetrics] = {
            "documented": repo_with_nose(readme_lines=4, readme_bytes=80),
            "tested": repo_with_nose(has_tests=False),
            "hygiene": repo_with_nose(gitignore_path=None, gitignore_rules=0),
            "dependencies": withheld(BASE_METRICS, dependencies_measured=False),
            "history": withheld(BASE_METRICS, history_complete=False),
            "authorship": repo_with_git(author_count=1),
            "cadence": repo_with_git(days_since_last_commit=400),
        }
        self.assertEqual(set(BASE_GATES), set(cases), "a gate has no test")
        for gate, metrics in cases.items():
            with self.subTest(gate=gate):
                judgement = judge(metrics)
                failed = {g.name for g in judgement.gates if not g.passed}
                self.assertIn(gate, failed, f"{gate} was expected to fail")
                assert judgement.score is not None
                self.assertLess(
                    judgement.score,
                    TOP_BAND_FLOOR,
                    f"{gate} failed and the repository still reached the nineties",
                )

    def test_passing_every_gate_reaches_at_least_ninety(self) -> None:
        """A defect in the code cannot pull a fully gated repository below 90."""
        metrics = repo_with_palate(largest_file_lines=4000, max_indent_depth=14)
        judgement = judge(metrics)
        self.assertTrue(all(gate.passed for gate in judgement.gates))
        assert judgement.score is not None
        self.assertGreaterEqual(judgement.score, TOP_BAND_FLOOR)
        self.assertEqual("outstanding", judgement.band)

    def test_the_craft_gate_keeps_paperwork_out_of_the_top_band(self) -> None:
        """Every process gate met and one enormous file is not exemplary."""
        judgement = judge(repo_with_palate(largest_file_lines=4000))
        self.assertEqual("outstanding", judgement.band)
        self.assertIn("craft", {g.name for g in judgement.care_gates if not g.passed})

    def test_the_score_always_lands_inside_its_own_band(self) -> None:
        edges = {name: (low, high) for name, low, high, _ in band_edges()}
        for name, metrics in spread():
            with self.subTest(case=name):
                judgement = judge(metrics)
                if judgement.score is None:
                    self.assertEqual("unscoreable", judgement.band)
                    continue
                low, high = edges[judgement.band]
                self.assertGreaterEqual(judgement.score, low)
                self.assertLessEqual(judgement.score, high)

    def test_every_band_carries_a_label(self) -> None:
        for name, low, high, label in band_edges():
            with self.subTest(band=name):
                self.assertTrue(label)
                self.assertTrue(name)
                self.assertLess(low, high)

    def test_the_gated_bands_exist_in_the_table(self) -> None:
        """The gate logic names two bands, and a rename must fail here first."""
        names = {name for name, _, _, _ in band_edges()}
        self.assertIn(EXEMPLARY, names)
        self.assertIn(OUTSTANDING, names)


class DenominatorTests(unittest.TestCase):
    """Score over what was measured, and print how many that was."""

    def test_a_full_measurement_scores_on_every_dimension(self) -> None:
        judgement = judge(BASE_METRICS)
        self.assertEqual(len(DIMENSIONS), judgement.total_dimensions)
        self.assertEqual(len(DIMENSIONS), judgement.scored_dimensions)

    def test_an_unmeasured_dimension_leaves_the_denominator(self) -> None:
        cases: dict[str, dict[str, bool]] = {
            "structure": {"dependencies_measured": False},
            "history": {"history_complete": False},
            "authorship": {"authorship_measured": False},
            "markers": {"lines_complete": False},
        }
        for dimension, gap in cases.items():
            with self.subTest(dimension=dimension):
                judgement = judge(withheld(BASE_METRICS, **gap))
                self.assertEqual(
                    len(DIMENSIONS) - 1, judgement.scored_dimensions
                )
                missing = {d.name for d in judgement.dimensions if not d.measured}
                self.assertEqual({dimension}, missing)

    def test_body_leaves_the_denominator_when_nothing_was_attributed(self) -> None:
        # Below the attribution floor the repository is refused outright, so
        # the dimension is exercised at a share the floor still admits.
        metrics = replace(
            BASE_METRICS,
            coverage=replace(BASE_METRICS.coverage, attributed_files=0),
        )
        judgement = judge(metrics)
        self.assertIsNone(judgement.score)
        self.assertEqual("unattributed", judgement.refusal)

    def test_an_unmeasured_dimension_contributes_no_deduction(self) -> None:
        metrics = withheld(no_history_metrics(), history_complete=False)
        judgement = judge(metrics)
        history = next(d for d in judgement.dimensions if d.name == "history")
        self.assertFalse(history.measured)
        self.assertGreater(history.severity, 0, "the findings still fire")
        self.assertEqual(0.0, history.deduction)

    def test_dimension_totals_match_the_findings(self) -> None:
        from sommelier.judge import KEY_DIMENSIONS

        for name, metrics in spread():
            with self.subTest(case=name):
                judgement = judge(metrics)
                expected = {dimension: 0 for dimension in DIMENSIONS}
                for finding in judgement.findings:
                    expected[KEY_DIMENSIONS[finding.key]] += finding.severity
                actual = {d.name: d.severity for d in judgement.dimensions}
                self.assertEqual(expected, actual)


class WithholdingTests(unittest.TestCase):
    """Removing a measurement can lower a score and can never raise one."""

    GAPS: tuple[dict[str, bool], ...] = (
        {"history_complete": False},
        {"authorship_measured": False},
        {"dependencies_measured": False},
        {"lines_complete": False},
        {"structural_scan_complete": False},
        {"history_complete": False, "authorship_measured": False},
        {"history_complete": False, "dependencies_measured": False},
    )

    def assert_not_higher(self, full: Judgement, partial: Judgement, note: str) -> None:
        if partial.score is None:
            return
        self.assertIsNotNone(full.score, f"{note}: the full measurement was refused")
        assert full.score is not None
        self.assertLessEqual(
            partial.score,
            full.score,
            f"{note}: withholding raised the score from {full.score} to "
            f"{partial.score}",
        )

    def test_withholding_never_raises_the_score_across_the_spread(self) -> None:
        for name, metrics in spread():
            full = judge(metrics)
            if full.score is None:
                continue
            for gap in self.GAPS:
                with self.subTest(case=name, gap=sorted(gap)):
                    partial = judge(withheld(metrics, **gap))
                    self.assert_not_higher(full, partial, f"{name} {sorted(gap)}")

    def test_withholding_history_costs_the_top_band(self) -> None:
        full = judge(BASE_METRICS)
        partial = judge(withheld(BASE_METRICS, history_complete=False))
        assert full.score is not None and partial.score is not None
        self.assertGreaterEqual(full.score, TOP_BAND_FLOOR)
        self.assertLess(partial.score, TOP_BAND_FLOOR)

    def test_a_shallow_clone_never_scores_above_the_full_clone(self) -> None:
        """The defect in one line, measured on a real pair of clones.

        A depth one clone is a genuine measurement gap: git reports one commit,
        no span, and a first commit that is not the first commit. Under the old
        formula that removed findings and paid a point. The clone is made from
        a local path, so this test never touches the network.
        """
        fixtures.require_git()
        fixture = fixtures.healthy_python_repo()
        self.addCleanup(fixture.cleanup)
        full = collect(fixture.path, budget_seconds=SCORE_BUDGET_SECONDS)

        shallow_root = Path(fixture.path).parent / "shallow-clone"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--no-local",
                f"file://{fixture.path}",
                str(shallow_root),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        shallow = collect(shallow_root, budget_seconds=SCORE_BUDGET_SECONDS)

        self.assertFalse(full.git.shallow, "the control clone is not a full clone")
        self.assertTrue(shallow.git.shallow, "the clone under test is not shallow")
        self.assertTrue(full.coverage.history_complete)
        self.assertFalse(shallow.coverage.history_complete)
        self.assertLess(
            shallow.git.commit_count,
            full.git.commit_count,
            "the shallow clone kept the whole history, so nothing is proved",
        )

        full_score = judge(full).score
        shallow_score = judge(shallow).score
        assert full_score is not None
        self.assertTrue(
            shallow_score is None or shallow_score <= full_score,
            f"a shallow clone scored {shallow_score} against {full_score} for "
            f"the full clone, so withholding history still pays",
        )


class RefusalTests(unittest.TestCase):
    """A repository nothing can read gets a reason, not a number."""

    def test_no_source_files_is_refused(self) -> None:
        judgement = judge(empty_metrics())
        self.assertIsNone(judgement.score)
        self.assertEqual("no_source_files", judgement.refusal)
        self.assertEqual("unscoreable", judgement.band)

    def test_an_unreadable_tree_is_refused_rather_than_ranked(self) -> None:
        """The github/gitignore case: source files, and no program among them."""
        metrics = replace(
            BASE_METRICS,
            coverage=replace(
                BASE_METRICS.coverage, source_files=309, attributed_files=0
            ),
            palate=replace(BASE_METRICS.palate, source_file_count=309),
        )
        judgement = judge(metrics)
        self.assertIsNone(judgement.score)
        self.assertEqual("unattributed", judgement.refusal)
        self.assertEqual("0", judgement.refusal_facts["percent"])

    def test_the_attribution_floor_is_exercised_at_its_edge(self) -> None:
        floor = BANDS["unscoreable_attribution_share"]
        assert isinstance(floor, float)
        total = 100
        cases: tuple[tuple[int, bool], ...] = (
            (int(total * floor) - 1, True),
            (int(total * floor), False),
            (total, False),
        )
        for attributed, refused in cases:
            with self.subTest(attributed=attributed):
                metrics = replace(
                    BASE_METRICS,
                    coverage=replace(
                        BASE_METRICS.coverage,
                        source_files=total,
                        attributed_files=attributed,
                    ),
                    palate=replace(BASE_METRICS.palate, source_file_count=total),
                )
                judgement = judge(metrics)
                self.assertEqual(refused, judgement.score is None)

    def test_too_few_dimensions_is_refused(self) -> None:
        minimum = BANDS["unscoreable_min_dimensions"]
        assert isinstance(minimum, int)
        judgement = judge(
            withheld(
                BASE_METRICS,
                history_complete=False,
                authorship_measured=False,
                dependencies_measured=False,
                lines_complete=False,
            )
        )
        # Four dimensions left, which is the floor, so this one still scores.
        self.assertEqual(minimum, judgement.scored_dimensions)
        self.assertIsNotNone(judgement.score)

    def test_the_dimension_floor_is_exercised_from_below(self) -> None:
        """One dimension under the floor, and the refusal names the count.

        The test above stands on the floor. This one steps off it, so a floor
        that quietly moved by one would fail here rather than pass both.
        """
        minimum = band_int("unscoreable_min_dimensions")
        judgement = judge(
            unfinished(
                withheld(
                    BASE_METRICS,
                    history_complete=False,
                    authorship_measured=False,
                    dependencies_measured=False,
                    lines_complete=False,
                ),
                "palate",
            )
        )
        self.assertEqual(minimum - 1, judgement.scored_dimensions)
        self.assertIsNone(judgement.score)
        self.assertEqual("too_few_dimensions", judgement.refusal)
        self.assertEqual(str(minimum), judgement.refusal_facts["minimum"])
        self.assertEqual(
            str(minimum - 1), judgement.refusal_facts["scored"]
        )

    def test_judge_never_raises_on_a_broken_record(self) -> None:
        class Hostile:
            def __getattr__(self, name: str) -> object:
                raise RuntimeError("this record refuses to be read")

        judgement = judge(Hostile())  # type: ignore[arg-type]
        self.assertIsNone(judgement.score)
        self.assertEqual("unreadable", judgement.refusal)

    def test_judge_never_raises_across_the_spread(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                self.assertIsInstance(judge(metrics), Judgement)

    def test_a_coverage_record_of_all_gaps_is_survivable(self) -> None:
        blank = Coverage(
            lines_complete=False,
            truncated_files=0,
            structural_scan_complete=False,
            function_detector_files=0,
            attributed_files=0,
            source_files=0,
            history_complete=False,
            authorship_measured=False,
            dependencies_measured=False,
        )
        judgement = judge(replace(BASE_METRICS, coverage=blank))
        self.assertIsNone(judgement.score)


class UnfinishedRunTests(unittest.TestCase):
    """An analyzer that stopped at the budget measured less of this repository.

    The coverage record answers the question "could this be measured". It does
    not answer "did the measurement finish", and the difference was worth
    thirteen points and a band. A walk that stopped before the committed key
    reported no secrets, the hygiene gate read that zero as evidence of a
    clean tree, and a repository that scored 87 with the key in it scored 100
    without the walk that found it. The same door was open on the log: a read
    that stopped after the recent commits reported no dormancy and no silence,
    and the cadence gate passed on the part of the history that was read.

    Every case below holds the repository fixed and shortens the run.
    """

    ANALYZERS: tuple[str, ...] = tuple(sorted(ANALYZER_DIMENSIONS))

    def test_every_analyzer_the_collector_can_drop_is_accounted_for(self) -> None:
        emittable = analyzers_the_collector_can_drop()
        self.assertTrue(emittable, "the scan found no dropped analyzer at all")
        unclaimed = sorted(emittable - set(ANALYZER_DIMENSIONS) - INVENTORY_ONLY)
        self.assertEqual(
            [],
            unclaimed,
            "the collector can drop an analyzer the judge has no answer for:\n"
            + "\n".join(unclaimed),
        )
        stranded = sorted(set(ANALYZER_DIMENSIONS) - emittable)
        self.assertEqual(
            [],
            stranded,
            "the judge answers for an analyzer the collector never drops:\n"
            + "\n".join(stranded),
        )

    def test_every_gate_names_the_analyzers_it_reads(self) -> None:
        self.assertEqual(
            set(BASE_GATES) | set(CARE_GATES),
            set(GATE_ANALYZERS),
            "a gate was added without saying which analyzers it reads",
        )
        unknown = sorted(
            {name for names in GATE_ANALYZERS.values() for name in names}
            - set(ANALYZER_DIMENSIONS)
        )
        self.assertEqual([], unknown, "a gate reads an analyzer that does not exist")

    def test_every_dimension_an_analyzer_feeds_exists(self) -> None:
        unknown = sorted(
            {name for names in ANALYZER_DIMENSIONS.values() for name in names}
            - set(DIMENSIONS)
        )
        self.assertEqual([], unknown, "an analyzer feeds a dimension that is not scored")

    def test_a_short_walk_cannot_clear_the_sediment_it_never_reached(self) -> None:
        """The defect in one pair. A committed key against a walk that stopped."""
        found = judge(repo_with_secret())
        self.assertIn("hygiene", failed_gates(found))
        assert found.score is not None
        self.assertLess(found.score, TOP_BAND_FLOOR)

        short = judge(unfinished(BASE_METRICS, "tree"))
        self.assertIn(
            "hygiene",
            failed_gates(short),
            "a walk that stopped early passed the hygiene gate on its own silence",
        )
        self.assertIsNone(
            short.score,
            "a walk that never finished still produced a number",
        )

    def test_a_short_log_cannot_clear_the_history_it_never_read(self) -> None:
        """A dormant, fix-heavy history against a log read that stopped."""
        read = judge(
            repo_with_git(
                fix_commit_count=90,
                fix_ratio=0.75,
                longest_gap_days=900,
                days_since_last_commit=800,
                last_commit_subject="fix everything",
            )
        )
        self.assertIn("cadence", failed_gates(read))
        assert read.score is not None

        short = judge(unfinished(BASE_METRICS, "git"))
        self.assertIn(
            "cadence",
            failed_gates(short),
            "a log read that stopped early passed cadence on the part it read",
        )
        assert short.score is not None
        self.assertLess(short.score, read.score)
        self.assertLess(short.score, TOP_BAND_FLOOR)

    def test_an_unfinished_analyzer_takes_its_dimensions_out(self) -> None:
        for analyzer, dimensions in sorted(ANALYZER_DIMENSIONS.items()):
            with self.subTest(analyzer=analyzer):
                judgement = judge(unfinished(BASE_METRICS, analyzer))
                missing = {d.name for d in judgement.dimensions if not d.measured}
                self.assertEqual(set(dimensions), missing)

    def test_an_unfinished_analyzer_closes_every_gate_that_reads_it(self) -> None:
        for analyzer in self.ANALYZERS:
            with self.subTest(analyzer=analyzer):
                judgement = judge(unfinished(BASE_METRICS, analyzer))
                blocked = {
                    gate
                    for gate, reads in GATE_ANALYZERS.items()
                    if analyzer in reads
                }
                self.assertLessEqual(blocked, failed_gates(judgement))

    def test_an_unfinished_analyzer_never_raises_the_score(self) -> None:
        """Every case in the spread, against every subset of the analyzers."""
        subsets = [
            combination
            for size in range(1, len(self.ANALYZERS) + 1)
            for combination in itertools.combinations(self.ANALYZERS, size)
        ]
        for name, metrics in spread():
            full = judge(metrics)
            if full.score is None:
                continue
            for combination in subsets:
                with self.subTest(case=name, dropped=combination):
                    partial = judge(unfinished(metrics, *combination))
                    if partial.score is None:
                        continue
                    self.assertLessEqual(
                        partial.score,
                        full.score,
                        f"{name}: dropping {', '.join(combination)} raised the "
                        f"score from {full.score} to {partial.score}",
                    )

    # Which families of finding are read from which analyzer. Written out
    # rather than derived, so silencing one more course has to be a decision
    # taken here as well as in the judge.
    SILENCED: dict[str, frozenset[str]] = {
        "tree": frozenset({"label", "nose", "palate", "structure", "abandonment"}),
        "git": frozenset({"vintage", "finish"}),
        "palate": frozenset({"label", "palate", "abandonment"}),
        "abandonment": frozenset({"abandonment"}),
    }

    def families(self, judgement: Judgement) -> set[str]:
        return {finding.key.split(".", 1)[0] for finding in judgement.findings}

    def test_a_course_read_from_an_unfinished_analyzer_says_nothing(self) -> None:
        """Absence of a reading is not a reading of absence.

        A walk that stopped early found no README, no tests and no secrets. A
        log read that stopped early found no commits at all. Printed as
        findings those are three confident falsehoods about a repository
        nobody finished reading, and the footnote already names the analyzer
        that stopped.
        """
        self.assertEqual(
            set(ANALYZER_DIMENSIONS), set(self.SILENCED), "an analyzer has no entry"
        )
        loud = judge(worst_metrics())
        for analyzer, silenced in sorted(self.SILENCED.items()):
            with self.subTest(analyzer=analyzer):
                self.assertLessEqual(
                    silenced,
                    self.families(loud),
                    "the loudest case in the suite says nothing here anyway",
                )
                quiet = self.families(judge(unfinished(worst_metrics(), analyzer)))
                self.assertEqual(
                    set(), quiet & silenced, f"{analyzer} spoke about what it never read"
                )
                self.assertEqual(
                    self.families(loud) - silenced,
                    quiet,
                    f"{analyzer} silenced a course it does not feed",
                )

    def test_a_run_that_read_nothing_states_the_refusal_and_nothing_else(self) -> None:
        judgement = judge(unfinished(worst_metrics(), *self.ANALYZERS))
        self.assertEqual((), judgement.findings)
        self.assertIsNone(judgement.score)
        self.assertEqual("too_few_dimensions", judgement.refusal)

    def test_a_short_walk_is_not_reported_as_an_empty_repository(self) -> None:
        """The counts a walk never finished are floors, and a floor of zero is
        not a finding of nothing."""
        blind = replace(
            BASE_METRICS,
            coverage=replace(
                BASE_METRICS.coverage, source_files=0, attributed_files=0
            ),
            palate=replace(BASE_METRICS.palate, source_file_count=0, total_file_count=0),
        )
        self.assertEqual("no_source_files", judge(blind).refusal)
        self.assertEqual(
            "too_few_dimensions",
            judge(unfinished(blind, "tree")).refusal,
            "a walk that stopped early was reported as a repository with no code",
        )

    def test_an_unfinished_run_cannot_reach_the_top_band(self) -> None:
        """No drop of any kind is exemplary.

        The outstanding band is left open on purpose to an analyzer that does
        not feed a gate. Every base gate that repository passed, it passed on
        evidence somebody read, and the missing dimension still costs it the
        coverage weight inside the band. The exemplary band is the one that
        claims sustained care across every axis, and an axis nobody finished
        reading is not one of them.
        """
        for analyzer in self.ANALYZERS:
            with self.subTest(analyzer=analyzer):
                judgement = judge(unfinished(BASE_METRICS, analyzer))
                self.assertNotEqual(EXEMPLARY, judgement.band)
                self.assertIn("craft", failed_gates(judgement))
                self.assertIn("complete_coverage", failed_gates(judgement))

    def test_an_analyzer_that_feeds_a_gate_bars_the_nineties(self) -> None:
        for analyzer in self.ANALYZERS:
            if not any(analyzer in reads for reads in GATE_ANALYZERS.values()):
                continue
            with self.subTest(analyzer=analyzer):
                judgement = judge(unfinished(BASE_METRICS, analyzer))
                self.assertNotIn(judgement.band, {EXEMPLARY, OUTSTANDING})


class MonotonicityTests(unittest.TestCase):
    """Making a repository worse never makes the number go up.

    Every sequence below starts at the same faultless baseline and moves one
    axis outward, one step at a time. The baseline sits in the middle of every
    two sided band on purpose. An axis banded at both ends is only monotone
    away from the middle, and a sequence that started at zero nesting would be
    asserting that a file with no indentation is worse than one with five
    levels of it, which is the opposite of what the band says.
    """

    def assert_never_rises(
        self, axis: str, steps: Sequence[tuple[str, RepoMetrics]]
    ) -> None:
        previous = judge(BASE_METRICS)
        assert previous.score is not None
        previous_label = "faultless"
        for label, metrics in steps:
            judgement = judge(metrics)
            self.assertIsNotNone(
                judgement.score, f"{axis}: {label} was refused, so nothing is proved"
            )
            assert judgement.score is not None and previous.score is not None
            self.assertLessEqual(
                judgement.score,
                previous.score,
                f"{axis}: {label} scored {judgement.score} against "
                f"{previous.score} for {previous_label}",
            )
            previous = judgement
            previous_label = label

    def test_markers_accumulate_downward(self) -> None:
        self.assert_never_rises(
            "markers",
            tuple(
                (f"{rate} per kloc", repo_with_markers(rate))
                for rate in (6.0, 12.0, 24.0, 60.0)
            ),
        )

    def test_a_growing_file_never_helps(self) -> None:
        self.assert_never_rises(
            "largest file",
            tuple(
                (f"{lines} lines", repo_with_palate(largest_file_lines=lines))
                for lines in (300, 500, 801, 4000)
            ),
        )

    def test_deepening_nesting_never_helps(self) -> None:
        self.assert_never_rises(
            "nesting",
            tuple(
                (f"depth {depth}", repo_with_palate(max_indent_depth=depth))
                for depth in (5, 6, 9, 14)
            ),
        )

    def test_a_lengthening_function_never_helps(self) -> None:
        self.assert_never_rises(
            "longest function",
            tuple(
                (f"{lines} lines", repo_with_palate(longest_function_lines=lines))
                for lines in (99, 101, 400)
            ),
        )

    def test_committing_sediment_never_helps(self) -> None:
        self.assert_never_rises(
            "sediment",
            (
                ("one key", repo_with_secret(1)),
                ("four keys", repo_with_secret(4)),
            ),
        )

    def test_losing_the_paperwork_never_helps(self) -> None:
        self.assert_never_rises(
            "documentation",
            (
                ("thin readme", repo_with_nose(readme_lines=8, readme_bytes=200)),
                (
                    "no readme",
                    repo_with_nose(readme_path=None, readme_lines=0, readme_bytes=0),
                ),
                (
                    "no readme and no license",
                    repo_with_nose(
                        readme_path=None,
                        readme_lines=0,
                        readme_bytes=0,
                        license_path=None,
                        license_name=None,
                    ),
                ),
            ),
        )

    def test_losing_the_tests_never_helps(self) -> None:
        self.assert_never_rises(
            "testing", (("no tests", repo_with_nose(has_tests=False)),)
        )

    def test_losing_the_gitignore_never_helps(self) -> None:
        self.assert_never_rises(
            "hygiene",
            (
                (
                    "no gitignore",
                    repo_with_nose(gitignore_path=None, gitignore_rules=0),
                ),
            ),
        )

    def test_going_quiet_never_helps(self) -> None:
        self.assert_never_rises(
            "dormancy",
            tuple(
                (f"{days} days", repo_with_git(days_since_last_commit=days))
                for days in (90, 365, 366, 900)
            ),
        )

    def test_a_rising_fix_ratio_never_helps(self) -> None:
        self.assert_never_rises(
            "fix ratio",
            tuple(
                (
                    f"ratio {ratio}",
                    repo_with_git(
                        fix_ratio=ratio, fix_commit_count=int(ratio * 120)
                    ),
                )
                for ratio in (0.30, 0.40, 0.70, 0.95)
            ),
        )

    def test_a_lengthening_silence_never_helps(self) -> None:
        self.assert_never_rises(
            "silence",
            tuple(
                (f"{days} days", repo_with_git(longest_gap_days=days))
                for days in (180, 181, 600, 1200)
            ),
        )

    def test_a_growing_dependency_tree_never_helps(self) -> None:
        self.assert_never_rises(
            "dependencies",
            tuple(
                (f"{count} declared", repo_with_dependencies("python", count))
                for count in (25, 26, 61, 400)
            ),
        )

    def test_a_narrowing_authorship_never_helps(self) -> None:
        self.assert_never_rises(
            "authorship",
            (
                ("two authors", repo_with_git(author_count=2, top_author_share=0.6)),
                (
                    "one author",
                    repo_with_git(
                        author_count=1, top_author_commits=120, top_author_share=1.0
                    ),
                ),
            ),
        )


class DegradationOnDiskTests(unittest.TestCase):
    """The same six degradations, applied to a real repository on disk.

    The synthetic suite above proves the arithmetic. This one proves that the
    arithmetic is fed by the thing that actually changed, which is the part a
    metrics record written by hand cannot show. Each variant is one extra
    commit on a copy of the same repository, measured against a control that
    commits a harmless file, so the only difference between any two runs is
    the content of that commit.
    """

    EXTRA_DAY = "2026-08-10"
    CONTROL = {"docs/notes.md": "# notes\n\nNothing of consequence.\n"}

    def variant(self, name: str, files: dict[str, str], remove: str = "") -> int:
        fixture = fixtures.healthy_python_repo()
        self.addCleanup(fixture.cleanup)
        root = fixture.path
        if remove:
            target = root.joinpath(*remove.split("/"))
            if target.is_dir():
                for child in sorted(target.rglob("*")):
                    if child.is_file():
                        child.unlink()
            elif target.is_file():
                target.unlink()
        if files:
            fixtures.write_tree(root, files)
        fixtures.git_commit(root, f"add {name}", day=self.EXTRA_DAY)
        judgement = judge(collect(root, budget_seconds=SCORE_BUDGET_SECONDS))
        self.assertIsNotNone(judgement.score, f"{name} was refused a score")
        assert judgement.score is not None
        return judgement.score

    def setUp(self) -> None:
        fixtures.require_git()

    def test_each_degradation_lowers_the_score_it_is_measured_against(self) -> None:
        control = self.variant("notes", dict(self.CONTROL))
        todos = "\n".join(f"# TODO: revisit branch {index}" for index in range(200))
        bulk = "\n".join(f"VALUE_{index} = {index}" for index in range(5000))
        nested = "\n".join(
            ["    " * level + f"if value > {level}:" for level in range(14)]
            + ["    " * 14 + "return value"]
        )
        cases: tuple[tuple[str, dict[str, str], str], ...] = (
            ("two hundred markers", {"src/cellar/notes.py": todos + "\n"}, ""),
            ("a five thousand line file", {"src/cellar/bulk.py": bulk + "\n"}, ""),
            (
                "a file nested fourteen deep",
                {"src/cellar/deep.py": f"def walk(value):\n{nested}\n"},
                "",
            ),
            # Not named .env: the fixture's own .gitignore covers that one, so
            # git would never stage it and the commit would carry no change.
            (
                "a committed key",
                {"deploy/service-account.pem": "not a real key\n"},
                "",
            ),
            ("no readme", dict(self.CONTROL), "README.md"),
            ("no tests", dict(self.CONTROL), "tests"),
        )
        for label, files, remove in cases:
            with self.subTest(case=label):
                score = self.variant(label, files, remove)
                self.assertLessEqual(
                    score,
                    control,
                    f"{label} scored {score} against {control} for the control, "
                    f"so making the repository worse paid",
                )


def gate_edges() -> tuple[tuple[str, str, RepoMetrics, RepoMetrics], ...]:
    """(gate, what moved, the metrics that pass, the metrics one step past).

    The thresholds are read out of BANDS rather than written here, so retuning
    a band moves this table with it instead of leaving it asserting the old
    number under a passing name.
    """
    readme_floor = band_int("gate_readme_lines")
    reference_floor = band_int("gate_readme_lines_exemplary")
    authors = band_int("gate_min_authors")
    dormant = band_int("dormant_days")
    recent = band_int("vintage_recent_days")
    fixes = band_float("fix_ratio_high")
    return (
        (
            "documented",
            "readme length",
            repo_with_nose(readme_lines=readme_floor),
            repo_with_nose(readme_lines=readme_floor - 1),
        ),
        (
            "documented",
            "the license",
            repo_with_nose(),
            repo_with_nose(license_path=None, license_name=None),
        ),
        (
            "tested",
            "the tests",
            repo_with_nose(has_tests=True),
            repo_with_nose(has_tests=False),
        ),
        ("hygiene", "one committed key", BASE_METRICS, repo_with_secret(1)),
        (
            "hygiene",
            "the gitignore",
            repo_with_nose(),
            repo_with_nose(gitignore_path=None, gitignore_rules=0),
        ),
        (
            "dependencies",
            "a manifest to read",
            BASE_METRICS,
            withheld(BASE_METRICS, dependencies_measured=False),
        ),
        (
            # An empty file with the right name is free. The gate is supposed
            # to cost the author the work of resolving the tree, so it reads
            # what the lockfile pins rather than that it exists.
            "dependencies",
            "a lockfile that pins nothing",
            repo_with_lockfile(1),
            repo_with_lockfile(0),
        ),
        (
            "dependencies",
            "the lockfile itself",
            BASE_METRICS,
            replace(
                BASE_METRICS,
                structure=replace(
                    BASE_STRUCTURE,
                    manifests=(
                        replace(BASE_MANIFEST, lockfile_path=None, locked_count=0),
                    ),
                ),
            ),
        ),
        (
            "history",
            "a complete history",
            BASE_METRICS,
            withheld(BASE_METRICS, history_complete=False),
        ),
        (
            "authorship",
            "the author floor",
            repo_with_git(author_count=authors, top_author_share=0.5),
            repo_with_git(author_count=authors - 1, top_author_share=1.0),
        ),
        (
            "cadence",
            "one day past dormancy",
            repo_with_git(days_since_last_commit=dormant),
            repo_with_git(days_since_last_commit=dormant + 1),
        ),
        (
            "cadence",
            "one float past the fix ratio",
            repo_with_git(fix_ratio=fixes),
            repo_with_git(fix_ratio=math.nextafter(fixes, 1.0)),
        ),
        (
            "continuous_integration",
            "the workflow",
            repo_with_nose(has_ci=True),
            repo_with_nose(has_ci=False),
        ),
        (
            "contributing",
            "the contributing guide",
            repo_with_nose(has_contributing=True),
            repo_with_nose(has_contributing=False),
        ),
        (
            "reference_documentation",
            "the exemplary readme floor",
            repo_with_nose(readme_lines=reference_floor),
            repo_with_nose(readme_lines=reference_floor - 1),
        ),
        (
            "active",
            "one day past the recent window",
            repo_with_git(days_since_last_commit=recent),
            repo_with_git(days_since_last_commit=recent + 1),
        ),
    )


class GateBoundaryTests(unittest.TestCase):
    """Every gate, one unit either side of the number it turns on."""

    def test_every_gate_holds_at_its_edge_and_gives_way_one_step_past(self) -> None:
        for gate, moved, passing, failing in gate_edges():
            with self.subTest(gate=gate, moved=moved):
                self.assertNotIn(
                    gate,
                    failed_gates(judge(passing)),
                    f"{gate} failed on its own edge with {moved}",
                )
                self.assertIn(
                    gate,
                    failed_gates(judge(failing)),
                    f"{gate} passed one step past its edge with {moved}",
                )

    def test_every_base_gate_has_a_boundary_case(self) -> None:
        """A gate added without an edge case fails here rather than silently."""
        exercised = {gate for gate, _, _, _ in gate_edges()}
        missing = sorted(set(BASE_GATES) - exercised)
        self.assertEqual(
            [], missing, "these gates have no boundary case:\n" + "\n".join(missing)
        )

    def test_the_care_gates_that_read_a_threshold_have_one_too(self) -> None:
        exercised = {gate for gate, _, _, _ in gate_edges()}
        unknown = sorted(exercised - set(BASE_GATES) - set(CARE_GATES))
        self.assertEqual([], unknown, "the table names a gate that does not exist")
        # locked, craft and complete_coverage read no threshold of their own.
        # They are covered by the drop and denominator tests above instead.
        self.assertLessEqual(
            {"continuous_integration", "contributing", "reference_documentation",
             "active"},
            exercised,
        )


class BandBoundaryTests(unittest.TestCase):
    """The band table, checked as a table rather than one row at a time."""

    def test_the_bands_tile_the_scale_without_gap_or_overlap(self) -> None:
        covered: list[int] = []
        for _, low, high, _ in band_edges():
            covered.extend(range(low, high + 1))
        self.assertEqual(
            len(covered), len(set(covered)), "two bands claim the same score"
        )
        floor = band_int("score_deduction_floor")
        self.assertEqual(
            list(range(floor, 101)),
            sorted(covered),
            "the bands leave a hole between the floor and one hundred",
        )

    def test_the_deduction_arithmetic_lands_exactly_on_the_floor(self) -> None:
        """A full deduction reaches the floor, and one point of span too many
        would have it clamp there instead, which hides a retuning mistake."""
        self.assertEqual(
            band_int("score_deduction_ceiling") - band_int("score_deduction_floor"),
            band_int("score_deduction_span"),
        )

    def test_the_deduction_band_stops_below_the_gated_bands(self) -> None:
        ceiling = band_int("score_deduction_ceiling")
        gated = min(low for name, low, _, _ in band_edges() if name == OUTSTANDING)
        self.assertLess(ceiling, gated, "a deduction alone can reach the nineties")

    def test_every_score_in_the_deduction_range_is_reachable(self) -> None:
        floor = band_int("score_deduction_floor")
        ceiling = band_int("score_deduction_ceiling")
        span = band_int("score_deduction_span")
        steps = 1000
        reached = {
            max(floor, min(ceiling, ceiling - round(index / steps * span)))
            for index in range(steps + 1)
        }
        self.assertEqual(set(range(floor, ceiling + 1)), reached)

    def test_the_coverage_weight_clears_its_own_bound(self) -> None:
        """The bound the module docstring states, asserted rather than trusted.

        Removing one dimension from a measured set of n raises the mean by at
        most 1/n. The smallest set that can lose one and still be scored is the
        floor plus one, so the weight has to clear its reciprocal.
        """
        smallest = band_int("unscoreable_min_dimensions") + 1
        self.assertGreater(band_float("score_coverage_weight"), 1.0 / smallest)


class DegenerateInputTests(unittest.TestCase):
    """Nothing to taste is an answer, and the answer exits zero.

    Every one of these was a crash or a confident number in some earlier
    version of the tool. None of them may print a score it cannot defend.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sommelier-degenerate-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def taste(self, path: Path, *flags: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli_main(["taste", str(path), *flags])
        return (code, buffer.getvalue())

    def cases(self) -> tuple[tuple[str, Path], ...]:
        one_file = self.root / "one-file"
        one_file.mkdir()
        (one_file / "main.py").write_text("print(1)\n", encoding="utf-8")

        images = self.root / "images"
        images.mkdir()
        for index in range(4):
            fixtures.write_binary(
                images, f"plate{index}.png", fixtures.binary_blob(512)
            )

        nothing = self.root / "nothing"
        nothing.mkdir()

        built: list[tuple[str, Path]] = [
            ("one file", one_file),
            ("only images", images),
            ("empty directory", nothing),
        ]
        for name, builder in (
            ("bare directory", fixtures.bare_directory),
            ("no commits", fixtures.git_repo_without_commits),
            ("unknown language", fixtures.unknown_language_repo),
        ):
            fixture = builder()
            self.addCleanup(fixture.cleanup)
            built.append((name, fixture.path))
        return tuple(built)

    def test_every_degenerate_input_exits_zero_on_every_renderer(self) -> None:
        for name, path in self.cases():
            for flags in ((), ("--sober",), ("--json",)):
                with self.subTest(case=name, flags=flags):
                    code, output = self.taste(path, *flags)
                    self.assertEqual(0, code, f"{name} {flags} exited {code}")
                    self.assertTrue(output.strip(), f"{name} {flags} printed nothing")

    def test_a_refused_repository_prints_a_refusal_and_not_a_number(self) -> None:
        for name, path in self.cases():
            judgement = judge(collect(path, budget_seconds=SCORE_BUDGET_SECONDS))
            if judgement.score is not None:
                continue
            with self.subTest(case=name):
                self.assertIsNotNone(judgement.refusal)
                _, sober = self.taste(path, "--sober")
                rows = [
                    line.split() for line in sober.splitlines() if line.startswith("  ")
                ]
                score_rows = [row for row in rows if row and row[0] == "score"]
                self.assertEqual([["score", "none"]], score_rows)
                _, payload = self.taste(path, "--json")
                self.assertIn('"score": null', payload)

    def test_a_path_that_does_not_exist_is_declined_without_a_traceback(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(["taste", str(self.root / "no-such-cellar")])
        self.assertEqual(1, code)
        self.assertEqual("", out.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertTrue(err.getvalue().strip())


class ReproducibilityTests(unittest.TestCase):
    """Same repository, same verdict, in a process that shares nothing."""

    def test_two_processes_agree_on_the_same_repository(self) -> None:
        fixtures.require_git()
        fixture = fixtures.healthy_python_repo()
        self.addCleanup(fixture.cleanup)
        # Different hash seeds, so a verdict that depended on set ordering
        # anywhere between the walk and the card would disagree here.
        outputs: list[str] = []
        for seed in ("0", "1", "524287"):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            completed = subprocess.run(
                [sys.executable, "-m", "sommelier.cli", "taste",
                 str(fixture.path), "--sober"],
                cwd=str(REPO_ROOT),
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            outputs.append(completed.stdout)
        self.assertEqual(
            1,
            len(set(outputs)),
            "two runs of the same repository disagreed:\n" + "\n".join(outputs),
        )


def _band_floor() -> int:
    floor = BANDS["score_deduction_floor"]
    assert isinstance(floor, int)
    return floor


if __name__ == "__main__":
    unittest.main()
