"""Threshold judging.

Consumes a RepoMetrics record and returns a Judgement. Every numeric threshold
this module applies lives in BANDS and is read back from there, so the bands can
be retuned in one place. This module emits no reader facing prose: findings
carry pre-formatted fact strings that lines.py templates substitute.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Final, cast

from sommelier.collect import (
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
        "function_lines_long": 100,
        "readme_lines_thin": 10,
        "debug_prints_notable": 5,
        "vintage_aged_years": 5.0,
        "vintage_recent_days": 90,
        "dormant_days": 365,
        "polyglot_min_languages": 4,
        "polyglot_min_share": 0.05,
        "monoculture_share": 0.95,
        "fix_subject_pattern": r"\bfix(e[sd])?\b",
        "score_base": 94,
        "score_penalty_cap": 7,
        "score_severity_per_penalty": 3,
    }
)

_UNKNOWN: Final[str] = "unknown"
_DAYS_PER_YEAR: Final[float] = 365.25
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
class Judgement:
    findings: tuple[Finding, ...]
    score: int
    total_severity: int


@dataclass(frozen=True)
class _Spec:
    course: str
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

# The single registry of what judge can say: course, severity and the exact set
# of facts each finding guarantees. ALL_KEYS and KEY_FACTS derive from it.
_SPECS: Final[Mapping[str, _Spec]] = MappingProxyType(
    {
        "label.identity": _Spec(
            "label",
            0,
            ("name", "language", "file_count", "source_file_count", "total_lines"),
        ),
        "label.vendored": _Spec(
            "label",
            3,
            (
                "vendored_files",
                "vendored_dirs",
                "total_files",
                "vendored_share",
                "dirs_phrase",
            ),
        ),
        "label.secrets": _Spec("label", 3, ("secret_files", "path")),
        "label.os_cruft": _Spec("label", 1, ("cruft_files", "path")),
        "label.large_binary": _Spec(
            "label", 2, ("binary_count", "largest_path", "largest_mb")
        ),
        "label.polyglot": _Spec(
            "label", 1, ("language_count", "languages", "primary", "primary_share")
        ),
        "label.monoculture": _Spec("label", 0, ("language", "share", "file_count")),
        "vintage.no_history": _Spec("vintage", 2, ("name", "file_count")),
        "vintage.empty": _Spec("vintage", 2, ("name", "file_count")),
        "vintage.declared": _Spec(
            "vintage",
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
        "vintage.shallow": _Spec("vintage", 0, ("commit_count",)),
        "vintage.aged": _Spec(
            "vintage",
            0,
            ("first_year", "years", "first_date", "commit_count", "commits_phrase"),
        ),
        "vintage.recent": _Spec(
            "vintage", 0, ("days", "first_date", "commit_count", "commits_phrase")
        ),
        "nose.no_readme": _Spec("nose", 2, ("name", "source_files", "total_lines")),
        "nose.thin_readme": _Spec(
            "nose", 1, ("readme_path", "readme_lines", "readme_bytes")
        ),
        "nose.no_license": _Spec("nose", 1, ("name",)),
        "nose.no_gitignore": _Spec("nose", 3, ("name", "total_files")),
        "nose.no_tests": _Spec("nose", 2, ("source_files", "total_lines")),
        "nose.documented": _Spec(
            "nose", 0, ("readme_path", "readme_lines", "license_name")
        ),
        "nose.debug_prints": _Spec("nose", 1, ("debug_prints", "source_files")),
        "palate.full_bodied": _Spec("palate", 1, _FILE_SIZE_FACTS),
        "palate.cry_for_help": _Spec("palate", 3, _FILE_SIZE_FACTS),
        "palate.deep_nesting": _Spec("palate", 2, ("depth", "path")),
        "palate.abyssal": _Spec("palate", 3, ("depth", "path")),
        "palate.long_function": _Spec("palate", 2, ("name", "lines", "path")),
        "palate.sampled": _Spec("palate", 0, ("scanned", "total")),
        "palate.empty": _Spec("palate", 3, ("name", "total_files")),
        "palate.body": _Spec(
            "palate",
            0,
            (
                "source_files",
                "average_lines",
                "largest_path",
                "largest_lines",
                "depth",
            ),
        ),
        "structure.tannic": _Spec("structure", 1, _DEPENDENCY_FACTS),
        "structure.opaque": _Spec("structure", 2, _DEPENDENCY_FACTS),
        "structure.undeclared": _Spec("structure", 1, ("name", "source_files")),
        "structure.declared": _Spec(
            "structure", 0, ("ecosystem", "declared", "dev", "manifest_path")
        ),
        "structure.drift": _Spec(
            "structure",
            2,
            ("manifest_path", "lockfile_path", "reason", "declared", "locked"),
        ),
        "structure.no_lockfile": _Spec(
            "structure", 2, ("manifest_path", "ecosystem", "declared")
        ),
        "finish.fix_ratio": _Spec(
            "finish",
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
            "finish", 2, ("gap_days", "gap_start", "gap_end")
        ),
        "finish.single_estate": _Spec(
            "finish",
            1,
            ("author", "author_commits", "share", "commit_count", "author_count"),
        ),
        "finish.abrupt": _Spec("finish", 1, ("subject", "last_date")),
        "finish.dormant": _Spec("finish", 2, ("days", "years", "last_date")),
        "finish.history": _Spec(
            "finish",
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
        "finish.no_history": _Spec("finish", 2, ("name", "file_count")),
        "finish.void": _Spec("finish", 2, ("name", "file_count")),
        # Markers are a Nose finding: they are the first thing the reader
        # notices, not the aftertaste.
        "abandonment.suspiciously_clean": _Spec(
            "nose", 0, ("source_files", "total_lines", "debug_prints")
        ),
        "abandonment.notes": _Spec("nose", 1, _MARKER_FACTS),
        "abandonment.aggressive": _Spec("nose", 2, _MARKER_FACTS),
    }
)

ALL_KEYS: Final[tuple[str, ...]] = tuple(sorted(_SPECS))

KEY_FACTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {key: _SPECS[key].facts for key in ALL_KEYS}
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
    # course is never silent on a repository that did everything right.
    if not findings and nose.readme_path is not None:
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

        nesting_facts = {
            "depth": _number(palate.max_indent_depth),
            "path": _text(palate.max_indent_path),
        }
        if palate.max_indent_depth >= _band_int("indent_depth_abyssal"):
            findings.append(_finding("palate.abyssal", nesting_facts))
        elif palate.max_indent_depth >= _band_int("indent_depth_deep"):
            findings.append(_finding("palate.deep_nesting", nesting_facts))

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
    has_drift = any(manifest.drift for manifest in structure.manifests)
    if not findings and not has_drift and structure.manifests:
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

    return findings


def _judge_abandonment(metrics: RepoMetrics) -> list[Finding]:
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


def judge(metrics: RepoMetrics) -> Judgement:
    """Apply BANDS to one RepoMetrics record and return the sorted findings."""
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
    penalty = min(
        _band_int("score_penalty_cap"),
        total_severity // _band_int("score_severity_per_penalty"),
    )
    return Judgement(
        findings=findings,
        score=_band_int("score_base") - penalty,
        total_severity=total_severity,
    )
