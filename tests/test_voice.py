"""Tests for the voice layer.

Two kinds of test live here, deliberately separated.

The snapshot tests run against a small frozen cellar patched in for the
duration of the test. That keeps the snapshot stable when somebody adds a new
tasting line, which is a thing the project actively wants people to do. A
snapshot taken over the real cellar would fail on every contribution and would
teach contributors to regenerate it without reading it.

The determinism and formatting tests run against the real cellar, because
those are the properties that must hold for the shipped material.

Voice no longer sees metrics or a judgement. It is handed a plan, so the
helpers below build one the same way the pipeline does.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from sommelier import judge as judge_module
from sommelier import lines as lines_module
from sommelier import plan as plan_module
from sommelier.collect import RepoMetrics
from sommelier.judge import Fact, Finding, Judgement
from sommelier.plan import Plan, compose
from sommelier.render import render_card
from sommelier.voice import COURSE_TITLES, pour, stable_seed

from tests import fixtures
from tests.fixtures import synthetic_metrics

REPO_ROOT = Path(__file__).resolve().parents[1]

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

# The frozen cellar cites real fact names, because plan.py decides which forms
# survive by reading what each template asks for. A template naming a fact its
# key does not carry is not a shorter sentence, it is an unsayable one.
FROZEN_CELLAR = {
    "label.identity": (
        "{name}. {language}. {source_file_count} source files.",
        "{name} holds {source_file_count} files of {language}.",
        "{source_file_count} files. {language}. This is {name}.",
    ),
    "palate.cry_for_help": (
        "{path} runs to {lines} lines, which is not a module.",
        "One file, {path}, contains {lines} lines.",
        "{lines} lines in {path}. Nobody decided this.",
    ),
}

FROZEN_VERDICTS = ("{score} points. {band}, on {scored} of {total} dimensions.",)
FROZEN_PAIRINGS = ("Pairs well with a strong drink and a rewrite.",)

FROZEN_REFUSALS = {
    "no_source_files": ("No score. {name} holds {total_files} files, none of it code.",),
}


def _fact(name: str, value: str) -> Fact:
    """One fact per name, each its own measurement, so nothing deduplicates."""
    return Fact(measurement=f"test.{name}", value=value, unit=judge_module.TEXT)


def _finding(key: str, course: str, severity: int, **facts: str) -> Finding:
    return Finding(
        key=key,
        course=course,
        severity=severity,
        facts={name: _fact(name, value) for name, value in facts.items()},
    )


def _plan(metrics: RepoMetrics, judgement: Judgement) -> Plan:
    return compose(metrics, judgement)


def _judgement_like(judgement: Judgement, findings: tuple[Finding, ...]) -> Judgement:
    """The same judgement, carrying fewer findings."""
    return replace(judgement, findings=findings)


def _judgement(
    *findings: Finding,
    score: int | None = 91,
    band: str = "outstanding",
    band_label: str = "Outstanding",
    scored: int = 8,
    total: int = 8,
    refusal: str | None = None,
    refusal_facts: dict[str, str] | None = None,
) -> Judgement:
    return Judgement(
        findings=tuple(findings),
        score=score,
        total_severity=sum(f.severity for f in findings),
        band=band,
        band_label=band_label,
        dimensions=(),
        scored_dimensions=scored,
        total_dimensions=total,
        gates=(),
        care_gates=(),
        refusal=refusal,
        refusal_facts=refusal_facts or {},
    )


class StableSeedTests(unittest.TestCase):
    def test_seed_is_stable_across_calls(self) -> None:
        self.assertEqual(stable_seed("todo-app"), stable_seed("todo-app"))

    def test_different_names_seed_differently(self) -> None:
        self.assertNotEqual(stable_seed("todo-app"), stable_seed("other-app"))

    def test_seed_does_not_use_salted_hash(self) -> None:
        # A literal value, so a switch to hash() fails here rather than
        # failing mysteriously between processes.
        self.assertEqual(stable_seed("todo-app"), 3702919137)


class SnapshotTests(unittest.TestCase):
    """Snapshots against the frozen cellar, so contributions do not break them."""

    def _pour_frozen(self, seed: int) -> str:
        metrics = synthetic_metrics(
            name="todo-app",
            primary_language="JavaScript",
            source_file_count=13,
            largest_file_path="src/app.js",
            largest_file_lines=2400,
        )
        judgement = _judgement(
            _finding(
                "label.identity",
                "label",
                0,
                name="todo-app",
                language="JavaScript",
                source_file_count="13",
                file_count="14,203",
            ),
            _finding(
                "palate.cry_for_help",
                "palate",
                3,
                path="src/app.js",
                lines="2,400",
            ),
        )
        with (
            mock.patch.object(lines_module, "CELLAR", FROZEN_CELLAR),
            mock.patch.object(lines_module, "VERDICTS", FROZEN_VERDICTS),
            mock.patch.object(lines_module, "PAIRINGS", FROZEN_PAIRINGS),
            mock.patch("sommelier.plan.CELLAR", FROZEN_CELLAR),
            mock.patch("sommelier.voice.CELLAR", FROZEN_CELLAR),
            mock.patch("sommelier.voice.VERDICTS", FROZEN_VERDICTS),
            mock.patch("sommelier.voice.PAIRINGS", FROZEN_PAIRINGS),
        ):
            return render_card(pour(_plan(metrics, judgement), seed=seed))

    def test_snapshot_seed_seven(self) -> None:
        expected = "\n".join(
            [
                "CODE SOMMELIER                                   tasting no. 48",
                "",
                "The label    todo-app. JavaScript. 13 source files.",
                "Palate       One file, src/app.js, contains 2,400 lines.",
                "Verdict      91 points. Outstanding, on 8 of 8 dimensions.",
                "Pairing      Pairs well with a strong drink and a rewrite.",
            ]
        )
        self.assertEqual(self._pour_frozen(seed=7), expected)

    def test_snapshot_is_repeatable(self) -> None:
        self.assertEqual(self._pour_frozen(seed=7), self._pour_frozen(seed=7))

    def test_different_seed_gives_a_different_card(self) -> None:
        cards = {self._pour_frozen(seed=n) for n in range(12)}
        self.assertGreater(len(cards), 1)


class DeterminismTests(unittest.TestCase):
    """Properties that must hold for the real, shipped cellar."""

    def setUp(self) -> None:
        self.metrics = synthetic_metrics(name="todo-app")
        self.judgement = _judgement(
            _finding(
                "label.identity",
                "label",
                0,
                name="todo-app",
                language="Python",
                source_file_count="13",
                file_count="13",
                total_lines="900",
            )
        )
        self.plan = _plan(self.metrics, self.judgement)

    def test_same_repo_receives_the_same_tasting(self) -> None:
        first = pour(self.plan)
        second = pour(self.plan)
        self.assertEqual(render_card(first), render_card(second))

    def test_tasting_number_is_in_range(self) -> None:
        for seed in range(50):
            card = pour(self.plan, seed=seed)
            self.assertGreaterEqual(card.tasting_number, 1)
            self.assertLessEqual(card.tasting_number, 99)

    def test_explicit_seed_overrides_the_repo_name(self) -> None:
        unseeded = pour(self.plan)
        seeded = {pour(self.plan, seed=n).tasting_number for n in range(30)}
        self.assertIn(unseeded.tasting_number, range(1, 100))
        self.assertGreater(len(seeded), 1)

    def test_one_course_changing_leaves_the_others_alone(self) -> None:
        """Each draw site is keyed on its own name, not on a running stream.

        A single RNG stream makes every choice depend on how many came before
        it, so losing one Finish finding rewrites the Palate. The plan layer
        makes a course answer for itself, and this pins the other half: a
        course that lost nothing prints exactly what it printed before.
        """
        from sommelier.judge import judge

        from tests.test_judge import spread

        for name, metrics in spread():
            judgement = judge(metrics)
            finish = [f for f in judgement.findings if f.course == "finish"]
            if len(finish) < 2:
                continue
            thinner = _judgement_like(
                judgement,
                tuple(f for f in judgement.findings if f is not finish[-1]),
            )
            with self.subTest(case=name):
                before = {
                    course.name: course.body
                    for course in pour(compose(metrics, judgement)).courses
                }
                after = {
                    course.name: course.body
                    for course in pour(compose(metrics, thinner)).courses
                }
                for course in before:
                    if course == "Finish":
                        continue
                    self.assertEqual(
                        before[course],
                        after.get(course),
                        f"{name}: dropping a Finish finding moved {course}",
                    )

    def test_dropping_a_spoken_finding_leaves_every_other_course_alone(self) -> None:
        """The isolation claim, tested on findings that actually reached a card.

        The test above drops the last finding of the Finish, which on several
        fixtures is one the plan had already refused, so a card that never
        moved would prove nothing. This one takes a finding out of each course
        in turn, and only ones the plan admitted, which is the case that can
        move something. Planning now sits between judge and voice and shares a
        seed with it, so a finding leaving one course is exactly where
        cross-course coupling would reappear.
        """
        from sommelier.judge import judge
        from sommelier.plan import compose as compose_plan

        from tests.test_judge import spread

        tried = 0
        for name, metrics in spread():
            judgement = judge(metrics)
            plan = compose_plan(metrics, judgement)
            before = {c.name: c.body for c in pour(plan).courses}
            for planned in plan.courses:
                for proposition in planned.propositions:
                    tried += 1
                    dropped = proposition.finding
                    thinner = _judgement_like(
                        judgement,
                        tuple(f for f in judgement.findings if f.key != dropped.key),
                    )
                    after = {
                        c.name: c.body
                        for c in pour(compose_plan(metrics, thinner)).courses
                    }
                    moved = sorted(
                        course
                        for course in before
                        if course != COURSE_TITLES[planned.name]
                        and before[course] != after.get(course)
                    )
                    with self.subTest(case=name, dropped=dropped.key):
                        self.assertEqual(
                            [],
                            moved,
                            f"{name}: dropping {dropped.key} moved "
                            f"{', '.join(moved)}",
                        )
        self.assertGreater(tried, 50, "the spread stopped producing findings")

    def test_unknown_key_is_dropped_rather_than_raising(self) -> None:
        judgement = _judgement(_finding("label.not_in_cellar", "label", 2))
        card = pour(_plan(self.metrics, judgement))
        self.assertEqual(card.courses, ())


class ProcessDeterminismTests(unittest.TestCase):
    """The same repository, the same card, in a process that shares nothing.

    test_score proves this for the metrics table. The card is the half that
    goes through plan and voice, where a frozenset of fact names decides what
    each finding is left holding: iterate one of those in its own order and
    the card changes with the hash seed and with nothing else. That failure
    is invisible in a single process, because PYTHONHASHSEED cannot be
    changed once the interpreter has started.
    """

    def test_two_processes_agree_on_the_whole_card(self) -> None:
        fixtures.require_git()
        with fixtures.neglected_js_repo() as fixture:
            cards: list[str] = []
            for seed in ("0", "1", "524287"):
                environment = dict(os.environ)
                environment["PYTHONHASHSEED"] = seed
                completed = subprocess.run(
                    [sys.executable, "-m", "sommelier.cli", "taste",
                     str(fixture.path)],
                    cwd=str(REPO_ROOT),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=True,
                )
                cards.append(completed.stdout)
        self.assertIn("CODE SOMMELIER", cards[0], "the subprocess printed no card")
        self.assertEqual(
            1,
            len(set(cards)),
            "two readings of one repository disagreed:\n" + "\n".join(cards),
        )


class CellarFormattingTests(unittest.TestCase):
    """Every shipped template must format from the facts its key provides."""

    def test_every_template_formats_with_its_declared_facts(self) -> None:
        for key, templates in lines_module.CELLAR.items():
            facts = {name: "X" for name in judge_module.KEY_FACTS[key]}
            for index, template in enumerate(templates):
                with self.subTest(key=key, index=index):
                    rendered = template.format(**facts)
                    self.assertNotIn("{", rendered)
                    self.assertNotIn("}", rendered)

    def test_every_key_has_at_least_three_lines(self) -> None:
        thin = {
            key: len(templates)
            for key, templates in lines_module.CELLAR.items()
            if len(templates) < 3
        }
        self.assertEqual(thin, {}, f"keys with fewer than three lines: {thin}")

    def test_verdict_templates_state_the_score_band_and_denominator(self) -> None:
        """A score without its denominator is what this rewrite exists to remove."""
        for template in lines_module.VERDICTS:
            with self.subTest(template=template):
                self.assertEqual(
                    set(PLACEHOLDER.findall(template)),
                    {"score", "band", "scored", "total"},
                )

    def test_verdicts_no_longer_disown_the_number(self) -> None:
        """The old lines existed to say the score meant nothing. It does now."""
        for template in lines_module.VERDICTS:
            with self.subTest(template=template):
                lowered = template.lower()
                for dead in ("formality", "never told anyone", "between 87 and 94"):
                    self.assertNotIn(dead, lowered)

    def test_every_refusal_code_has_at_least_three_lines(self) -> None:
        thin = {
            code: len(templates)
            for code, templates in lines_module.REFUSALS.items()
            if len(templates) < 3
        }
        self.assertEqual(thin, {}, f"refusal codes with fewer than three lines: {thin}")

    def test_every_refusal_template_formats_from_its_declared_facts(self) -> None:
        for code, templates in lines_module.REFUSALS.items():
            facts = {name: "X" for name in judge_module.REFUSAL_FACTS[code]}
            for index, template in enumerate(templates):
                with self.subTest(code=code, index=index):
                    rendered = template.format(**facts)
                    self.assertNotIn("{", rendered)
                    self.assertNotIn("}", rendered)

    def test_a_refused_card_states_the_reason_and_no_number(self) -> None:
        metrics = synthetic_metrics(name="templates-only")
        judgement = _judgement(
            score=None,
            band="unscoreable",
            band_label="No score",
            refusal="no_source_files",
            refusal_facts={"name": "templates-only", "total_files": "309"},
        )
        card = pour(_plan(metrics, judgement), seed=5)
        self.assertIsNone(card.score)
        self.assertIn("309", card.verdict)
        self.assertNotIn("points", card.verdict)
        rendered = render_card(card)
        self.assertIn("Verdict", rendered)
        self.assertNotIn("{", rendered)

    def test_every_refusal_code_renders_a_verdict(self) -> None:
        metrics = synthetic_metrics(name="todo-app")
        for code in judge_module.REFUSALS:
            facts = {name: "7" for name in judge_module.REFUSAL_FACTS[code]}
            judgement = _judgement(
                score=None,
                band="unscoreable",
                band_label="No score",
                refusal=code,
                refusal_facts=facts,
            )
            with self.subTest(code=code):
                card = render_card(pour(_plan(metrics, judgement), seed=11))
                self.assertNotIn("{", card)
                self.assertNotIn("None", card)

    def test_pairings_take_no_placeholders(self) -> None:
        for template in lines_module.PAIRINGS:
            with self.subTest(template=template):
                self.assertEqual(PLACEHOLDER.findall(template), [])

    def test_rendered_card_never_leaks_a_placeholder(self) -> None:
        metrics = synthetic_metrics(name="todo-app")
        for key, fact_names in judge_module.KEY_FACTS.items():
            course = key.split(".")[0]
            if course not in judge_module.COURSES:
                course = "nose"
            judgement = _judgement(
                _finding(key, course, 2, **{name: f"X{name}" for name in fact_names})
            )
            with self.subTest(key=key):
                card = render_card(pour(_plan(metrics, judgement), seed=3))
                self.assertNotIn("{", card)


if __name__ == "__main__":
    unittest.main()
