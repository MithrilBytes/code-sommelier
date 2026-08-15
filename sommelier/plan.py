"""The content plan.

Between judging and realisation. Judge decides what is true; this module
decides what gets said; voice decides how to say it. Nothing here is a string
a reader will ever see.

v1 had no such layer, and the output showed it. Every finding was rendered in
ignorance of its neighbours, so two findings that had measured the same thing
both said it:

    Body: 58 files, 221.2 lines on average, peaking at 3,094 lines in
    tests/test_requests.py. 3,094 lines in tests/test_requests.py.

That is not a rounding bug and no amount of new material fixes it. It is what
happens when a course is three findings queued up rather than a paragraph.

The rule this module enforces is one sentence long: **a measurement already
stated in a course is not stated again.** Everything below is the machinery
for holding to it.

* **Identity.** A fact carries the name of the thing measured, so
  `palate.body`'s `largest_lines` and `palate.cry_for_help`'s `lines` are
  recognised as one measurement under two local names.
* **Value.** Two different measurements that happen to read the same in the
  same unit are also the same sentence to a reader. The largest file and the
  most deeply nested file are different measurements, and in antirez/kilo they
  are both `kilo.c`, printed twice.
* **Claim.** Where two findings can cite one measurement, the sharper of the
  two takes it. The identity line of a course yields to a finding that has
  more to add, which is why `palate.body` carries `total_lines`: it is the one
  quantity no sharper finding is entitled to take from it.
* **Form.** What survives the claim decides how much a finding can say. A
  finding holding five measurements has a long sentence available to it and a
  finding holding one does not, so sentence length varies because the content
  varies rather than because a template was drawn.

A finding with nothing left to say is dropped. Saying less is the price of not
saying it twice, and it is the cheaper of the two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from typing import Final

from sommelier.collect import RepoMetrics
from sommelier.judge import COURSES, Finding, Judgement
from sommelier.lines import CELLAR

# The line that opens a course, before anything sorted by severity. Without
# this the identity line lands last, because it is the least alarming thing
# judge has to say.
OPENING_KEYS: Final[frozenset[str]] = frozenset(
    {
        "label.identity",
        "vintage.declared",
        "vintage.no_history",
        "vintage.empty",
        "nose.documented",
        "palate.body",
        "palate.empty",
        "structure.declared",
        "structure.undeclared",
        "finish.history",
        "finish.no_history",
        "finish.void",
    }
)

MAX_LINES_PER_COURSE: Final[int] = 3

# Nothing to measure gets a short tasting of the void rather than six courses
# of absence. There is no point describing the palate of an empty glass.
EMPTY_COURSES: Final[tuple[str, ...]] = ("label", "vintage", "finish")
MAX_LINES_WHEN_EMPTY: Final[int] = 1

# The plan prefers the fullest form a finding can still use, so a measurement
# nobody took is not left unsaid. Preferring it absolutely would hand most
# findings a single surviving form and make every card sound the same, so the
# choice widens to the next fullest until three forms stand. Three is the
# cellar's own floor for how many ways one thing may be said.
MIN_FORMS: Final[int] = 3


@dataclass(frozen=True)
class Proposition:
    """One finding, and the forms in which the plan will allow it to speak.

    `allowed` names the facts this finding was left holding after the course
    shared out its measurements. `forms` indexes the cellar entry for the
    finding's key, and every form listed cites only allowed facts, so whichever
    one voice draws, the sentence repeats nothing the course has already said.
    An empty forms tuple never reaches here: such a finding is dropped instead.
    """

    finding: Finding
    allowed: frozenset[str]
    forms: tuple[int, ...]


@dataclass(frozen=True)
class PlannedCourse:
    name: str
    propositions: tuple[Proposition, ...]


@dataclass(frozen=True)
class Verdict:
    """The closing line, decided before it is written.

    Whether there is a number at all is a planning decision, not a formatting
    one, so it is settled here and voice only writes down the answer.
    """

    score: int | None
    band_label: str
    scored_dimensions: int
    total_dimensions: int
    refusal: str | None
    refusal_facts: Mapping[str, str]


@dataclass(frozen=True)
class Footnote:
    """An analyzer that started and did not finish, carried through by name."""

    name: str
    reason: str


@dataclass(frozen=True)
class Plan:
    """Everything voice needs, and nothing that would send it back upstream."""

    repo_name: str
    courses: tuple[PlannedCourse, ...]
    verdict: Verdict
    footnotes: tuple[Footnote, ...]


def _order(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    """Reading order: the course opens, then the worst of it, then the rest."""
    return tuple(
        sorted(findings, key=lambda f: (f.key not in OPENING_KEYS, -f.severity, f.key))
    )


def _cited(template: str) -> frozenset[str]:
    """The fact names one template names.

    The cellar is read here for its shape rather than its words. No string
    from it is copied, compared against prose, or carried any further: this
    module never holds material.
    """
    names: set[str] = set()
    for _literal, field, _spec, _conversion in Formatter().parse(template):
        if field is None:
            continue
        root = field.split(".")[0].split("[")[0].strip()
        if root:
            names.add(root)
    return frozenset(names)


def _forms_available(key: str) -> tuple[frozenset[str], ...]:
    return tuple(_cited(template) for template in CELLAR.get(key, ()))


def _figure(reading: str) -> tuple[float, int] | None:
    """A reading as a number and the decimal places it was written to.

    None for anything that is not a number, which is most of a path and all of
    a commit subject.
    """
    try:
        value = float(reading.replace(",", ""))
    except ValueError:
        return None
    return value, len(reading.partition(".")[2])


def _contradicts(one: str, other: str) -> bool:
    """Whether two readings are one quantity written to two precisions.

    15.0 and 15 are the same number and a reader who meets both in a course
    reads a disagreement about it, whatever the two units were called. Two
    readings at the same precision are not this: they are two quantities that
    happen to match, which is the comparison case and stays.

    The unit table fixes the precision of each measurement, so this can only
    arise between two different measurements. It arises often: the average
    file length is written to one place and every other line count to none,
    so any repository whose average happens to be whole prints the pair.
    """
    left = _figure(one)
    right = _figure(other)
    if left is None or right is None or left[1] == right[1]:
        return False
    coarser = min(left[1], right[1])
    return round(left[0], coarser) == round(right[0], coarser)


def _reads_clean(finding: Finding, cited: frozenset[str]) -> bool:
    """Whether one sentence can cite all of these without stuttering.

    Two quantities in one unit are a comparison somebody wrote on purpose:
    zero dependencies declared and zero for development is a sentence. Two
    quantities in different units that happen to read alike are a coincidence,
    and 22 authors followed by 22 percent reads as a number said twice. Where
    that happens the sentence is not drawn, and another one is.

    A pair that contradicts itself on precision is refused on the same terms,
    and for a stronger reason: 5 lines beside 5.0 lines to a file is not a
    coincidence a reader forgives, it is the card disagreeing with itself
    inside one clause.
    """
    units: dict[str, str] = {}
    for name in sorted(cited):
        fact = finding.facts.get(name)
        if fact is None:
            return False
        if units.setdefault(fact.reading(), fact.unit) != fact.unit:
            return False
    readings = sorted(units)
    return not any(
        _contradicts(readings[index], other)
        for index in range(len(readings))
        for other in readings[index + 1 :]
    )


def _allocate(findings: Sequence[Finding]) -> dict[str, frozenset[str]]:
    """Which facts each finding is left holding, once the course has shared out.

    Claim order is severity first, reading order second, so the sharpest thing
    a course has to say takes the measurement and the identity line works with
    what is left. A finding's own facts never collide with each other: one
    sentence citing a file's name and its length is a sentence, not a
    repetition, so a finding claims as a whole and only then blocks its
    neighbours.

    A reading is blocked by anything already said that reads as the same
    number, and that includes the same number written to another precision.
    Two sentences apart is where 15.0 years and 15 years used to meet.
    """
    read_in = {finding.key: index for index, finding in enumerate(_order(findings))}
    claim = sorted(findings, key=lambda f: (-f.severity, read_in[f.key]))

    said_measurements: set[str] = set()
    said_readings: set[str] = set()
    allowed: dict[str, frozenset[str]] = {}

    for finding in claim:
        names: set[str] = set()
        measurements: set[str] = set()
        readings: set[str] = set()
        for name, fact in finding.facts.items():
            reading = fact.reading()
            if fact.measurement in said_measurements or reading in said_readings:
                continue
            if any(_contradicts(reading, said) for said in said_readings):
                continue
            names.add(name)
            measurements.add(fact.measurement)
            readings.add(reading)
        allowed[finding.key] = frozenset(names)
        said_measurements |= measurements
        said_readings |= readings

    return allowed


def _fullest(surviving: Sequence[tuple[int, int]]) -> tuple[int, ...]:
    """The fullest forms available, widened until the choice is not a foregone one.

    `surviving` is (index, facts cited). Grouped by how much each form says
    and taken from the top, so a finding holding five measurements is offered
    the sentences that use five of them rather than the one that uses two.
    """
    by_size: dict[int, list[int]] = {}
    for index, size in surviving:
        by_size.setdefault(size, []).append(index)
    chosen: list[int] = []
    for size in sorted(by_size, reverse=True):
        if len(chosen) >= MIN_FORMS:
            break
        chosen.extend(by_size[size])
    return tuple(sorted(chosen))


def _settle(findings: Sequence[Finding]) -> dict[str, Proposition] | None:
    """Every finding with somewhere to stand, or None if one of them has none."""
    allowed = _allocate(findings)
    settled: dict[str, Proposition] = {}
    for finding in findings:
        surviving = [
            (index, len(cited))
            for index, cited in enumerate(_forms_available(finding.key))
            if cited <= allowed[finding.key] and _reads_clean(finding, cited)
        ]
        if not surviving:
            return None
        settled[finding.key] = Proposition(
            finding=finding,
            allowed=allowed[finding.key],
            forms=_fullest(surviving),
        )
    return settled


def _yields_to(
    chosen: Sequence[Finding], candidate: Finding
) -> tuple[list[Finding], dict[str, Proposition]] | None:
    """The course, with the mild lines that were silencing a sharper one removed.

    Protecting whatever was admitted first is right until the thing it is
    keeping out is worse than it is. Measured before this existed, the finish
    on two repositories held back that a fifth of the history is titled fix, a
    severity two finding, so that the opening line could go on naming the
    commit count. The card was quieter about a repository than the metrics
    justified, which is the one direction it may never be wrong in.

    Only findings strictly milder than the candidate may be turned out, and
    the mildest goes first, so a course never trades a sharp observation for a
    duller one. None when no eviction lets the candidate in, and the course
    keeps what it had.
    """
    milder = sorted(
        (f for f in chosen if f.severity < candidate.severity),
        key=lambda f: (f.severity, f.key),
    )
    kept = list(chosen)
    for evicted in milder:
        kept = [f for f in kept if f.key != evicted.key]
        trial = [*kept, candidate]
        settled = _settle(trial)
        if settled is not None:
            return trial, settled
    return None


def _compose_course(findings: Sequence[Finding], ceiling: int) -> PlannedCourse | None:
    """Admit findings in reading order for as long as the course still reads.

    A candidate is admitted only if every finding already admitted survives
    beside it. That is what stops a late arrival taking a measurement the
    opening line was relying on and leaving it mute: if the course cannot hold
    both, it keeps the one it already had, unless what it already had is
    milder than what it is refusing.
    """
    chosen: list[Finding] = []
    propositions: dict[str, Proposition] = {}
    for candidate in _order(findings):
        if len(chosen) >= ceiling:
            break
        trial: list[Finding] = [*chosen, candidate]
        settled = _settle(trial)
        if settled is None:
            yielded = _yields_to(chosen, candidate)
            if yielded is None:
                continue
            trial, settled = yielded
        chosen = trial
        propositions = settled

    if not chosen:
        return None
    return PlannedCourse(
        name=findings[0].course,
        propositions=tuple(propositions[finding.key] for finding in chosen),
    )


def compose(metrics: RepoMetrics, judgement: Judgement) -> Plan:
    """Group, deduplicate, and budget. Nothing here is written down yet."""
    by_course: dict[str, list[Finding]] = {course: [] for course in COURSES}
    for finding in judgement.findings:
        if finding.course in by_course:
            by_course[finding.course].append(finding)

    wanted = EMPTY_COURSES if metrics.is_empty else COURSES
    ceiling = MAX_LINES_WHEN_EMPTY if metrics.is_empty else MAX_LINES_PER_COURSE

    courses: list[PlannedCourse] = []
    for course in wanted:
        findings = by_course[course]
        if not findings:
            continue
        planned = _compose_course(findings, ceiling)
        if planned is not None:
            courses.append(planned)

    return Plan(
        repo_name=metrics.name,
        courses=tuple(courses),
        verdict=Verdict(
            score=judgement.score,
            band_label=judgement.band_label,
            scored_dimensions=judgement.scored_dimensions,
            total_dimensions=judgement.total_dimensions,
            refusal=judgement.refusal,
            refusal_facts=judgement.refusal_facts,
        ),
        footnotes=tuple(
            Footnote(name=dropped.name, reason=dropped.reason)
            for dropped in metrics.dropped
        ),
    )
