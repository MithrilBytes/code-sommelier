"""Output formatting for code-sommelier.

Three renderers, no analysis and no voice: the tasting card grid, a plain
metrics table, and a stable JSON dump.
"""

from __future__ import annotations

import dataclasses
import json
import math
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any, Final

from sommelier.collect import (
    DependencyManifest,
    DroppedAnalyzer,
    LanguageShare,
    RepoMetrics,
    SedimentItem,
)
from sommelier.judge import Finding, Judgement
from sommelier.voice import Course, TastingCard

__all__ = ["render_card", "render_json", "render_sober"]

_TITLE: Final[str] = "CODE SOMMELIER"
_HEADER_WIDTH: Final[int] = 63
_LABEL_WIDTH: Final[int] = 13
_BODY_WIDTH: Final[int] = 66
_SOBER_WIDTH: Final[int] = 79
_FLOAT_PLACES: Final[int] = 4
_BYTES_PER_MB: Final[float] = 1048576.0

_PROXY_NOTE: Final[str] = (
    "Note: maximum indentation depth and longest function length are proxies "
    "for complexity. They are not cyclomatic complexity, and neither number "
    "should be read as one."
)


# ---------------------------------------------------------------------------
# tasting card
# ---------------------------------------------------------------------------


def render_card(card: TastingCard) -> str:
    """Lay the tasting card out on the 79 column grid."""
    lines: list[str] = [_header_line(card.tasting_number), ""]
    tail = (
        Course(name="Verdict", body=card.verdict),
        Course(name="Pairing", body=card.pairing),
    )
    for course in (*card.courses, *tail):
        lines.extend(_labelled_block(course.name, course.body))
    if card.footnotes:
        lines.append("")
        lines.extend(_labelled_block("Footnote", " ".join(card.footnotes)))
    return "\n".join(lines)


def _header_line(tasting_number: int) -> str:
    right = f"tasting no. {tasting_number}"
    room = _HEADER_WIDTH - len(_TITLE)
    if len(right) >= room:
        return f"{_TITLE} {right}"
    return _TITLE + right.rjust(room)


def _labelled_block(label: str, body: str) -> list[str]:
    wrapped = textwrap.wrap(body.strip(), width=_BODY_WIDTH)
    indent = " " * _LABEL_WIDTH
    if len(label) >= _LABEL_WIDTH:
        # An over long label takes a line of its own so the body column holds.
        return [label, *(indent + line for line in wrapped)]
    if not wrapped:
        return [label]
    head = label.ljust(_LABEL_WIDTH) + wrapped[0]
    return [head, *(indent + line for line in wrapped[1:])]


# ---------------------------------------------------------------------------
# json
# ---------------------------------------------------------------------------


