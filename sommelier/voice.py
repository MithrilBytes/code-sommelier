"""Findings in, lines out.

This module selects material from the cellar and arranges it into courses. It
holds no thresholds, measures nothing, and contains no material of its own.
Every string a reader ever sees comes from lines.py.

Selection is seeded on the repository name, so the same repository always
receives the same tasting. A professional does not revise his verdict when
asked twice.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from sommelier.collect import RepoMetrics
from sommelier.judge import COURSES, Finding, Judgement
from sommelier.lines import (
    CELLAR,
    FOOTNOTE_DROPPED,
    FOOTNOTE_INVENTORY,
    PAIRINGS,
    REFUSALS,
    VERDICTS,
)

COURSE_TITLES: dict[str, str] = {
    "label": "The label",
    "vintage": "Vintage",
    "nose": "Nose",
    "palate": "Palate",
    "structure": "Structure",
    "finish": "Finish",
}

# The line that opens a course, before anything sorted by severity. Without
# this the identity line lands last, because it is the least alarming thing
# judge has to say.
OPENING_KEYS: frozenset[str] = frozenset(
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

MAX_LINES_PER_COURSE: int = 3

# Nothing to measure gets a short tasting of the void rather than six courses
# of absence. There is no point describing the palate of an empty glass.
EMPTY_COURSES: tuple[str, ...] = ("label", "vintage", "finish")
MAX_LINES_WHEN_EMPTY: int = 1


@dataclass(frozen=True)
class Course:
    name: str
    body: str


@dataclass(frozen=True)
class TastingCard:
    repo_name: str
    tasting_number: int
    courses: tuple[Course, ...]
    verdict: str
    pairing: str

    score: int | None
    """None when the repository was refused a number. The verdict says why."""

    footnotes: tuple[str, ...]


def stable_seed(name: str) -> int:
    """Seed derived from the repository name.

    crc32 rather than hash(), which is salted per process and would make the
    tool disagree with itself between runs.
    """
    return zlib.crc32(name.encode("utf-8"))


def _order(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    return tuple(
        sorted(findings, key=lambda f: (f.key not in OPENING_KEYS, -f.severity, f.key))
    )


def _pick(base: int, site: str, count: int) -> int:
    """Choose an index for one named draw site, independently of every other.

    A single RNG stream makes every choice depend on how many choices came
    before it, so removing one finding shifts the template of every finding
    after it and the verdict as well. Measured on a real card, dropping one
    Finish finding moved 9 of 24 lines. Keying each draw on a stable site name
    means a diff shows the thing that changed and nothing else.
    """
    if count <= 1:
        return 0
    return zlib.crc32(site.encode("utf-8"), base) % count


def _speak(finding: Finding, base: int) -> str | None:
    templates = CELLAR.get(finding.key)
    if not templates:
        return None
    template = templates[_pick(base, f"cellar:{finding.key}", len(templates))]
    try:
        return template.format(**finding.facts)
    except (KeyError, IndexError):
        # A template citing a fact its key does not provide. test_style.py
        # fails the build on this, so it cannot reach a release, but the
        # sommelier still finishes the tasting rather than dropping the glass.
        return None


def _verdict(judgement: Judgement, base: int) -> str:
    """The closing line: the band and the denominator, or the refusal.

    A judgement with no score is not given a number wrapped in an apology. It
    draws from a different set of lines that states what was missing, so the
    card can be read without the reader ever inferring a score that was never
    computed.
    """
    if judgement.refusal is not None:
        templates = REFUSALS.get(judgement.refusal)
        if templates:
            site = f"refusal:{judgement.refusal}"
            template = templates[_pick(base, site, len(templates))]
            try:
                return template.format(**judgement.refusal_facts)
            except (KeyError, IndexError):
                # Same contract as _speak: the style gate fails the build on a
                # template citing a fact its code does not carry, and the
                # sommelier still finishes the tasting if one reaches a reader.
                pass
        return REFUSALS["no_source_files"][0].format(
            name=judgement.refusal_facts.get("name", ""),
            total_files=judgement.refusal_facts.get("total_files", "0"),
        )

    template = VERDICTS[_pick(base, "verdict", len(VERDICTS))]
    return template.format(
        score=judgement.score,
        band=judgement.band_label,
        scored=judgement.scored_dimensions,
        total=judgement.total_dimensions,
    )


def pour(
    metrics: RepoMetrics, judgement: Judgement, *, seed: int | None = None
) -> TastingCard:
    base = seed if seed is not None else stable_seed(metrics.name)
    tasting_number = 1 + _pick(base, "tasting-number", 99)

    by_course: dict[str, list[Finding]] = {course: [] for course in COURSES}
    for finding in judgement.findings:
        if finding.course in by_course:
            by_course[finding.course].append(finding)

    wanted = EMPTY_COURSES if metrics.is_empty else COURSES
    ceiling = MAX_LINES_WHEN_EMPTY if metrics.is_empty else MAX_LINES_PER_COURSE

    courses: list[Course] = []
    for course in wanted:
        sentences: list[str] = []
        for finding in _order(tuple(by_course[course])):
            if len(sentences) >= ceiling:
                break
            spoken = _speak(finding, base)
            if spoken:
                sentences.append(spoken)
        if sentences:
            courses.append(Course(name=COURSE_TITLES[course], body=" ".join(sentences)))

    verdict = _verdict(judgement, base)
    pairing = PAIRINGS[_pick(base, "pairing", len(PAIRINGS))]
    footnotes = tuple(
        FOOTNOTE_INVENTORY
        if dropped.name == "inventory"
        else FOOTNOTE_DROPPED.format(name=dropped.name, reason=dropped.reason)
        for dropped in metrics.dropped
    )

    return TastingCard(
        repo_name=metrics.name,
        tasting_number=tasting_number,
        courses=tuple(courses),
        verdict=verdict,
        pairing=pairing,
        score=judgement.score,
        footnotes=footnotes,
    )
