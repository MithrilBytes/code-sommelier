"""A plan in, lines out.

This module writes down what plan.py has already decided. It holds no
thresholds, measures nothing, chooses no content, and contains no material of
its own. Every string a reader ever sees comes from lines.py.

The one decision left here is which form a proposition takes, drawn from the
forms the plan left standing. That draw is seeded on the repository name, so
the same repository always receives the same tasting. A professional does not
revise his verdict when asked twice.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from sommelier.lines import (
    CELLAR,
    FOOTNOTE_DROPPED,
    FOOTNOTE_INVENTORY,
    PAIRINGS,
    REFUSALS,
    VERDICTS,
)
from sommelier.plan import Plan, Proposition, Verdict

COURSE_TITLES: dict[str, str] = {
    "label": "The label",
    "vintage": "Vintage",
    "nose": "Nose",
    "palate": "Palate",
    "structure": "Structure",
    "finish": "Finish",
}


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


def _speak(proposition: Proposition, base: int) -> str | None:
    """One proposition, in one of the forms the plan left standing."""
    finding = proposition.finding
    templates = CELLAR.get(finding.key)
    if not templates:
        return None
    forms = tuple(index for index in proposition.forms if index < len(templates))
    if not forms:
        return None
    template = templates[forms[_pick(base, f"cellar:{finding.key}", len(forms))]]
    try:
        return template.format(
            **{name: fact.written() for name, fact in finding.facts.items()}
        )
    except (KeyError, IndexError):
        # A template citing a fact its key does not provide. test_style.py
        # fails the build on this, so it cannot reach a release, but the
        # sommelier still finishes the tasting rather than dropping the glass.
        return None


def _verdict(verdict: Verdict, base: int) -> str:
    """The closing line: the band and the denominator, or the refusal.

    A judgement with no score is not given a number wrapped in an apology. It
    draws from a different set of lines that states what was missing, so the
    card can be read without the reader ever inferring a score that was never
    computed.
    """
    if verdict.refusal is not None:
        templates = REFUSALS.get(verdict.refusal)
        if templates:
            site = f"refusal:{verdict.refusal}"
            template = templates[_pick(base, site, len(templates))]
            try:
                return template.format(**verdict.refusal_facts)
            except (KeyError, IndexError):
                # Same contract as _speak: the style gate fails the build on a
                # template citing a fact its code does not carry, and the
                # sommelier still finishes the tasting if one reaches a reader.
                pass
        return REFUSALS["no_source_files"][0].format(
            name=verdict.refusal_facts.get("name", ""),
            total_files=verdict.refusal_facts.get("total_files", "0"),
        )

    template = VERDICTS[_pick(base, "verdict", len(VERDICTS))]
    return template.format(
        score=verdict.score,
        band=verdict.band_label,
        scored=verdict.scored_dimensions,
        total=verdict.total_dimensions,
    )


def pour(plan: Plan, *, seed: int | None = None) -> TastingCard:
    base = seed if seed is not None else stable_seed(plan.repo_name)
    tasting_number = 1 + _pick(base, "tasting-number", 99)

    courses: list[Course] = []
    for planned in plan.courses:
        sentences = [
            spoken
            for spoken in (
                _speak(proposition, base) for proposition in planned.propositions
            )
            if spoken
        ]
        if sentences:
            courses.append(
                Course(name=COURSE_TITLES[planned.name], body=" ".join(sentences))
            )

    footnotes = tuple(
        FOOTNOTE_INVENTORY
        if footnote.name == "inventory"
        else FOOTNOTE_DROPPED.format(name=footnote.name, reason=footnote.reason)
        for footnote in plan.footnotes
    )

    return TastingCard(
        repo_name=plan.repo_name,
        tasting_number=tasting_number,
        courses=tuple(courses),
        verdict=_verdict(plan.verdict, base),
        pairing=PAIRINGS[_pick(base, "pairing", len(PAIRINGS))],
        score=plan.verdict.score,
        footnotes=footnotes,
    )
