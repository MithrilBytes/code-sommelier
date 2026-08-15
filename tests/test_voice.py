"""Tests for the voice layer.

Two kinds of test live here, deliberately separated.

The snapshot tests run against a small frozen cellar patched in for the
duration of the test. That keeps the snapshot stable when somebody adds a new
tasting line, which is a thing the project actively wants people to do. A
snapshot taken over the real cellar would fail on every contribution and would
teach contributors to regenerate it without reading it.

The determinism and formatting tests run against the real cellar, because
those are the properties that must hold for the shipped material.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

from sommelier import judge as judge_module
from sommelier import lines as lines_module
from sommelier.judge import Finding, Judgement
from sommelier.render import render_card
from sommelier.voice import pour, stable_seed

from tests.fixtures import synthetic_metrics

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

FROZEN_CELLAR = {
    "label.identity": (
        "{name}. {primary_language}. {source_files} source files.",
        "{name} holds {source_files} files of {primary_language}.",
        "{source_files} files. {primary_language}. This is {name}.",
    ),
    "palate.cry_for_help": (
        "{largest_file} runs to {largest_lines} lines, which is not a module.",
        "One file, {largest_file}, contains {largest_lines} lines.",
        "{largest_lines} lines in {largest_file}. Nobody decided this.",
    ),
}

FROZEN_VERDICTS = ("{score} points. {band}, on {scored} of {total} dimensions.",)
FROZEN_PAIRINGS = ("Pairs well with a strong drink and a rewrite.",)

FROZEN_REFUSALS = {
    "no_source_files": ("No score. {name} holds {total_files} files, none of it code.",),
}


def _finding(key: str, course: str, severity: int, **facts: str) -> Finding:
    return Finding(key=key, course=course, severity=severity, facts=dict(facts))


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
                primary_language="JavaScript",
                source_files="13",
                total_files="14,203",
            ),
            _finding(
                "palate.cry_for_help",
                "palate",
                3,
                largest_file="src/app.js",
                largest_lines="2,400",
            ),
        )
        with (
            mock.patch.object(lines_module, "CELLAR", FROZEN_CELLAR),
            mock.patch.object(lines_module, "VERDICTS", FROZEN_VERDICTS),
            mock.patch.object(lines_module, "PAIRINGS", FROZEN_PAIRINGS),
            mock.patch("sommelier.voice.CELLAR", FROZEN_CELLAR),
            mock.patch("sommelier.voice.VERDICTS", FROZEN_VERDICTS),
            mock.patch("sommelier.voice.PAIRINGS", FROZEN_PAIRINGS),
        ):
            return render_card(pour(metrics, judgement, seed=seed))

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
                primary_language="Python",
                source_files="13",
                total_files="13",
            )
        )

    def test_same_repo_receives_the_same_tasting(self) -> None:
        first = pour(self.metrics, self.judgement)
        second = pour(self.metrics, self.judgement)
        self.assertEqual(render_card(first), render_card(second))

    def test_tasting_number_is_in_range(self) -> None:
        for seed in range(50):
            card = pour(self.metrics, self.judgement, seed=seed)
            self.assertGreaterEqual(card.tasting_number, 1)
            self.assertLessEqual(card.tasting_number, 99)

    def test_explicit_seed_overrides_the_repo_name(self) -> None:
        unseeded = pour(self.metrics, self.judgement)
        seeded = {
            pour(self.metrics, self.judgement, seed=n).tasting_number
            for n in range(30)
        }
        self.assertIn(unseeded.tasting_number, range(1, 100))
        self.assertGreater(len(seeded), 1)

    def test_unknown_key_is_dropped_rather_than_raising(self) -> None:
        judgement = _judgement(_finding("label.not_in_cellar", "label", 2))
        card = pour(self.metrics, judgement)
        self.assertEqual(card.courses, ())


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
        card = pour(metrics, judgement, seed=5)
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
                card = render_card(pour(metrics, judgement, seed=11))
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
                _finding(key, course, 2, **{name: "X" for name in fact_names})
            )
            with self.subTest(key=key):
                card = render_card(pour(metrics, judgement, seed=3))
                self.assertNotIn("{", card)


if __name__ == "__main__":
    unittest.main()
