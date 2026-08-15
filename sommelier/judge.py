"""Threshold judging.

Consumes a RepoMetrics record and returns a Judgement. Every numeric threshold
this module applies lives in BANDS and is read back from there, so the bands can
be retuned in one place. This module emits no reader facing prose: findings
carry pre-formatted fact strings that lines.py templates substitute.

The score has three layers, in this order.

**Refusal.** A repository the tool cannot read is not given a number. No source
files, or a language attribution below the floor, or too few dimensions
measured, and judge returns score None with a refusal code. The alternative is
what the previous model did: rank a directory of templates above a text editor
because every dimension it could not measure counted as clean.

**Gates.** Above 90 the tool switches from deduction to positive evidence. A
repository enters the outstanding band by satisfying every base gate, and the
exemplary band by satisfying the care gates on top. Gates are conjunctive and
they default to failed: not measured is never passed. That is what makes
withholding information cost a band rather than remove a penalty.

Withholding arrives by two doors and both are watched here. Coverage records a
measurement that could not be taken. The dropped list records an analyzer that
started and did not finish, which is the same gap wearing working clothes: its
counts are a floor and its zeros are absence. Every dimension an unfinished
analyzer feeds leaves the denominator, and every gate that reads one fails.

**Deduction.** Below 90 the score is the band ceiling less the mean deduction
across the dimensions that were measured, renormalised over that denominator
and reported with it. Every unmeasured dimension adds a fixed weight to the
deduction, which is what keeps renormalisation from paying.

That last weight is not a taste. Removing one dimension from a measured set of
n can raise the renormalised mean by at most 1/n of the span, so a coverage
weight above 1/n plus one point of rounding slack makes the reported score
monotone: withholding a measurement can lower a score and can never raise one.
With the minimum scoreable denominator at four, n is never below five, and
score_coverage_weight is set above that bound with room to spare.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType
from typing import Final, cast

from sommelier.collect import (
    Coverage,
    DependencyManifest,
    GitMetrics,
    RepoMetrics,
    SedimentItem,
)

COURSES: Final[tuple[str, ...]] = (
    "label",
    "vintage",
    "nose",
    "palate",
    "structure",
    "finish",
)

# The axes the score is computed over. A dimension whose inputs were not
# measured is dropped from the denominator, and the denominator is printed.
DIMENSIONS: Final[tuple[str, ...]] = (
    "documentation",
    "hygiene",
    "testing",
    "structure",
    "body",
    "markers",
    "history",
    "authorship",
)

# The conditions that admit a repository to the outstanding band. Every one of
# them costs the author real effort, and every one of them fails when the
# evidence is absent rather than passing by default.
BASE_GATES: Final[tuple[str, ...]] = (
    "documented",
    "tested",
    "hygiene",
    "dependencies",
    "history",
    "authorship",
    "cadence",
)

# Sustained care, on top of every base gate, for the exemplary band.
CARE_GATES: Final[tuple[str, ...]] = (
    "continuous_integration",
    "contributing",
    "reference_documentation",
    "active",
    "locked",
    "craft",
    "complete_coverage",
)

# What each analyzer feeds. An analyzer that stopped at the budget did not
# measure a smaller repository, it measured less of this one, so its counts
# are a floor and its zeros are absence rather than a clean result. Every
# dimension it feeds leaves the denominator. Without this the cheapest route
# to the top band is a run too short to find anything: a walk that stops
# before the committed key reports no secrets, and a log that stops before
# the dormancy reports a lively project.
#
# The inventory analyzer is deliberately absent. It is dropped when git
# cannot say which files are tracked, which names a different file set rather
# than a shorter one, and every dimension is measured over the set that was
# used.
ANALYZER_DIMENSIONS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "tree": (
            "documentation",
            "hygiene",
            "testing",
            "structure",
            "body",
            "markers",
        ),
        "git": ("history", "authorship"),
        "palate": ("body",),
        "abandonment": ("markers",),
    }
)

# Which analyzers each gate reads. A gate is positive evidence, and evidence
# an analyzer never reached is not evidence, so an unfinished analyzer fails
# every gate that rests on it.
GATE_ANALYZERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "documented": ("tree",),
        "tested": ("tree",),
        "hygiene": ("tree",),
        "dependencies": ("tree",),
        "history": ("git",),
        "authorship": ("git",),
        "cadence": ("git",),
        "continuous_integration": ("tree",),
        "contributing": ("tree",),
        "reference_documentation": ("tree",),
        "active": ("git",),
        "locked": ("tree",),
        # Both read every dimension, so the dimensions carry the drop for them.
        "craft": (),
        "complete_coverage": (),
    }
)

# The two bands the gates hand out directly, named here so a rename in the
# BANDS table cannot leave the gate logic pointing at nothing.
EXEMPLARY: Final[str] = "exemplary"
OUTSTANDING: Final[str] = "outstanding"

# Why a repository was refused a number. Each code needs its own lines in the
# cellar, on the same rule as every finding key.
REFUSALS: Final[tuple[str, ...]] = (
    "no_source_files",
    "unattributed",
    "too_few_dimensions",
    "unreadable",
)

REFUSAL_FACTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "no_source_files": ("name", "total_files"),
        "unattributed": ("name", "source_files", "attributed", "percent", "floor"),
        "too_few_dimensions": ("name", "scored", "total", "minimum"),
        "unreadable": ("name", "total_files"),
    }
)

BANDS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "todo_per_kloc_clean": 0.0,
        "todo_per_kloc_notes": 5.0,
        "todo_per_kloc_aggressive": 20.0,
        "largest_file_full_bodied": 300,
        "largest_file_cry_for_help": 800,
        "fix_ratio_high": 0.30,
        "gap_days_silence": 180,
        "bus_factor_share": 0.90,
        "bus_factor_min_commits": 10,
        # ecosystem -> (tannic above, opaque above); javascript is graded on a curve
        "dependency_counts": {
            "javascript": (40, 100),
            "python": (25, 60),
            "go": (20, 50),
            "rust": (20, 50),
        },
        "indent_depth_deep": 6,
        "indent_depth_abyssal": 9,
        # The other end of the same axis. A source tree that never indents at
        # all is not a program, whatever the extensions say.
        "indent_depth_flat": 0,
        "flat_min_source_files": 25,
        "function_lines_long": 100,
        "readme_lines_thin": 10,
        # The excess end of the documentation axis. Not a defect, and worth
        # saying, which is why it carries severity zero.
        "readme_lines_exhaustive": 300,
        "debug_prints_notable": 5,
        # The deficient end of the body axis: a repository shattered into
        # fragments reads no better than one poured into a single file.
        "average_lines_thin": 20.0,
        "thin_min_source_files": 25,
        # The deficient end of the dependency axis. Only asked of a repository
        # large enough that declaring nothing is a claim rather than a fact.
        "austere_min_source_files": 50,
        # The excess end of the authorship axis, against single_estate.
        "authors_per_kloc_crowded": 100.0,
        "vintage_aged_years": 5.0,
        "vintage_recent_days": 90,
        "dormant_days": 365,
        "polyglot_min_languages": 4,
        "polyglot_min_share": 0.05,
        "monoculture_share": 0.95,
        "fix_subject_pattern": r"\bfix(e[sd])?\b",
        # --- the score ---------------------------------------------------
        # Non-uniform widths, narrower at the top, so scarcity is a property
        # of the geometry. name, low, high, label.
        "score_bands": (
            ("exemplary", 96, 100, "Exemplary"),
            ("outstanding", 90, 95, "Outstanding"),
            ("sound", 80, 89, "Sound"),
            ("average", 70, 79, "Average"),
            ("below_average", 60, 69, "Below average"),
            ("unacceptable", 50, 59, "Unacceptable"),
        ),
        "score_unscoreable_band": ("unscoreable", "No score"),
        # The severity sum at which a dimension is fully spent. Reaching the
        # cap deducts the whole dimension and no further finding can deepen it.
        "dimension_caps": {
            "documentation": 3,
            "hygiene": 8,
            "testing": 2,
            "structure": 5,
            "body": 6,
            "markers": 2,
            "history": 5,
            "authorship": 2,
        },
        # What one unmeasured dimension adds to the deduction. Above 1/n plus
        # rounding slack for the smallest scoreable denominator, which is the
        # bound that makes withholding a measurement unable to raise a score.
        "score_coverage_weight": 0.25,
        "score_deduction_ceiling": 89,
        "score_deduction_floor": 50,
        "score_deduction_span": 39,
        "score_gated_span": 20,
        "score_exemplary_span": 16,
        # The most any one dimension may be spent and still be called
        # exemplary. Read by the craft gate.
        "exemplary_max_dimension_deduction": 0.25,
        "unscoreable_min_dimensions": 4,
        "unscoreable_attribution_share": 0.50,
        "gate_readme_lines": 20,
        "gate_readme_lines_exemplary": 100,
        "gate_min_authors": 2,
    }
)

_NO_FACTS: Final[Mapping[str, str]] = MappingProxyType({})

_UNKNOWN: Final[str] = "unknown"
_DAYS_PER_YEAR: Final[float] = 365.25
_LINES_PER_KLOC: Final[float] = 1000.0
_BYTES_PER_MEGABYTE: Final[int] = 1024 * 1024


def _band_int(name: str) -> int:
    return cast(int, BANDS[name])


def _band_float(name: str) -> float:
    return cast(float, BANDS[name])


def _band_str(name: str) -> str:
    return cast(str, BANDS[name])


def _dependency_band(ecosystem: str) -> tuple[int, int] | None:
    table = cast(Mapping[str, tuple[int, int]], BANDS["dependency_counts"])
    return table.get(ecosystem)


def _score_bands() -> tuple[tuple[str, int, int, str], ...]:
    return cast(tuple[tuple[str, int, int, str], ...], BANDS["score_bands"])


def _dimension_cap(name: str) -> int:
    table = cast(Mapping[str, int], BANDS["dimension_caps"])
    return table.get(name, 0)


def _unscoreable_band() -> tuple[str, str]:
    return cast(tuple[str, str], BANDS["score_unscoreable_band"])


_FIX_SUBJECT_RE: Final[re.Pattern[str]] = re.compile(
    _band_str("fix_subject_pattern"), re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    key: str
    course: str
    severity: int
    facts: Mapping[str, str]


@dataclass(frozen=True)
class Dimension:
    """One axis of the score, and whether it reached the judge at all."""

    name: str

    measured: bool
    """False when the inputs were not measured. Excluded from the denominator."""

    severity: int
    """The severity carried by the findings assigned to this dimension."""

    cap: int
    """The severity at which the dimension is fully spent."""

    deduction: float
    """severity over cap, clamped to one. Zero for an unmeasured dimension."""


@dataclass(frozen=True)
class Gate:
    """One published, checkable condition of entry to a band."""

    name: str
    passed: bool


@dataclass(frozen=True)
class Judgement:
    findings: tuple[Finding, ...]

    score: int | None
    """None when the repository was refused a number. See refusal."""

    total_severity: int
    band: str
    band_label: str
    dimensions: tuple[Dimension, ...]
    scored_dimensions: int
    total_dimensions: int
    gates: tuple[Gate, ...]
    care_gates: tuple[Gate, ...]

    refusal: str | None = None
    """The reason there is no score, as a code the cellar has lines for."""

    # default_factory, not a bare default: Python 3.11 rejects mappingproxy as
    # a dataclass default and 3.12 accepts it, so the bare form imports fine
    # here and explodes on the version the project claims to support.
    refusal_facts: Mapping[str, str] = field(default_factory=lambda: _NO_FACTS)


@dataclass(frozen=True)
class _Spec:
    course: str
    dimension: str
    severity: int
    facts: tuple[str, ...]


_MARKER_FACTS: Final[tuple[str, ...]] = (
    "total",
    "per_kloc",
    "todo",
    "fixme",
    "hack",
    "xxx",
    "worst_path",
    "worst_count",
    "debug_prints",
)

_DEPENDENCY_FACTS: Final[tuple[str, ...]] = (
    "ecosystem",
    "declared",
    "dev",
    "manifest_path",
    "threshold",
)

_FILE_SIZE_FACTS: Final[tuple[str, ...]] = ("path", "lines", "average_lines")

# The single registry of what judge can say: course, scoring dimension,
# severity and the exact set of facts each finding guarantees. ALL_KEYS and
# KEY_FACTS derive from it, and so does every dimension's severity total. The
# course is where a finding is spoken; the dimension is where it is counted,
# and the two are different questions.
_SPECS: Final[Mapping[str, _Spec]] = MappingProxyType(
    {
        "label.identity": _Spec(
            "label",
            "body",
            0,
            ("name", "language", "file_count", "source_file_count", "total_lines"),
        ),
        "label.vendored": _Spec(
            "label",
            "hygiene",
            3,
            (
                "vendored_files",
                "vendored_dirs",
                "total_files",
                "vendored_share",
                "dirs_phrase",
            ),
        ),
        "label.secrets": _Spec("label", "hygiene", 3, ("secret_files", "path")),
        "label.os_cruft": _Spec("label", "hygiene", 1, ("cruft_files", "path")),
        "label.large_binary": _Spec(
            "label", "hygiene", 2, ("binary_count", "largest_path", "largest_mb")
        ),
        "label.polyglot": _Spec(
            "label",
            "structure",
            1,
            ("language_count", "languages", "primary", "primary_share"),
        ),
        "label.monoculture": _Spec(
            "label", "structure", 0, ("language", "share", "file_count")
        ),
        "vintage.no_history": _Spec("vintage", "history", 2, ("name", "file_count")),
        "vintage.empty": _Spec("vintage", "history", 2, ("name", "file_count")),
        "vintage.declared": _Spec(
            "vintage",
            "history",
            0,
            (
                "first_year",
                "last_year",
                "first_date",
                "last_date",
                "years",
                "commit_count",
                "commits_phrase",
            ),
        ),
        "vintage.shallow": _Spec("vintage", "history", 0, ("commit_count",)),
        "vintage.aged": _Spec(
            "vintage",
            "history",
            0,
            ("first_year", "years", "first_date", "commit_count", "commits_phrase"),
        ),
        "vintage.recent": _Spec(
            "vintage",
            "history",
            0,
            ("days", "first_date", "commit_count", "commits_phrase"),
        ),
        "nose.no_readme": _Spec(
            "nose", "documentation", 2, ("name", "source_files", "total_lines")
        ),
        "nose.thin_readme": _Spec(
            "nose", "documentation", 1, ("readme_path", "readme_lines", "readme_bytes")
        ),
        "nose.exhaustive_readme": _Spec(
            "nose",
            "documentation",
            0,
            ("readme_path", "readme_lines", "readme_bytes", "source_files"),
        ),
        "nose.no_license": _Spec("nose", "documentation", 1, ("name",)),
        "nose.no_gitignore": _Spec("nose", "hygiene", 3, ("name", "total_files")),
        "nose.no_tests": _Spec(
            "nose", "testing", 2, ("source_files", "total_lines")
        ),
        "nose.documented": _Spec(
            "nose", "documentation", 0, ("readme_path", "readme_lines", "license_name")
        ),
        "nose.debug_prints": _Spec(
            "nose", "hygiene", 1, ("debug_prints", "source_files")
        ),
        "palate.full_bodied": _Spec("palate", "body", 1, _FILE_SIZE_FACTS),
        "palate.cry_for_help": _Spec("palate", "body", 3, _FILE_SIZE_FACTS),
        "palate.thin": _Spec(
            "palate", "body", 1, ("source_files", "average_lines", "total_lines")
        ),
        "palate.deep_nesting": _Spec("palate", "body", 2, ("depth", "path")),
        "palate.abyssal": _Spec("palate", "body", 3, ("depth", "path")),
        "palate.flat": _Spec(
            "palate",
            "body",
            1,
            ("source_files", "total_lines", "largest_path", "largest_lines"),
        ),
        "palate.long_function": _Spec("palate", "body", 2, ("name", "lines", "path")),
        "palate.sampled": _Spec("palate", "body", 0, ("scanned", "total")),
        "palate.empty": _Spec("palate", "body", 3, ("name", "total_files")),
        "palate.body": _Spec(
            "palate",
            "body",
            0,
            (
                "source_files",
                "average_lines",
                "largest_path",
                "largest_lines",
                "depth",
            ),
        ),
        "structure.tannic": _Spec("structure", "structure", 1, _DEPENDENCY_FACTS),
        "structure.opaque": _Spec("structure", "structure", 2, _DEPENDENCY_FACTS),
        "structure.austere": _Spec(
            "structure",
            "structure",
            0,
            ("ecosystem", "declared", "manifest_path", "source_files"),
        ),
        "structure.undeclared": _Spec(
            "structure", "structure", 1, ("name", "source_files")
        ),
        "structure.declared": _Spec(
            "structure",
            "structure",
            0,
            ("ecosystem", "declared", "dev", "manifest_path"),
        ),
        "structure.drift": _Spec(
            "structure",
            "structure",
            2,
            ("manifest_path", "lockfile_path", "reason", "declared", "locked"),
        ),
        "structure.no_lockfile": _Spec(
            "structure", "structure", 2, ("manifest_path", "ecosystem", "declared")
        ),
        "finish.fix_ratio": _Spec(
            "finish",
            "history",
            2,
            (
                "fix_commits",
                "commit_count",
                "fix_percent",
                "fixes_phrase",
                "commits_phrase",
            ),
        ),
        "finish.the_silence": _Spec(
            "finish", "history", 2, ("gap_days", "gap_start", "gap_end")
        ),
        "finish.single_estate": _Spec(
            "finish",
            "authorship",
            1,
            ("author", "author_commits", "share", "commit_count", "author_count"),
        ),
        "finish.crowded": _Spec(
            "finish",
            "authorship",
            1,
            ("author_count", "total_lines", "per_kloc", "commit_count", "authors_phrase"),
        ),
        "finish.abrupt": _Spec("finish", "history", 1, ("subject", "last_date")),
        "finish.dormant": _Spec(
            "finish", "history", 2, ("days", "years", "last_date")
        ),
        "finish.history": _Spec(
            "finish",
            "history",
            0,
            (
                "commit_count",
                "fix_commits",
                "fix_percent",
                "subject",
                "last_date",
                "author_count",
                "commits_phrase",
                "authors_phrase",
                "fixes_phrase",
            ),
        ),
        "finish.no_history": _Spec("finish", "history", 2, ("name", "file_count")),
        "finish.void": _Spec("finish", "history", 2, ("name", "file_count")),
        # Markers are a Nose finding: they are the first thing the reader
        # notices, not the aftertaste.
        "abandonment.suspiciously_clean": _Spec(
            "nose", "markers", 0, ("source_files", "total_lines", "debug_prints")
        ),
        "abandonment.notes": _Spec("nose", "markers", 1, _MARKER_FACTS),
        "abandonment.aggressive": _Spec("nose", "markers", 2, _MARKER_FACTS),
    }
)

ALL_KEYS: Final[tuple[str, ...]] = tuple(sorted(_SPECS))

KEY_FACTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {key: _SPECS[key].facts for key in ALL_KEYS}
)

KEY_DIMENSIONS: Final[Mapping[str, str]] = MappingProxyType(
    {key: _SPECS[key].dimension for key in ALL_KEYS}
)

_COURSE_ORDER: Final[Mapping[str, int]] = MappingProxyType(
    {name: index for index, name in enumerate(COURSES)}
)


def _number(value: int) -> str:
    return f"{value:,}"


def _decimal(value: float) -> str:
    return f"{value:.1f}"


def _phrase(count: int, singular: str, plural: str) -> str:
    """A count with its noun already agreed.

    One commit is not "1 commits". The sommelier is read aloud, so the
    agreement is settled here rather than left to the template.
    """
    return f"{_number(count)} {singular if count == 1 else plural}"


def _percent(share: float) -> str:
    if not math.isfinite(share):
        return _UNKNOWN
    return str(round(share * 100))


def _megabytes(size_bytes: int) -> str:
    return f"{size_bytes / _BYTES_PER_MEGABYTE:.1f}"


def _share(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return part / whole


def _text(value: str | None) -> str:
    if value is None:
        return _UNKNOWN
    stripped = value.strip()
    return stripped if stripped else _UNKNOWN


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _reference_date(git: GitMetrics) -> date | None:
    """Today, reconstructed from the metrics so judging stays a pure function."""
    last = _parse_date(git.last_commit_date)
    if last is None:
        return None
    try:
        return last + timedelta(days=git.days_since_last_commit)
    except OverflowError:
        return None


def _first_sediment(items: Sequence[SedimentItem], kind: str) -> SedimentItem | None:
    for item in items:
        if item.kind == kind:
            return item
    return None


def _dropped(metrics: RepoMetrics) -> frozenset[str]:
    """The analyzers that started and did not finish, by name."""
    return frozenset(item.name for item in metrics.dropped)


def _read(metrics: RepoMetrics, *analyzers: str) -> bool:
    """Whether every analyzer a course is read from ran to the end.

    A course whose analyzer stopped at the budget says nothing, rather than
    saying that it found nothing. The two are the same value and they are not
    the same statement: a walk that ended early reports no README, no tests
    and no secrets, and a log read that ended early reports no commits at all.
    Printed as findings those are confident falsehoods about a repository
    nobody finished reading, and the footnote already names the analyzer that
    stopped.
    """
    dropped = _dropped(metrics)
    return not any(name in dropped for name in analyzers)


def _finding(key: str, facts: Mapping[str, str]) -> Finding:
    spec = _SPECS[key]
    populated = {name: facts.get(name, _UNKNOWN) for name in spec.facts}
    return Finding(
        key=key,
        course=spec.course,
        severity=spec.severity,
        facts=MappingProxyType(populated),
    )


def _sort_key(finding: Finding) -> tuple[int, int, str]:
    return (
        _COURSE_ORDER.get(finding.course, len(COURSES)),
        -finding.severity,
        finding.key,
    )


def _judge_label(metrics: RepoMetrics) -> list[Finding]:
    # The counts below come from the walk, the line total from the scan.
    if not _read(metrics, "tree", "palate"):
        return []
    palate = metrics.palate
    terroir = metrics.terroir
    sediment = metrics.sediment
    findings: list[Finding] = [
        _finding(
            "label.identity",
            {
                "name": metrics.name,
                "language": _text(terroir.primary_language),
                "file_count": _number(palate.total_file_count),
                "source_file_count": _number(palate.source_file_count),
                "total_lines": _number(palate.total_lines),
            },
        )
    ]

    if sediment.vendored_file_count > 0:
        findings.append(
            _finding(
                "label.vendored",
                {
                    "vendored_files": _number(sediment.vendored_file_count),
                    "vendored_dirs": _number(sediment.vendored_dir_count),
                    "total_files": _number(palate.total_file_count),
                    "dirs_phrase": _phrase(
                        sediment.vendored_dir_count, "directory", "directories"
                    ),
                    "vendored_share": _percent(
                        _share(sediment.vendored_file_count, palate.total_file_count)
                    ),
                },
            )
        )

    if sediment.secret_file_count > 0:
        secret = _first_sediment(sediment.items, "secret")
        findings.append(
            _finding(
                "label.secrets",
                {
                    "secret_files": _number(sediment.secret_file_count),
                    "path": _text(secret.path if secret is not None else None),
                },
            )
        )

    if sediment.os_cruft_count > 0:
        cruft = _first_sediment(sediment.items, "os_cruft")
        findings.append(
            _finding(
                "label.os_cruft",
                {
                    "cruft_files": _number(sediment.os_cruft_count),
                    "path": _text(cruft.path if cruft is not None else None),
                },
            )
        )

    if sediment.large_binary_count > 0:
        findings.append(
            _finding(
                "label.large_binary",
                {
                    "binary_count": _number(sediment.large_binary_count),
                    "largest_path": _text(sediment.largest_binary_path),
                    "largest_mb": _megabytes(sediment.largest_binary_bytes),
                },
            )
        )

    languages = terroir.languages
    if languages:
        floor = _band_float("polyglot_min_share")
        significant = [lang for lang in languages if lang.share >= floor]
        if len(significant) >= _band_int("polyglot_min_languages"):
            primary = next(
                (
                    lang
                    for lang in languages
                    if lang.name == terroir.primary_language
                ),
                languages[0],
            )
            findings.append(
                _finding(
                    "label.polyglot",
                    {
                        "language_count": _number(len(significant)),
                        "languages": ", ".join(lang.name for lang in significant),
                        "primary": primary.name,
                        "primary_share": _percent(primary.share),
                    },
                )
            )
        top = languages[0]
        if top.share > _band_float("monoculture_share"):
            findings.append(
                _finding(
                    "label.monoculture",
                    {
                        "language": top.name,
                        "share": _percent(top.share),
                        "file_count": _number(top.file_count),
                    },
                )
            )

    return findings


def _judge_vintage(metrics: RepoMetrics) -> list[Finding]:
    if not _read(metrics, "git"):
        return []
    git = metrics.git
    identity = {
        "name": metrics.name,
        "file_count": _number(metrics.palate.total_file_count),
    }
    if not git.is_repo:
        return [_finding("vintage.no_history", identity)]
    if not git.has_commits:
        return [_finding("vintage.empty", identity)]

    findings: list[Finding] = []
    if git.shallow:
        findings.append(
            _finding("vintage.shallow", {"commit_count": _number(git.commit_count)})
        )

    reference = _reference_date(git)
    first = _parse_date(git.first_commit_date)
    last = _parse_date(git.last_commit_date)
    if first is not None and last is not None:
        span_years = (last - first).days / _DAYS_PER_YEAR
        findings.append(
            _finding(
                "vintage.declared",
                {
                    "first_year": str(first.year),
                    "last_year": str(last.year),
                    "first_date": _text(git.first_commit_date),
                    "last_date": _text(git.last_commit_date),
                    "years": _decimal(max(span_years, 0.0)),
                    "commit_count": _number(git.commit_count),
                    "commits_phrase": _phrase(
                        git.commit_count, "commit", "commits"
                    ),
                },
            )
        )

    if reference is None or first is None:
        return findings

    age_days = (reference - first).days
    age_years = age_days / _DAYS_PER_YEAR
    first_year = (
        str(git.first_commit_year) if git.first_commit_year is not None else str(first.year)
    )
    if age_years >= _band_float("vintage_aged_years"):
        findings.append(
            _finding(
                "vintage.aged",
                {
                    "first_year": first_year,
                    "years": _number(int(age_years)),
                    "first_date": _text(git.first_commit_date),
                    "commit_count": _number(git.commit_count),
                    "commits_phrase": _phrase(
                        git.commit_count, "commit", "commits"
                    ),
                },
            )
        )
    elif age_days < _band_int("vintage_recent_days"):
        findings.append(
            _finding(
                "vintage.recent",
                {
                    "days": _number(max(age_days, 0)),
                    "first_date": _text(git.first_commit_date),
                    "commit_count": _number(git.commit_count),
                    "commits_phrase": _phrase(
                        git.commit_count, "commit", "commits"
                    ),
                },
            )
        )
    return findings


def _judge_nose(metrics: RepoMetrics) -> list[Finding]:
    if not _read(metrics, "tree"):
        return []
    nose = metrics.nose
    palate = metrics.palate
    findings: list[Finding] = []

    if nose.readme_path is None:
        findings.append(
            _finding(
                "nose.no_readme",
                {
                    "name": metrics.name,
                    "source_files": _number(palate.source_file_count),
                    "total_lines": _number(palate.total_lines),
                },
            )
        )
    elif nose.readme_lines < _band_int("readme_lines_thin"):
        findings.append(
            _finding(
                "nose.thin_readme",
                {
                    "readme_path": _text(nose.readme_path),
                    "readme_lines": _number(nose.readme_lines),
                    "readme_bytes": _number(nose.readme_bytes),
                },
            )
        )

    if nose.license_path is None:
        findings.append(_finding("nose.no_license", {"name": metrics.name}))

    if nose.gitignore_path is None:
        findings.append(
            _finding(
                "nose.no_gitignore",
                {
                    "name": metrics.name,
                    "total_files": _number(palate.total_file_count),
                },
            )
        )

    if not nose.has_tests:
        findings.append(
            _finding(
                "nose.no_tests",
                {
                    "source_files": _number(palate.source_file_count),
                    "total_lines": _number(palate.total_lines),
                },
            )
        )

    if metrics.abandonment.debug_print_count >= _band_int("debug_prints_notable"):
        findings.append(
            _finding(
                "nose.debug_prints",
                {
                    "debug_prints": _number(metrics.abandonment.debug_print_count),
                    "source_files": _number(palate.source_file_count),
                },
            )
        )

    # Said only when there is nothing else to say about the paperwork, so the
    # course is never silent on a repository that did everything right. The
    # documentation axis is banded at both ends: too little is a defect, and
    # a README past the exhaustive floor is a fact worth stating, which is why
    # it is severity zero and takes the same slot.
    if not findings and nose.readme_path is not None:
        if nose.readme_lines >= _band_int("readme_lines_exhaustive"):
            findings.append(
                _finding(
                    "nose.exhaustive_readme",
                    {
                        "readme_path": _text(nose.readme_path),
                        "readme_lines": _number(nose.readme_lines),
                        "readme_bytes": _number(nose.readme_bytes),
                        "source_files": _number(palate.source_file_count),
                    },
                )
            )
        else:
            findings.append(
                _finding(
                    "nose.documented",
                    {
                        "readme_path": _text(nose.readme_path),
                        "readme_lines": _number(nose.readme_lines),
                        "license_name": _text(nose.license_name),
                    },
                )
            )

    return findings


def _judge_palate(metrics: RepoMetrics) -> list[Finding]:
    if not _read(metrics, "tree", "palate"):
        return []
    palate = metrics.palate
    findings: list[Finding] = []

    if palate.source_file_count <= 0:
        findings.append(
            _finding(
                "palate.empty",
                {
                    "name": metrics.name,
                    "total_files": _number(palate.total_file_count),
                },
            )
        )
    else:
        findings.append(
            _finding(
                "palate.body",
                {
                    "source_files": _number(palate.source_file_count),
                    "average_lines": _decimal(palate.average_lines),
                    "largest_path": _text(palate.largest_file_path),
                    "largest_lines": _number(palate.largest_file_lines),
                    "depth": _number(palate.max_indent_depth),
                },
            )
        )
        size_facts = {
            "path": _text(palate.largest_file_path),
            "lines": _number(palate.largest_file_lines),
            "average_lines": _decimal(palate.average_lines),
        }
        if palate.largest_file_lines > _band_int("largest_file_cry_for_help"):
            findings.append(_finding("palate.cry_for_help", size_facts))
        elif palate.largest_file_lines >= _band_int("largest_file_full_bodied"):
            findings.append(_finding("palate.full_bodied", size_facts))

        # The deficient end of the same axis. Asked only of a repository with
        # enough files that the average means something.
        if palate.source_file_count >= _band_int(
            "thin_min_source_files"
        ) and palate.average_lines < _band_float("average_lines_thin"):
            findings.append(
                _finding(
                    "palate.thin",
                    {
                        "source_files": _number(palate.source_file_count),
                        "average_lines": _decimal(palate.average_lines),
                        "total_lines": _number(palate.total_lines),
                    },
                )
            )

        nesting_facts = {
            "depth": _number(palate.max_indent_depth),
            "path": _text(palate.max_indent_path),
        }
        if palate.max_indent_depth >= _band_int("indent_depth_abyssal"):
            findings.append(_finding("palate.abyssal", nesting_facts))
        elif palate.max_indent_depth >= _band_int("indent_depth_deep"):
            findings.append(_finding("palate.deep_nesting", nesting_facts))
        elif palate.source_file_count >= _band_int(
            "flat_min_source_files"
        ) and palate.max_indent_depth <= _band_int("indent_depth_flat"):
            # No indentation anywhere across a large source set. The other end
            # of the nesting axis, and the one that says this is data.
            findings.append(
                _finding(
                    "palate.flat",
                    {
                        "source_files": _number(palate.source_file_count),
                        "total_lines": _number(palate.total_lines),
                        "largest_path": _text(palate.largest_file_path),
                        "largest_lines": _number(palate.largest_file_lines),
                    },
                )
            )

        if palate.longest_function_lines > _band_int("function_lines_long"):
            findings.append(
                _finding(
                    "palate.long_function",
                    {
                        "name": _text(palate.longest_function_name),
                        "lines": _number(palate.longest_function_lines),
                        "path": _text(palate.longest_function_path),
                    },
                )
            )

    if palate.sampled:
        findings.append(
            _finding(
                "palate.sampled",
                {
                    "scanned": _number(palate.scanned_file_count),
                    "total": _number(palate.source_file_count),
                },
            )
        )

    return findings


def _dependency_facts(manifest: DependencyManifest, threshold: int) -> dict[str, str]:
    return {
        "ecosystem": manifest.ecosystem,
        "declared": _number(manifest.declared_count),
        "dev": _number(manifest.dev_count),
        "manifest_path": _text(manifest.manifest_path),
        "threshold": _number(threshold),
    }


def _judge_structure(metrics: RepoMetrics) -> list[Finding]:
    if not _read(metrics, "tree"):
        return []
    structure = metrics.structure
    findings: list[Finding] = []

    if structure.undeclared:
        findings.append(
            _finding(
                "structure.undeclared",
                {
                    "name": metrics.name,
                    "source_files": _number(metrics.palate.source_file_count),
                },
            )
        )

    # One finding per key at most, so the worst offending manifest speaks for all.
    opaque: list[tuple[DependencyManifest, int]] = []
    tannic: list[tuple[DependencyManifest, int]] = []
    for manifest in structure.manifests:
        band = _dependency_band(manifest.ecosystem)
        if band is None:
            continue
        tannic_above, opaque_above = band
        if manifest.declared_count > opaque_above:
            opaque.append((manifest, opaque_above))
        elif manifest.declared_count > tannic_above:
            tannic.append((manifest, tannic_above))

    if opaque:
        manifest, threshold = max(opaque, key=lambda pair: pair[0].declared_count)
        findings.append(
            _finding("structure.opaque", _dependency_facts(manifest, threshold))
        )
    elif tannic:
        manifest, threshold = max(tannic, key=lambda pair: pair[0].declared_count)
        findings.append(
            _finding("structure.tannic", _dependency_facts(manifest, threshold))
        )

    # The deficient end of the dependency axis, against tannic and opaque. A
    # small project declaring nothing has nothing to declare, so this is only
    # asked of a repository large enough that the silence is a claim. It is
    # severity zero because writing no dependencies is not a defect.
    austere: Finding | None = None
    if (
        structure.manifests
        and structure.total_declared == 0
        and metrics.palate.source_file_count >= _band_int("austere_min_source_files")
    ):
        largest = max(structure.manifests, key=lambda item: item.declared_count)
        austere = _finding(
            "structure.austere",
            {
                "ecosystem": largest.ecosystem,
                "declared": _number(structure.total_declared),
                "manifest_path": _text(largest.manifest_path),
                "source_files": _number(metrics.palate.source_file_count),
            },
        )

    has_drift = any(manifest.drift for manifest in structure.manifests)
    if not findings and austere is None and not has_drift and structure.manifests:
        # Said only when the course has nothing else to report, so the tasting
        # never praises the dependency tree and condemns it in one breath.
        largest = max(structure.manifests, key=lambda item: item.declared_count)
        findings.append(
            _finding(
                "structure.declared",
                {
                    "ecosystem": largest.ecosystem,
                    "declared": _number(largest.declared_count),
                    "dev": _number(largest.dev_count),
                    "manifest_path": _text(largest.manifest_path),
                },
            )
        )

    # A missing lockfile is its own finding. Drift means two files exist and
    # disagree, and only then can a line name them both. Each key reports the
    # first manifest in path order, so neither condition can hide the other.
    unlocked: DependencyManifest | None = None
    disagreeing: DependencyManifest | None = None
    for manifest in structure.manifests:
        if not manifest.drift:
            continue
        if manifest.lockfile_path is None:
            if unlocked is None:
                unlocked = manifest
        elif disagreeing is None:
            disagreeing = manifest

    if unlocked is not None:
        findings.append(
            _finding(
                "structure.no_lockfile",
                {
                    "manifest_path": _text(unlocked.manifest_path),
                    "ecosystem": unlocked.ecosystem,
                    "declared": _number(unlocked.declared_count),
                },
            )
        )

    if disagreeing is not None:
        findings.append(
            _finding(
                "structure.drift",
                {
                    "manifest_path": _text(disagreeing.manifest_path),
                    "lockfile_path": _text(disagreeing.lockfile_path),
                    "reason": _text(disagreeing.drift_reason),
                    "declared": _number(disagreeing.declared_count),
                    "locked": _number(disagreeing.locked_count),
                },
            )
        )

    if austere is not None:
        findings.append(austere)

    return findings


def _judge_abandonment(metrics: RepoMetrics) -> list[Finding]:
    # One scan produces the markers and the palate together, and a marker
    # count is per thousand lines, so neither is worth reading without the
    # other.
    if not _read(metrics, "tree", "palate", "abandonment"):
        return []
    markers = metrics.abandonment
    if metrics.palate.total_lines <= 0:
        return []

    per_kloc = markers.per_kloc
    if per_kloc <= _band_float("todo_per_kloc_clean"):
        return [
            _finding(
                "abandonment.suspiciously_clean",
                {
                    "source_files": _number(metrics.palate.source_file_count),
                    "total_lines": _number(metrics.palate.total_lines),
                    "debug_prints": _number(markers.debug_print_count),
                },
            )
        ]

    if per_kloc > _band_float("todo_per_kloc_aggressive"):
        key = "abandonment.aggressive"
    elif per_kloc >= _band_float("todo_per_kloc_notes"):
        key = "abandonment.notes"
    else:
        return []

    return [
        _finding(
            key,
            {
                "total": _number(markers.total),
                "per_kloc": _decimal(per_kloc),
                "todo": _number(markers.todo),
                "fixme": _number(markers.fixme),
                "hack": _number(markers.hack),
                "xxx": _number(markers.xxx),
                "worst_path": _text(markers.worst_file_path),
                "worst_count": _number(markers.worst_file_count),
                "debug_prints": _number(markers.debug_print_count),
            },
        )
    ]


def _judge_finish(metrics: RepoMetrics) -> list[Finding]:
    # The markers are read from the files rather than from the log, so they
    # keep their own guard and still speak when only the log was cut short.
    if not _read(metrics, "git"):
        return _judge_abandonment(metrics)
    git = metrics.git
    findings: list[Finding] = []
    identity = {
        "name": metrics.name,
        "file_count": _number(metrics.palate.total_file_count),
    }

    if not git.is_repo:
        findings.append(_finding("finish.no_history", identity))
    elif not git.has_commits:
        findings.append(_finding("finish.void", identity))
    else:
        findings.append(
            _finding(
                "finish.history",
                {
                    "commit_count": _number(git.commit_count),
                    "fix_commits": _number(git.fix_commit_count),
                    "fix_percent": _percent(git.fix_ratio),
                    "subject": _text(git.last_commit_subject),
                    "last_date": _text(git.last_commit_date),
                    "author_count": _number(git.author_count),
                    "commits_phrase": _phrase(
                        git.commit_count, "commit", "commits"
                    ),
                    "authors_phrase": _phrase(
                        git.author_count, "author", "authors"
                    ),
                    "fixes_phrase": _phrase(
                        git.fix_commit_count, "commit", "commits"
                    ),
                },
            )
        )

    if git.is_repo and git.has_commits:
        if git.commit_count > 0 and git.fix_ratio > _band_float("fix_ratio_high"):
            findings.append(
                _finding(
                    "finish.fix_ratio",
                    {
                        "fix_commits": _number(git.fix_commit_count),
                        "commit_count": _number(git.commit_count),
                        "fix_percent": _percent(git.fix_ratio),
                        "fixes_phrase": _phrase(
                            git.fix_commit_count, "commit", "commits"
                        ),
                        "commits_phrase": _phrase(
                            git.commit_count, "commit", "commits"
                        ),
                    },
                )
            )

        if git.longest_gap_days > _band_int("gap_days_silence"):
            findings.append(
                _finding(
                    "finish.the_silence",
                    {
                        "gap_days": _number(git.longest_gap_days),
                        "gap_start": _text(git.longest_gap_start),
                        "gap_end": _text(git.longest_gap_end),
                    },
                )
            )

        if git.top_author_share > _band_float(
            "bus_factor_share"
        ) and git.commit_count >= _band_int("bus_factor_min_commits"):
            findings.append(
                _finding(
                    "finish.single_estate",
                    {
                        "author": _text(git.top_author_name),
                        "author_commits": _number(git.top_author_commits),
                        "share": _percent(git.top_author_share),
                        "commit_count": _number(git.commit_count),
                        "author_count": _number(git.author_count),
                    },
                )
            )

        # The other end of the authorship axis. One author holding everything
        # is a bus factor; a thousand holding a thousand lines is nobody
        # holding anything, and the number that says so is authors per
        # thousand lines rather than authors alone.
        thousands = metrics.palate.total_lines / _LINES_PER_KLOC
        if thousands > 0.0:
            per_kloc = git.author_count / thousands
            if per_kloc >= _band_float("authors_per_kloc_crowded"):
                findings.append(
                    _finding(
                        "finish.crowded",
                        {
                            "author_count": _number(git.author_count),
                            "total_lines": _number(metrics.palate.total_lines),
                            "per_kloc": _decimal(per_kloc),
                            "commit_count": _number(git.commit_count),
                            "authors_phrase": _phrase(
                                git.author_count, "author", "authors"
                            ),
                        },
                    )
                )

        subject = git.last_commit_subject
        if subject is not None and _FIX_SUBJECT_RE.search(subject) is not None:
            findings.append(
                _finding(
                    "finish.abrupt",
                    {
                        "subject": _text(subject),
                        "last_date": _text(git.last_commit_date),
                    },
                )
            )

        if git.days_since_last_commit > _band_int("dormant_days"):
            findings.append(
                _finding(
                    "finish.dormant",
                    {
                        "days": _number(git.days_since_last_commit),
                        "years": _decimal(git.days_since_last_commit / _DAYS_PER_YEAR),
                        "last_date": _text(git.last_commit_date),
                    },
                )
            )

    findings.extend(_judge_abandonment(metrics))
    return findings


# ---------------------------------------------------------------------------
# the score
# ---------------------------------------------------------------------------


def _unfinished(dropped: frozenset[str]) -> frozenset[str]:
    """Every dimension fed by an analyzer that did not finish."""
    lost: set[str] = set()
    for name in sorted(dropped):
        lost.update(ANALYZER_DIMENSIONS.get(name, ()))
    return frozenset(lost)


def _measured(metrics: RepoMetrics) -> Mapping[str, bool]:
    """Which dimensions had inputs, one predicate each.

    Documentation, hygiene and testing rest on files that are either present
    or absent, and absence is an answer, as long as something looked. The
    other five rest on measurements that can fail to happen, and a measurement
    that did not happen is not a clean result. An analyzer that stopped at the
    budget takes every dimension it feeds with it, on the same rule: what it
    never reached it never cleared.
    """
    coverage = metrics.coverage
    has_source = coverage.source_files > 0
    lost = _unfinished(_dropped(metrics))
    measured = {
        "documentation": True,
        "hygiene": True,
        "testing": True,
        "structure": coverage.dependencies_measured,
        "body": has_source and coverage.attributed_files > 0,
        "markers": has_source and coverage.lines_complete,
        "history": coverage.history_complete,
        "authorship": coverage.authorship_measured,
    }
    return {
        name: value and name not in lost for name, value in measured.items()
    }


def _dimensions(metrics: RepoMetrics, findings: Sequence[Finding]) -> tuple[Dimension, ...]:
    measured = _measured(metrics)
    totals: dict[str, int] = {name: 0 for name in DIMENSIONS}
    for finding in findings:
        spec = _SPECS.get(finding.key)
        if spec is None or spec.dimension not in totals:
            continue
        totals[spec.dimension] += finding.severity

    scored: list[Dimension] = []
    for name in DIMENSIONS:
        cap = _dimension_cap(name)
        severity = totals[name]
        is_measured = measured.get(name, False)
        deduction = 0.0
        if is_measured and cap > 0:
            deduction = min(1.0, severity / cap)
        scored.append(
            Dimension(
                name=name,
                measured=is_measured,
                severity=severity,
                cap=cap,
                deduction=deduction,
            )
        )
    return tuple(scored)


def _locked(metrics: RepoMetrics) -> bool:
    """Every manifest that declares a dependency also pins one.

    Not agreement between the two counts. Drift is inferred from file times
    and a fresh checkout rewrites those, so drift is worth a deduction and is
    not worth a gate. A manifest declaring nothing has nothing to pin.

    A lockfile that pins nothing is not a lockfile. Its name on disk is free
    and its contents are read, so the gate asks for the contents: otherwise
    the cheapest way through is an empty file with the right name.
    """
    return all(
        manifest.declared_count <= 0
        or (manifest.lockfile_path is not None and manifest.locked_count > 0)
        for manifest in metrics.structure.manifests
    )


def _reached(name: str, dropped: frozenset[str]) -> bool:
    """Whether every analyzer this gate reads ran to the end."""
    return not any(
        analyzer in dropped for analyzer in GATE_ANALYZERS.get(name, ())
    )


def _gates(metrics: RepoMetrics) -> tuple[Gate, ...]:
    """The conjunction that admits a repository to the outstanding band.

    Every predicate reads positive evidence. Where the evidence was never
    measured the gate is failed, which is the whole mechanism: withholding a
    measurement closes a gate and can never open one. An analyzer that stopped
    at the budget closes every gate that reads it, since a walk that ended
    early found no secret for the same reason it found nothing else.
    """
    git = metrics.git
    nose = metrics.nose
    coverage = metrics.coverage
    sediment = metrics.sediment
    passed = {
        "documented": (
            nose.readme_path is not None
            and nose.readme_lines >= _band_int("gate_readme_lines")
            and nose.license_path is not None
        ),
        "tested": nose.has_tests,
        "hygiene": (
            nose.gitignore_path is not None
            and sediment.secret_file_count == 0
            and sediment.os_cruft_count == 0
        ),
        "dependencies": coverage.dependencies_measured and _locked(metrics),
        "history": coverage.history_complete,
        "authorship": (
            coverage.authorship_measured
            and git.author_count >= _band_int("gate_min_authors")
        ),
        "cadence": (
            coverage.history_complete
            and git.fix_ratio <= _band_float("fix_ratio_high")
            and git.days_since_last_commit <= _band_int("dormant_days")
        ),
    }
    dropped = _dropped(metrics)
    return tuple(
        Gate(name=name, passed=passed[name] and _reached(name, dropped))
        for name in BASE_GATES
    )


def _care_gates(
    metrics: RepoMetrics, dimensions: Sequence[Dimension]
) -> tuple[Gate, ...]:
    """Sustained care, asked only of a repository that passed every base gate."""
    git = metrics.git
    nose = metrics.nose
    coverage = metrics.coverage
    passed = {
        "continuous_integration": nose.has_ci,
        "contributing": nose.has_contributing,
        "reference_documentation": nose.readme_lines
        >= _band_int("gate_readme_lines_exemplary"),
        "active": coverage.history_complete
        and git.days_since_last_commit <= _band_int("vintage_recent_days"),
        "locked": not any(manifest.drift for manifest in metrics.structure.manifests),
        # No single axis may be more than a fraction spent. The band mean
        # dilutes one bad dimension to an eighth, so without this a repository
        # with every process gate and one enormous file reaches the top band on
        # its paperwork. An unmeasured dimension fails this outright.
        "craft": all(
            dimension.measured
            and dimension.deduction <= _band_float("exemplary_max_dimension_deduction")
            for dimension in dimensions
        ),
        "complete_coverage": (
            all(dimension.measured for dimension in dimensions)
            and coverage.lines_complete
            and coverage.structural_scan_complete
        ),
    }
    dropped = _dropped(metrics)
    return tuple(
        Gate(name=name, passed=passed[name] and _reached(name, dropped))
        for name in CARE_GATES
    )


def _effective_deduction(dimensions: Sequence[Dimension]) -> float:
    """The mean deduction over measured dimensions, plus the coverage weight.

    Renormalising over what was measured is the honest denominator and it is
    also a gaming vector on its own: dropping a bad dimension raises the mean.
    The weight added per unmeasured dimension is what closes that, and the
    module docstring states the bound it has to clear.
    """
    measured = [dimension for dimension in dimensions if dimension.measured]
    missing = len(dimensions) - len(measured)
    mean = 0.0
    if measured:
        mean = sum(dimension.deduction for dimension in measured) / len(measured)
    weighted = mean + missing * _band_float("score_coverage_weight")
    return min(1.0, max(0.0, weighted))


def _position(low: int, high: int, span: int, deduction: float) -> int:
    """Where inside a band the integer lands.

    The band is the measurement and this is presentation. Percentile ordering
    within a band belongs here and is not built yet: this is the seam it will
    replace, taking the band's edges and one number in zero to one, and no
    caller passes it anything else.
    """
    return max(low, min(high, high - round(deduction * span)))


def _band_for(score: int) -> tuple[str, str]:
    for name, low, high, label in _score_bands():
        if low <= score <= high:
            return (name, label)
    return _unscoreable_band()


def _refusal(
    metrics: RepoMetrics, dimensions: Sequence[Dimension]
) -> tuple[str, dict[str, str]] | None:
    """Why this repository gets no number, or None if it gets one.

    Refusing is the point. A tree of templates with no program in it used to
    score above a hand written text editor, because every dimension nothing
    could read counted as clean.
    """
    coverage = metrics.coverage
    name = metrics.name

    # Both counts below are produced by the walk. When the walk stopped at the
    # budget they are floors, and a floor of zero is not a finding: saying a
    # repository holds no code because nobody finished looking is the kind of
    # confident falsehood the refusal exists to avoid. The walk feeds six of
    # the eight dimensions, so such a run falls through to the count of
    # dimensions below, which is true whatever the walk found.
    counted = "tree" not in _dropped(metrics)

    if counted and coverage.source_files <= 0:
        return (
            "no_source_files",
            {
                "name": name,
                "total_files": _number(metrics.palate.total_file_count),
            },
        )

    floor = _band_float("unscoreable_attribution_share")
    share = _share(coverage.attributed_files, coverage.source_files)
    if counted and share < floor:
        return (
            "unattributed",
            {
                "name": name,
                "source_files": _number(coverage.source_files),
                "attributed": _number(coverage.attributed_files),
                "percent": _percent(share),
                "floor": _percent(floor),
            },
        )

    minimum = _band_int("unscoreable_min_dimensions")
    scored = sum(1 for dimension in dimensions if dimension.measured)
    if scored < minimum:
        return (
            "too_few_dimensions",
            {
                "name": name,
                "scored": _number(scored),
                "total": _number(len(dimensions)),
                "minimum": _number(minimum),
            },
        )
    return None


def _judge(metrics: RepoMetrics) -> Judgement:
    collected: dict[str, Finding] = {}
    for finding in (
        *_judge_label(metrics),
        *_judge_vintage(metrics),
        *_judge_nose(metrics),
        *_judge_palate(metrics),
        *_judge_structure(metrics),
        *_judge_finish(metrics),
    ):
        collected[finding.key] = finding

    findings = tuple(sorted(collected.values(), key=_sort_key))
    total_severity = sum(finding.severity for finding in findings)

    dimensions = _dimensions(metrics, findings)
    gates = _gates(metrics)
    care = _care_gates(metrics, dimensions)
    scored = sum(1 for dimension in dimensions if dimension.measured)

    refusal = _refusal(metrics, dimensions)
    if refusal is not None:
        code, facts = refusal
        band, label = _unscoreable_band()
        return Judgement(
            findings=findings,
            score=None,
            total_severity=total_severity,
            band=band,
            band_label=label,
            dimensions=dimensions,
            scored_dimensions=scored,
            total_dimensions=len(dimensions),
            gates=gates,
            care_gates=care,
            refusal=code,
            refusal_facts=MappingProxyType(facts),
        )

    deduction = _effective_deduction(dimensions)
    bands = {entry[0]: entry for entry in _score_bands()}

    # Gates decide the band above ninety. Below it the deduction decides the
    # number and the band falls out of the number, which is the asymmetry the
    # whole model rests on: absence of defect never buys the top two bands.
    if all(gate.passed for gate in gates) and all(gate.passed for gate in care):
        band, low, high, label = bands[EXEMPLARY]
        score = _position(low, high, _band_int("score_exemplary_span"), deduction)
    elif all(gate.passed for gate in gates):
        band, low, high, label = bands[OUTSTANDING]
        score = _position(low, high, _band_int("score_gated_span"), deduction)
    else:
        score = _position(
            _band_int("score_deduction_floor"),
            _band_int("score_deduction_ceiling"),
            _band_int("score_deduction_span"),
            deduction,
        )
        band, label = _band_for(score)

    return Judgement(
        findings=findings,
        score=score,
        total_severity=total_severity,
        band=band,
        band_label=label,
        dimensions=dimensions,
        scored_dimensions=scored,
        total_dimensions=len(dimensions),
        gates=gates,
        care_gates=care,
    )


def judge(metrics: RepoMetrics) -> Judgement:
    """Apply BANDS to one RepoMetrics record and return the sorted findings.

    Never raises. A record the bands cannot be applied to is refused a number
    and says so, because a tasting that ends in a traceback is worse than a
    tasting that ends in a refusal.
    """
    try:
        return _judge(metrics)
    except Exception:  # the contract is that judge() never raises
        return _refused(metrics)


def _refused(metrics: RepoMetrics) -> Judgement:
    """The last resort. Reads two fields and formats neither."""
    band, label = _unscoreable_band()
    try:
        name = metrics.name
        total_files = _number(metrics.palate.total_file_count)
    except Exception:  # the fallback cannot fail either
        name = _UNKNOWN
        total_files = _UNKNOWN
    return Judgement(
        findings=(),
        score=None,
        total_severity=0,
        band=band,
        band_label=label,
        dimensions=(),
        scored_dimensions=0,
        total_dimensions=len(DIMENSIONS),
        gates=(),
        care_gates=(),
        refusal="unreadable",
        refusal_facts=MappingProxyType({"name": name, "total_files": total_files}),
    )