def render_json(metrics: RepoMetrics, judgement: Judgement) -> str:
    """Serialise the measurements and the judgement, and nothing else."""
    payload = {
        "judgement": _jsonable(judgement),
        "metrics": _jsonable(metrics),
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _jsonable(value: object) -> Any:
    """Walk any dataclass tree into JSON safe primitives.

    Field driven rather than hand listed, so it cannot drift from collect.py.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # JSON has no literal for infinity or NaN.
        return round(value, _FLOAT_PLACES) if math.isfinite(value) else None
    return str(value)


# ---------------------------------------------------------------------------
# sober table
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Section:
    title: str
    rows: tuple[tuple[str, str], ...]


def render_sober(metrics: RepoMetrics, judgement: Judgement) -> str:
    """Print the raw measurements as an aligned two column table."""
    sections = _sober_sections(metrics, judgement)
    width = max(
        (len(label) for section in sections for label, _ in section.rows),
        default=0,
    )
    lines: list[str] = []
    for section in sections:
        if lines:
            lines.append("")
        lines.append(section.title)
        for label, value in section.rows:
            lines.append(f"  {label.ljust(width)}  {value}".rstrip())
    lines.append("")
    lines.extend(textwrap.wrap(_PROXY_NOTE, width=_SOBER_WIDTH))
    return "\n".join(lines)


def _sober_sections(metrics: RepoMetrics, judgement: Judgement) -> tuple[_Section, ...]:
    git = metrics.git
    terroir = metrics.terroir
    nose = metrics.nose
    palate = metrics.palate
    structure = metrics.structure
    abandonment = metrics.abandonment
    sediment = metrics.sediment

    sections: list[_Section] = [
        _Section(
            "Repository",
            (
                ("name", metrics.name),
                ("path", metrics.path),
                ("git repository", _yes_no(metrics.is_git_repo)),
                ("empty", _yes_no(metrics.is_empty)),
            ),
        ),
        _Section(
            "History",
            (
                ("commits", _count(git.commit_count)),
                ("has commits", _yes_no(git.has_commits)),
                ("shallow clone", _yes_no(git.shallow)),
                ("first commit", _text(git.first_commit_date)),
                ("last commit", _text(git.last_commit_date)),
                ("days since last commit", _count(git.days_since_last_commit)),
                ("fix commits", _count(git.fix_commit_count)),
                ("fix ratio", _ratio(git.fix_ratio)),
                ("longest gap days", _count(git.longest_gap_days)),
                ("longest gap start", _text(git.longest_gap_start)),
                ("longest gap end", _text(git.longest_gap_end)),
                ("authors", _count(git.author_count)),
                ("top author", _text(git.top_author_name)),
                ("top author commits", _count(git.top_author_commits)),
                ("top author share", _ratio(git.top_author_share)),
                ("last commit subject", _text(git.last_commit_subject)),
            ),
        ),
        _Section(
            "Languages",
            (
                ("primary language", _text(terroir.primary_language)),
                ("languages detected", _count(len(terroir.languages))),
                ("frameworks", _join(terroir.frameworks)),
                *_language_rows(terroir.languages),
            ),
        ),
        _Section(
            "Documentation",
            (
                ("readme", _text(nose.readme_path)),
                ("readme lines", _count(nose.readme_lines)),
                ("readme bytes", _count(nose.readme_bytes)),
                ("license file", _text(nose.license_path)),
                ("license name", _text(nose.license_name)),
                ("gitignore", _text(nose.gitignore_path)),
                ("gitignore rules", _count(nose.gitignore_rules)),
                ("contributing guide", _yes_no(nose.has_contributing)),
                ("continuous integration", _yes_no(nose.has_ci)),
                ("tests present", _yes_no(nose.has_tests)),
            ),
        ),
        _Section(
            "Files",
            (
                ("source files", _count(palate.source_file_count)),
                ("total files", _count(palate.total_file_count)),
                ("scanned files", _count(palate.scanned_file_count)),
                ("sampled", _yes_no(palate.sampled)),
                ("source lines", _count(palate.total_lines)),
                ("average lines per file", _one_place(palate.average_lines)),
                ("largest file", _text(palate.largest_file_path)),
                ("largest file lines", _count(palate.largest_file_lines)),
                ("max indent depth", _count(palate.max_indent_depth)),
                ("max indent file", _text(palate.max_indent_path)),
                ("longest function", _text(palate.longest_function_name)),
                ("longest function lines", _count(palate.longest_function_lines)),
                ("longest function file", _text(palate.longest_function_path)),
            ),
        ),
        _Section(
            "Dependencies",
            (
                ("manifests", _count(len(structure.manifests))),
                ("declared dependencies", _count(structure.total_declared)),
                ("ecosystems", _join(structure.ecosystems)),
                ("no manifest found", _yes_no(structure.undeclared)),
                *tuple(_manifest_row(item) for item in structure.manifests),
            ),
        ),
        _Section(
            "Markers",
            (
                ("todo", _count(abandonment.todo)),
                ("fixme", _count(abandonment.fixme)),
                ("hack", _count(abandonment.hack)),
                ("xxx", _count(abandonment.xxx)),
                ("total markers", _count(abandonment.total)),
                ("markers per kloc", _one_place(abandonment.per_kloc)),
                ("worst file", _text(abandonment.worst_file_path)),
                ("worst file markers", _count(abandonment.worst_file_count)),
                ("debug prints", _count(abandonment.debug_print_count)),
                ("commented out lines", _count(abandonment.commented_out_code_lines)),
            ),
        ),
        _Section(
            "Sediment",
            (
                ("vendored files", _count(sediment.vendored_file_count)),
                ("vendored directories", _count(sediment.vendored_dir_count)),
                ("secret files", _count(sediment.secret_file_count)),
                ("os cruft files", _count(sediment.os_cruft_count)),
                ("large binaries", _count(sediment.large_binary_count)),
                ("largest binary", _text(sediment.largest_binary_path)),
                ("largest binary bytes", _count(sediment.largest_binary_bytes)),
                ("largest binary size", _megabytes(sediment.largest_binary_bytes)),
                *tuple(_sediment_row(item) for item in sediment.items),
            ),
        ),
    ]

    if metrics.dropped:
        sections.append(
            _Section(
                "Dropped analyzers",
                tuple(_dropped_row(item) for item in metrics.dropped),
            )
        )

    sections.append(
        _Section(
            "Judgement",
            (
                ("score", _count(judgement.score)),
                ("total severity", _count(judgement.total_severity)),
                ("findings", _count(len(judgement.findings))),
                *tuple(_finding_row(item) for item in judgement.findings),
            ),
        )
    )
    return tuple(sections)


def _language_rows(languages: Sequence[LanguageShare]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            f"language {language.name}",
            f"{_count(language.file_count)} files, "
            f"{_count(language.line_count)} lines, "
            f"{_percent(language.share)}",
        )
        for language in languages
    )


def _manifest_row(manifest: DependencyManifest) -> tuple[str, str]:
    parts = [
        manifest.ecosystem,
        f"{_count(manifest.declared_count)} declared",
        f"{_count(manifest.dev_count)} dev",
        f"{_count(manifest.locked_count)} locked",
        f"lockfile {_text(manifest.lockfile_path)}",
        f"drift {_yes_no(manifest.drift)}",
    ]
    if manifest.drift_reason:
        parts.append(manifest.drift_reason)
    return ("manifest", f"{manifest.manifest_path}: " + ", ".join(parts))


def _sediment_row(item: SedimentItem) -> tuple[str, str]:
    return (
        "sediment",
        f"{item.path}: {item.kind}, {_count(item.file_count)} files, "
        f"{_count(item.size_bytes)} bytes",
    )


def _dropped_row(item: DroppedAnalyzer) -> tuple[str, str]:
    return ("dropped", f"{item.name}: {item.reason}")


def _finding_row(finding: Finding) -> tuple[str, str]:
    return (
        "finding",
        f"{finding.key}: course {finding.course}, severity {finding.severity}",
    )


# ---------------------------------------------------------------------------
# value formatting
# ---------------------------------------------------------------------------


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _count(value: int) -> str:
    return format(value, ",")


def _ratio(value: float) -> str:
    return f"{value:.{_FLOAT_PLACES}f}"


def _one_place(value: float) -> str:
    return f"{value:.1f}"


def _percent(share: float) -> str:
    return f"{share * 100.0:.0f} percent"


def _megabytes(size_bytes: int) -> str:
    return f"{size_bytes / _BYTES_PER_MB:.1f} MB"


def _text(value: str | None) -> str:
    return value if value else "none"


def _join(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "none"
