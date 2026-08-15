"""The content plan, and the promise it exists to keep.

One rule is under test here, stated three ways because a reader can notice it
any of them: a course never states one measurement twice, a course never
prints one value twice, and a course never prints one value at two precisions.
The first catches `palate.body` and `palate.cry_for_help` both reporting
`palate.largest_file_lines` under different local names. The second catches two
different measurements that read the same, which is how antirez/kilo printed
`kilo.c` as both its largest file and its most deeply nested one. The third
catches the pair that survived both of those and shipped: a repository whose
average file length lands on a whole number is written 5.0 by the average and 5
by every other line count, so the palate said `1 files, 5 lines, 5.0 to a file`
and disagreed with itself inside one clause. Precision belongs to the unit, and
that alone does not stop two units meeting on one number.

The structural tests prove the property for every form voice could possibly
draw, not merely for the one it drew today. A proposition may only be realised
through a form citing facts the plan left it holding, so disjoint holdings
across a course is the whole guarantee.

`RenderedCardTests` then proves it again on the page, which is the only place
a reader meets it. That pass also pins two things the structural pass cannot
see: that every sentence on a card is a cellar form the plan allowed, and that
the digits on the card are exactly the digits of the facts behind it, so no
line can smuggle in a number nobody measured.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from sommelier.collect import RepoMetrics
from sommelier.judge import (
    AVERAGE,
    COUNT,
    COURSES,
    LINES,
    PATH,
    Fact,
    Finding,
    Judgement,
    judge,
)
from sommelier.lines import CELLAR
from sommelier.plan import (
    MAX_LINES_PER_COURSE,
    MAX_LINES_WHEN_EMPTY,
    Plan,
    PlannedCourse,
    Proposition,
    Verdict,
    _allocate,
    _cited,
    _compose_course,
    _contradicts,
    _forms_available,
    _reads_clean,
    _yields_to,
    compose,
)
from sommelier.voice import COURSE_TITLES, pour

from tests import corpus, fixtures
from tests.test_judge import repo_with_palate, spread

# Large enough that the walk is never the thing that decides the result. The
# same value test_golden uses, and for the same reason.
GOLDEN_BUDGET: float = 120.0


def whole_number_averages() -> tuple[tuple[str, RepoMetrics], ...]:
    """Repositories whose average file length lands on a whole number.

    The trap the unit table cannot see. Precision belongs to the measurement,
    so the average is always written to one place and every other line count to
    none, and the two disagree the moment they land on the same number. Every
    real repository in the corpus averages to something fractional, which is
    the only reason the defect was not visible there. It was visible in two
    shipped golden cards.
    """
    return (
        (
            "average equals the largest file",
            repo_with_palate(
                source_file_count=2,
                total_lines=10,
                average_lines=5.0,
                largest_file_lines=5,
            ),
        ),
        (
            "average equals the total",
            repo_with_palate(
                source_file_count=1,
                total_lines=5,
                average_lines=5.0,
                largest_file_lines=5,
            ),
        ),
        (
            "average equals the file count",
            repo_with_palate(
                source_file_count=40,
                total_lines=1600,
                average_lines=40.0,
                largest_file_lines=91,
            ),
        ),
    )


def _fact(measurement: str, value: object, unit: str) -> Fact:
    assert isinstance(value, (int, float, str)) or value is None
    return Fact(measurement=measurement, value=value, unit=unit)


def _finding(key: str, course: str, severity: int, **facts: Fact) -> Finding:
    return Finding(key=key, course=course, severity=severity, facts=dict(facts))


def _stated(course: PlannedCourse) -> Iterator[tuple[str, tuple[Fact, ...]]]:
    """What each sentence of the course may put in front of a reader.

    Grouped by finding, because the rule is about a course repeating itself
    and not about one sentence. A single sentence naming 855 commits and the
    855 of them titled fix names one count twice and reads correctly.
    """
    for proposition in course.propositions:
        yield (
            proposition.finding.key,
            tuple(
                proposition.finding.facts[name]
                for name in sorted(proposition.allowed)
            ),
        )


class InvariantCase(unittest.TestCase):
    def assert_says_nothing_twice(self, label: str, plan: Plan) -> None:
        for course in plan.courses:
            measurements: dict[str, str] = {}
            values: dict[tuple[str, str], str] = {}
            for key, facts in _stated(course):
                where = f"{label} {course.name}: {key}"
                for fact in facts:
                    self.assertNotIn(
                        fact.measurement,
                        measurements,
                        f"{where} restates {fact.measurement}, already stated "
                        f"by {measurements.get(fact.measurement)}",
                    )
                    written = (fact.unit, fact.written())
                    self.assertNotIn(
                        written,
                        values,
                        f"{where} prints {fact.written()} a second time, after "
                        f"{values.get(written)}",
                    )
                for fact in facts:
                    measurements[fact.measurement] = key
                    values[(fact.unit, fact.written())] = key

    def assert_agrees_on_precision(self, label: str, plan: Plan) -> None:
        """No course writes one number two ways, in one sentence or across two.

        Two readings, because the pair that shipped could arrive either way.
        Inside `palate.body` the average is written to one decimal place and
        every other line count to none, so a repository whose average happens
        to be whole says 5 lines and 5.0 to a file in one clause. Split over
        two findings it is the largest file at 5 lines and the average at 5.0.
        A reader cannot tell either from a rounding error, and should not have
        to.

        Within a sentence the unit of judgement is the form, since that is
        what decides which of the facts a finding holds are printed together.
        Across sentences it is everything the finding holds, which is stricter
        than what it will say and is the guarantee the allocation offers.
        """
        for course in plan.courses:
            said: dict[str, str] = {}
            for proposition in course.propositions:
                finding = proposition.finding
                forms = _forms_available(finding.key)
                for index in proposition.forms:
                    readings = sorted(
                        {finding.facts[name].reading() for name in forms[index]}
                    )
                    inside = [
                        (readings[at], other)
                        for at in range(len(readings))
                        for other in readings[at + 1 :]
                        if _contradicts(readings[at], other)
                    ]
                    self.assertEqual(
                        [],
                        inside,
                        f"{label} {course.name}: {finding.key} form {index} "
                        f"writes one quantity at two precisions",
                    )
                held = {
                    finding.facts[name].reading() for name in proposition.allowed
                }
                for reading in sorted(held):
                    clash = sorted(
                        other for other in said if _contradicts(reading, other)
                    )
                    self.assertEqual(
                        [],
                        clash,
                        f"{label} {course.name}: {finding.key} writes {reading} "
                        f"beside {clash} from {[said[c] for c in clash]}, which "
                        f"is one quantity at two precisions",
                    )
                for reading in held:
                    said.setdefault(reading, finding.key)

    def assert_nothing_sharper_was_dropped(
        self, label: str, metrics: RepoMetrics, judgement: Judgement, plan: Plan
    ) -> None:
        """Deduplication may cost a course a line. It may not cost it the worst one.

        Saying less is the price of not saying it twice, and the direction the
        card may never be wrong in is the other one. A course that dropped a
        severity two finding while printing a severity zero one, with a line
        still going spare, is quieter about a repository than the metrics
        justify, whatever it says about the plan's internals.

        A full course is exempt: three findings admitted and a fourth turned
        away is the budget, which is a decision made before any of this and
        is tested by assert_within_budget.
        """
        ceiling = MAX_LINES_WHEN_EMPTY if metrics.is_empty else MAX_LINES_PER_COURSE
        admitted_by_course = {
            course.name: [p.finding for p in course.propositions]
            for course in plan.courses
        }
        for course in COURSES:
            emitted = [f for f in judgement.findings if f.course == course]
            admitted = admitted_by_course.get(course, [])
            if not emitted or len(admitted) >= ceiling:
                continue
            keys = {finding.key for finding in admitted}
            for dropped in (f for f in emitted if f.key not in keys):
                milder = sorted(
                    f"{f.key} at {f.severity}"
                    for f in admitted
                    if f.severity < dropped.severity
                )
                self.assertEqual(
                    [],
                    milder,
                    f"{label} {course}: dropped {dropped.key} at severity "
                    f"{dropped.severity} while printing {', '.join(milder)}, "
                    f"with {ceiling - len(admitted)} lines going spare",
                )

    def assert_within_budget(self, label: str, metrics: RepoMetrics, plan: Plan) -> None:
        ceiling = MAX_LINES_WHEN_EMPTY if metrics.is_empty else MAX_LINES_PER_COURSE
        for course in plan.courses:
            self.assertLessEqual(len(course.propositions), ceiling, label)
            self.assertTrue(course.propositions, f"{label}: empty course survived")
            for proposition in course.propositions:
                self.assertTrue(
                    proposition.forms, f"{label}: proposition with no form"
                )


class SyntheticInvariantTests(InvariantCase):
    """Every fixture from spotless to catastrophic, on the real cellar."""

    def test_no_course_says_the_same_thing_twice(self) -> None:
        for name, metrics in spread() + whole_number_averages():
            with self.subTest(case=name):
                self.assert_says_nothing_twice(name, compose(metrics, judge(metrics)))

    def test_no_course_contradicts_itself_on_precision(self) -> None:
        for name, metrics in spread() + whole_number_averages():
            with self.subTest(case=name):
                self.assert_agrees_on_precision(
                    name, compose(metrics, judge(metrics))
                )

    def test_every_course_stays_inside_its_budget(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                plan = compose(metrics, judge(metrics))
                self.assert_within_budget(name, metrics, plan)

    def test_no_course_goes_quiet_about_the_worst_of_it(self) -> None:
        for name, metrics in spread() + whole_number_averages():
            with self.subTest(case=name):
                judgement = judge(metrics)
                self.assert_nothing_sharper_was_dropped(
                    name, metrics, judgement, compose(metrics, judgement)
                )

    def test_planning_is_a_pure_function_of_the_judgement(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                judgement = judge(metrics)
                self.assertEqual(
                    compose(metrics, judgement), compose(metrics, judgement)
                )


class CorpusInvariantTests(InvariantCase):
    """The same rule on ten real repositories, which is where it was broken."""

    def setUp(self) -> None:
        self.cached = [
            entry
            for entry in corpus.load_manifest()
            if corpus.cached_commit(entry) is not None
        ]
        if not self.cached:
            self.skipTest("corpus cache is empty; run `python3 -m tests.corpus --sync`")

    def _metrics(self, entry: corpus.Entry) -> RepoMetrics:
        from unittest.mock import patch

        import sommelier.collect as collect_module

        with patch.object(
            collect_module, "date", corpus.frozen_date_class(corpus.FROZEN_TODAY)
        ):
            return collect_module.collect(
                entry.path, budget_seconds=corpus.CORPUS_BUDGET_SECONDS
            )

    def test_no_course_says_the_same_thing_twice(self) -> None:
        for entry in self.cached:
            with self.subTest(entry.slug):
                metrics = self._metrics(entry)
                judgement = judge(metrics)
                plan = compose(metrics, judgement)
                self.assert_says_nothing_twice(entry.slug, plan)
                self.assert_agrees_on_precision(entry.slug, plan)
                self.assert_within_budget(entry.slug, metrics, plan)
                self.assert_nothing_sharper_was_dropped(
                    entry.slug, metrics, judgement, plan
                )


# A number as a reader meets it, whole. Dates are lifted out first so that
# 2011-08-01 is one reading and not the three that a digit scan would find in
# it, and the boundary keeps the 2 out of src/v2/app.py.
_DATE = re.compile(r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])")
_NUMBER = re.compile(r"(?<![\w.,/-])\d(?:[\d,]*\d)?(?:\.\d+)?(?!\d|,\d|\.\d)")


def figures(text: str) -> list[str]:
    """Every number printed in one piece of text, in order."""
    found = _DATE.findall(text)
    return found + _NUMBER.findall(_DATE.sub(lambda m: "#" * len(m.group(0)), text))


def two_ways(one: str, other: str) -> bool:
    """Whether two printed numbers are one quantity written twice.

    Deliberately not `plan._contradicts`. A gate that asks the code under test
    whether the code under test is right proves nothing, so this reads the
    digits off the page and decides for itself. The two agreeing is the point.
    """
    try:
        left, right = float(one.replace(",", "")), float(other.replace(",", ""))
    except ValueError:
        return False
    places = (len(one.partition(".")[2]), len(other.partition(".")[2]))
    if places[0] == places[1]:
        return False
    return round(left, min(places)) == round(right, min(places))


def _sentences(
    proposition: Proposition, body: str, offset: int
) -> tuple[int, tuple[Fact, ...]] | None:
    """Match one proposition against the next sentence of a rendered course.

    Returns where the sentence ends and the facts it put on the page. None
    when no form the plan allowed produces the text that is actually there,
    which is itself a finding: the card would be saying something the plan
    did not sanction.
    """
    finding = proposition.finding
    templates = CELLAR.get(finding.key, ())
    written = {name: fact.written() for name, fact in finding.facts.items()}
    for index in proposition.forms:
        if index >= len(templates):
            continue
        try:
            rendered = templates[index].format(**written)
        except (KeyError, IndexError):
            continue
        if body.startswith(rendered, offset):
            cited = frozenset(
                name for name in finding.facts if f"{{{name}}}" in templates[index]
            )
            return offset + len(rendered) + 1, tuple(
                finding.facts[name] for name in sorted(cited)
            )
    return None


class RenderedCardTests(unittest.TestCase):
    """The same rule, read off the page instead of off the plan.

    The structural pass proves the plan cannot ask for a repetition. This one
    proves the card does not contain one, which is a different claim: it also
    covers the draw voice makes, the wording of the form it lands on, and the
    digits the prose carries of its own accord.

    One repetition is permitted and it is named here so that it stays a
    decision rather than a hole: two facts in the same sentence, in the same
    unit, may read alike. That is `0 dependencies and 0 development
    dependencies`, and `8 source files out of 8 on disk`, where the equality is
    the information. Across two sentences, in two units, or at two precisions,
    there is no such reading and the gate fails.
    """

    def spoken(
        self, label: str, metrics: RepoMetrics
    ) -> Iterator[tuple[str, str, tuple[tuple[Fact, ...], ...]]]:
        """(course, body, facts per sentence) for a whole rendered card."""
        judgement = judge(metrics)
        plan = compose(metrics, judgement)
        card = pour(plan)
        bodies = {course.name: course.body for course in card.courses}
        for planned in plan.courses:
            title = COURSE_TITLES[planned.name]
            body = bodies.get(title)
            self.assertIsNotNone(
                body, f"{label} {title}: planned course reached no reader"
            )
            assert body is not None
            offset = 0
            per_sentence: list[tuple[Fact, ...]] = []
            for proposition in planned.propositions:
                matched = _sentences(proposition, body, offset)
                self.assertIsNotNone(
                    matched,
                    f"{label} {title}: {proposition.finding.key} is not on the "
                    f"page in any form the plan allowed it",
                )
                assert matched is not None
                offset, facts = matched
                per_sentence.append(facts)
            yield title, body, tuple(per_sentence)

    def assert_card_reads_clean(self, label: str, metrics: RepoMetrics) -> None:
        for title, body, per_sentence in self.spoken(label, metrics):
            where = f"{label} {title}"

            printed = Counter(figures(body))
            from_facts: Counter[str] = Counter()
            for facts in per_sentence:
                for fact in facts:
                    from_facts.update(figures(fact.written()))
            self.assertEqual(
                dict(printed),
                dict(from_facts),
                f"{where}: the digits on the page are not the digits of the "
                f"facts behind it",
            )

            said: dict[str, tuple[int, str]] = {}
            for position, facts in enumerate(per_sentence):
                for fact in facts:
                    reading = fact.reading()
                    seen = said.get(reading)
                    if seen is not None:
                        sentence, unit = seen
                        self.assertEqual(
                            (position, fact.unit),
                            (sentence, unit),
                            f"{where}: {reading} is printed twice, and not as "
                            f"one sentence comparing two quantities in one unit",
                        )
                    clash = sorted(other for other in said if two_ways(reading, other))
                    self.assertEqual(
                        [],
                        clash,
                        f"{where}: {reading} is printed beside {clash}, which is "
                        f"one quantity at two precisions",
                    )
                    said.setdefault(reading, (position, fact.unit))

            digits = sorted(set(figures(body)))
            pairs = sorted(
                (digits[at], other)
                for at in range(len(digits))
                for other in digits[at + 1 :]
                if two_ways(digits[at], other)
            )
            self.assertEqual(
                [], pairs, f"{where}: the page prints {pairs} of one quantity"
            )

    def test_no_rendered_course_repeats_itself(self) -> None:
        for name, metrics in spread() + whole_number_averages():
            with self.subTest(case=name):
                self.assert_card_reads_clean(name, metrics)


class RenderedCorpusTests(RenderedCardTests):
    """The rendered rule on the ten repositories the defect was measured on."""

    def setUp(self) -> None:
        self.cached = [
            entry
            for entry in corpus.load_manifest()
            if corpus.cached_commit(entry) is not None
        ]
        if not self.cached:
            self.skipTest("corpus cache is empty; run `python3 -m tests.corpus --sync`")

    def test_no_rendered_course_repeats_itself(self) -> None:
        from unittest.mock import patch

        import sommelier.collect as collect_module

        for entry in self.cached:
            with self.subTest(entry.slug):
                with patch.object(
                    collect_module,
                    "date",
                    corpus.frozen_date_class(corpus.FROZEN_TODAY),
                ):
                    metrics = collect_module.collect(
                        entry.path, budget_seconds=corpus.CORPUS_BUDGET_SECONDS
                    )
                self.assert_card_reads_clean(entry.slug, metrics)


class FixtureRepositoryTests(RenderedCardTests, InvariantCase):
    """The same rule on the trees the golden cards are cut from.

    spread() is metrics assembled by hand and the corpus is a cache that may
    not be there, so between them the gate could pass on a machine holding
    neither the trap nor the real thing. These are directories on disk, walked
    by collect, and they are the exact inputs behind tests/golden. The defect
    shipped in two of those cards: bare-directory read `2 files averaging 5.0
    lines. The largest, helper.py, runs to 5.`, which is the whole disease in
    one sentence.
    """

    BUILDERS = (
        ("healthy-python", fixtures.healthy_python_repo),
        ("neglected-js", fixtures.neglected_js_repo),
        ("bare-directory", fixtures.bare_directory),
        ("no-commits", fixtures.git_repo_without_commits),
        ("empty-directory", fixtures.empty_directory),
        ("unknown-language", fixtures.unknown_language_repo),
        ("deep-and-long", fixtures.deep_and_long_repo),
    )

    def _measure(self, root: Path) -> RepoMetrics:
        from unittest.mock import patch

        import sommelier.collect as collect_module

        with patch.object(
            collect_module,
            "date",
            corpus.frozen_date_class(corpus.FROZEN_TODAY),
        ):
            metrics = collect_module.collect(root, budget_seconds=GOLDEN_BUDGET)
        self.assertEqual(
            (),
            metrics.dropped,
            "an analyzer was dropped, so this is not the fixture under test",
        )
        return metrics

    def test_no_rendered_course_repeats_itself(self) -> None:
        fixtures.require_git()
        for label, build in self.BUILDERS:
            with self.subTest(label):
                with build() as fixture:
                    metrics = self._measure(fixture.path)
                    judgement = judge(metrics)
                    plan = compose(metrics, judgement)
                    self.assert_says_nothing_twice(label, plan)
                    self.assert_agrees_on_precision(label, plan)
                    self.assert_within_budget(label, metrics, plan)
                    self.assert_nothing_sharper_was_dropped(
                        label, metrics, judgement, plan
                    )
                    self.assert_card_reads_clean(label, metrics)


class AllocationTests(unittest.TestCase):
    """Who gets the measurement when two findings can both cite it."""

    def _palate(self) -> Sequence[Finding]:
        path = _fact("palate.largest_file_path", "src/app.js", PATH)
        lines = _fact("palate.largest_file_lines", 2400, LINES)
        files = _fact("palate.source_file_count", 13, COUNT)
        return (
            _finding(
                "palate.body",
                "palate",
                0,
                source_files=files,
                largest_path=path,
                largest_lines=lines,
            ),
            _finding("palate.cry_for_help", "palate", 3, path=path, lines=lines),
        )

    def test_the_sharper_finding_takes_the_shared_measurement(self) -> None:
        allowed = _allocate(self._palate())
        self.assertEqual({"path", "lines"}, set(allowed["palate.cry_for_help"]))
        self.assertEqual({"source_files"}, set(allowed["palate.body"]))

    def test_a_finding_never_blocks_itself(self) -> None:
        """One sentence naming a file and its length is a sentence."""
        allowed = _allocate(self._palate()[1:])
        self.assertEqual({"path", "lines"}, set(allowed["palate.cry_for_help"]))

    def test_two_measurements_reading_the_same_collide(self) -> None:
        """kilo.c is both the largest file and the deepest, and is named once."""
        findings = (
            _finding(
                "palate.body",
                "palate",
                0,
                largest_path=_fact("palate.largest_file_path", "kilo.c", PATH),
            ),
            _finding(
                "palate.abyssal",
                "palate",
                3,
                path=_fact("palate.max_indent_path", "kilo.c", PATH),
            ),
        )
        allowed = _allocate(findings)
        self.assertEqual({"path"}, set(allowed["palate.abyssal"]))
        self.assertEqual(set(), set(allowed["palate.body"]))

    def test_a_sentence_is_not_drawn_when_it_would_stutter(self) -> None:
        """22 authors and 22 percent are one number to whoever reads them."""
        finding = _finding(
            "finish.history",
            "finish",
            0,
            authors_phrase=_fact("git.author_count", 22, "authors"),
            fix_percent=_fact("git.fix_ratio", 0.22, "percent"),
            commits_phrase=_fact("git.commit_count", 76, "commits"),
        )
        self.assertFalse(
            _reads_clean(finding, frozenset({"authors_phrase", "fix_percent"}))
        )
        self.assertTrue(
            _reads_clean(finding, frozenset({"authors_phrase", "commits_phrase"}))
        )

    def test_a_deliberate_comparison_in_one_unit_still_reads(self) -> None:
        """Zero declared and zero for development is a sentence, not a stutter."""
        finding = _finding(
            "structure.declared",
            "structure",
            0,
            declared=_fact("structure.declared_count", 0, COUNT),
            dev=_fact("structure.dev_count", 0, COUNT),
        )
        self.assertTrue(_reads_clean(finding, frozenset({"declared", "dev"})))

    def test_the_opening_line_leads_at_equal_severity(self) -> None:
        """Vintage opens on the dates, and the age yields to them."""
        first = _fact("git.first_commit", "2011-08-01", "date")
        findings = (
            _finding("vintage.aged", "vintage", 0, first_date=first),
            _finding("vintage.declared", "vintage", 0, first_date=first),
        )
        allowed = _allocate(findings)
        self.assertEqual({"first_date"}, set(allowed["vintage.declared"]))
        self.assertEqual(set(), set(allowed["vintage.aged"]))


def _one_course(course: PlannedCourse) -> Plan:
    """A single course wrapped so the real gate can be run over it."""
    return Plan(
        repo_name="fixture",
        courses=(course,),
        verdict=Verdict(
            score=50,
            band_label="Unacceptable",
            scored_dimensions=1,
            total_dimensions=1,
            refusal=None,
            refusal_facts={},
        ),
        footnotes=(),
    )


class PrecisionTests(InvariantCase):
    """One number, written once.

    Fixing precision to the unit stops one measurement being written two ways.
    It does nothing about two measurements meeting on the same number, which is
    the case that reached the goldens: a two file repository of five lines
    apiece prints the total as 5 and the average as 5.0.
    """

    def test_one_number_at_two_precisions_is_a_contradiction(self) -> None:
        self.assertTrue(_contradicts("15.0", "15"))
        self.assertTrue(_contradicts("5", "5.0"))
        self.assertTrue(_contradicts("1,665", "1,665.0"))
        self.assertTrue(_contradicts("496", "496.0"))

    def test_two_numbers_that_merely_match_are_not(self) -> None:
        """Same precision is a comparison. Different numbers are two numbers."""
        self.assertFalse(_contradicts("0", "0"))
        self.assertFalse(_contradicts("15.7", "15.8"))
        self.assertFalse(_contradicts("15.5", "15"))
        self.assertFalse(_contradicts("4.6", "1,665"))

    def test_text_never_contradicts_anything(self) -> None:
        self.assertFalse(_contradicts("src/app.py", "5"))
        self.assertFalse(_contradicts("2011-08-01", "2011"))
        self.assertFalse(_contradicts("unknown", "unknown"))

    def _body(self) -> Finding:
        """A palate whose average lands on a whole number, which is the trap."""
        return _finding(
            "palate.body",
            "palate",
            0,
            source_files=_fact("palate.source_file_count", 1, COUNT),
            total_lines=_fact("palate.total_lines", 5, LINES),
            average_lines=_fact("palate.average_lines", 5.0, AVERAGE),
        )

    def test_no_sentence_prints_five_lines_and_five_point_zero(self) -> None:
        finding = self._body()
        self.assertFalse(
            _reads_clean(finding, frozenset({"total_lines", "average_lines"})),
            "1 files, 5 lines, 5.0 to a file shipped in a golden card",
        )
        self.assertTrue(_reads_clean(finding, frozenset({"source_files", "total_lines"})))
        self.assertTrue(
            _reads_clean(finding, frozenset({"source_files", "average_lines"}))
        )

    def test_two_sentences_do_not_print_it_either(self) -> None:
        """The pair also has to survive being split across two findings."""
        findings = (
            self._body(),
            _finding(
                "palate.full_bodied",
                "palate",
                1,
                path=_fact("palate.largest_file_path", "helper.py", PATH),
                lines=_fact("palate.largest_file_lines", 5, LINES),
                average_lines=_fact("palate.average_lines", 5.0, AVERAGE),
            ),
        )
        course = _compose_course(findings, MAX_LINES_PER_COURSE)
        self.assertIsNotNone(course)
        assert course is not None
        self.assert_agrees_on_precision("five lines apiece", _one_course(course))


class SeverityTests(unittest.TestCase):
    """A quieter line never keeps a louder one off the card.

    Admitting in reading order and refusing anything that starves an incumbent
    reads as caution and is not: it makes the first line admitted senior to
    every line after it, whatever the findings are worth. Measured before this
    was fixed, the finish on two repositories withheld that a third of the
    history is titled fix, a severity two finding, so that the opening line
    could go on naming the commit count.
    """

    def _finish(self) -> Sequence[Finding]:
        commits = _fact("git.commit_count", 3, "commits")
        fixes = _fact("git.fix_commit_count", 1, "commits")
        ratio = _fact("git.fix_ratio", 0.33, "percent")
        return (
            _finding(
                "finish.history",
                "finish",
                0,
                commits_phrase=commits,
                fixes_phrase=fixes,
                fix_percent=ratio,
            ),
            _finding(
                "finish.fix_ratio",
                "finish",
                2,
                commits_phrase=commits,
                fixes_phrase=fixes,
                fix_percent=ratio,
            ),
        )

    def test_the_sharper_finding_reaches_the_course(self) -> None:
        course = _compose_course(self._finish(), MAX_LINES_PER_COURSE)
        self.assertIsNotNone(course)
        assert course is not None
        self.assertIn(
            "finish.fix_ratio",
            [p.finding.key for p in course.propositions],
            "the opening line kept a severity two finding off the card",
        )

    def test_a_milder_finding_never_turns_out_a_sharper_one(self) -> None:
        sharp, mild = self._finish()[1], self._finish()[0]
        self.assertIsNone(
            _yields_to([sharp], mild),
            "a severity zero line evicted a severity two one",
        )

    def test_eviction_stops_at_the_first_set_that_stands(self) -> None:
        """Only what is in the way goes, and the mildest of it goes first."""
        blocker, candidate = self._finish()[0], self._finish()[1]
        keep = _finding(
            "finish.abrupt",
            "finish",
            1,
            subject=_fact("git.last_commit_subject", "fix login", "text"),
        )
        yielded = _yields_to([blocker, keep], candidate)
        self.assertIsNotNone(yielded, "the sharper finding still had nowhere to go")
        assert yielded is not None
        kept, _settled = yielded
        self.assertEqual(
            ["finish.abrupt", "finish.fix_ratio"],
            [f.key for f in kept],
            "the severity one line went out with the severity zero one",
        )


class TruthfulnessTests(unittest.TestCase):
    """Some findings may not be dropped for being hard to fit.

    A shallow clone is the one the spec singles out: withholding history
    already scores higher than publishing it, and a card that never mentions
    the truncation reads a withheld history as a short one. Every line the
    cellar held for it named the commit count, which vintage.declared claims
    first, so the warning never printed on any repository at all.
    """

    def test_a_shallow_clone_is_always_said_out_loud(self) -> None:
        commits = _fact("git.commit_count", 40, "commits")
        findings = (
            _finding(
                "vintage.declared",
                "vintage",
                0,
                first_year=_fact("git.first_commit", 2018, "year"),
                first_date=_fact("git.first_commit", "2018-05-29", "date"),
                last_date=_fact("git.last_commit", "2024-02-27", "date"),
                years=_fact("git.history_span", 5.7, "years"),
                commit_count=commits,
                commits_phrase=commits,
            ),
            _finding("vintage.shallow", "vintage", 0, commit_count=commits),
        )
        course = _compose_course(findings, MAX_LINES_PER_COURSE)
        self.assertIsNotNone(course)
        assert course is not None
        self.assertIn(
            "vintage.shallow",
            [p.finding.key for p in course.propositions],
            "the reader is never told the history was truncated",
        )

    def test_every_key_can_speak_holding_nothing_or_is_allowed_to_fall(self) -> None:
        """The keys that must survive starvation, and the proof that they do.

        Judge emits these whatever else it emits, and each is a claim about
        what was not measured rather than about what was. A form of theirs has
        to stand when every fact they carry has been claimed elsewhere.
        """
        for key in ("vintage.shallow", "nose.no_license"):
            with self.subTest(key=key):
                self.assertTrue(
                    any(not _cited(template) for template in CELLAR[key]),
                    f"{key} has no line that survives losing every fact",
                )

    def test_the_one_number_vintage_aged_holds_is_a_sum_of_two_others(self) -> None:
        """Why the aged line is allowed to fall, written down.

        Every form of vintage.aged names the first year, the first date or the
        commit count, and vintage.declared opens the course by claiming all
        three, so the aged line reaches no card on any repository. That is a
        real reduction and it is only acceptable because the number it would
        have printed is not a new one: the age is the span of the history plus
        the days since the last commit, both of which the card states. If judge
        ever changes so that is no longer true, the line has to come back, and
        this fails to say so.
        """
        from sommelier.judge import _DAYS_PER_YEAR

        checked = 0
        for name, metrics in spread():
            findings = {f.key: f for f in judge(metrics).findings}
            aged = findings.get("vintage.aged")
            declared = findings.get("vintage.declared")
            if aged is None or declared is None:
                continue
            age = aged.facts["years"].value
            span = declared.facts["years"].value
            self.assertIsInstance(age, float)
            self.assertIsInstance(span, float)
            assert isinstance(age, float) and isinstance(span, float)
            dormant = metrics.git.days_since_last_commit / _DAYS_PER_YEAR
            checked += 1
            with self.subTest(case=name):
                self.assertAlmostEqual(
                    age,
                    span + dormant,
                    places=9,
                    msg=f"{name}: the age is no longer the span plus the "
                    f"dormancy, so dropping vintage.aged now loses a number",
                )
        self.assertGreater(checked, 0, "no fixture reached the aged band")


if __name__ == "__main__":
    unittest.main()
