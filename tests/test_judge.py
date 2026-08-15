"""Band edge tests for sommelier.judge.

Every numeric threshold in the contract is exercised just below the edge, at the
edge, and just above it. Metrics are built directly rather than through
collect() so that the suite stays fast and free of filesystem and git state.
"""

from __future__ import annotations

import datetime as dt
import unittest
from collections.abc import Sequence
from dataclasses import replace

from sommelier.collect import (
    AbandonmentMetrics,
    Coverage,
    DependencyManifest,
    GitMetrics,
    LanguagePalate,
    LanguageShare,
    NoseMetrics,
    PalateMetrics,
    RepoMetrics,
    SedimentItem,
    SedimentMetrics,
    StructureMetrics,
    TerroirMetrics,
)
from sommelier.judge import (
    ALL_KEYS,
    BANDS,
    BASE_GATES,
    CARE_GATES,
    COURSES,
    DIMENSIONS,
    AUTHORS,
    COMMITS,
    COUNT,
    DATE,
    DAYS,
    DIRECTORIES,
    KEY_DIMENSIONS,
    KEY_FACTS,
    MEASUREMENTS,
    REFUSAL_FACTS,
    REFUSALS,
    UNITS,
    YEAR,
    YEARS,
    Fact,
    Finding,
    judge,
)

# Every key judge can emit, with the severity it must carry. Nine of these are
# not in the contract's band list. Judge adds the severity zero openers
# vintage.declared, nose.documented, palate.body, structure.declared and
# finish.history so that no course renders blank, mirrors the vintage absences
# as finish.no_history and finish.void, and splits a missing lockfile out of
# structure.drift as structure.no_lockfile. It also bands debug prints as
# nose.debug_prints. The contract's band list should be amended to match.
EXPECTED_SEVERITY: dict[str, int] = {
    "label.identity": 0,
    "label.monoculture": 0,
    "label.polyglot": 1,
    "label.os_cruft": 1,
    "label.large_binary": 2,
    "label.vendored": 3,
    "label.secrets": 3,
    "vintage.shallow": 0,
    "vintage.aged": 0,
    "vintage.recent": 0,
    "vintage.no_history": 2,
    "vintage.empty": 2,
    "vintage.declared": 0,
    "nose.documented": 0,
    "nose.exhaustive_readme": 0,
    "nose.debug_prints": 1,
    "nose.thin_readme": 1,
    "nose.no_license": 1,
    "nose.no_readme": 2,
    "nose.no_tests": 2,
    "nose.no_gitignore": 3,
    "palate.sampled": 0,
    "palate.body": 0,
    "palate.full_bodied": 1,
    "palate.thin": 1,
    "palate.flat": 1,
    "palate.deep_nesting": 2,
    "palate.long_function": 2,
    "palate.abyssal": 3,
    "palate.cry_for_help": 3,
    "palate.empty": 3,
    "structure.undeclared": 1,
    "structure.declared": 0,
    "structure.austere": 0,
    "structure.tannic": 1,
    "structure.drift": 2,
    "structure.no_lockfile": 2,
    "structure.opaque": 2,
    "abandonment.suspiciously_clean": 0,
    "abandonment.notes": 1,
    "abandonment.aggressive": 2,
    "finish.single_estate": 1,
    "finish.crowded": 1,
    "finish.abrupt": 1,
    "finish.fix_ratio": 2,
    "finish.the_silence": 2,
    "finish.dormant": 2,
    "finish.history": 0,
    "finish.no_history": 2,
    "finish.void": 2,
}

# Where each finding is counted, which is a different question from where it
# is spoken. A finding on the label may be a hygiene defect, and a finding on
# the finish may be an authorship one.
EXPECTED_DIMENSION: dict[str, str] = {
    "label.identity": "body",
    "label.monoculture": "structure",
    "label.polyglot": "structure",
    "label.os_cruft": "hygiene",
    "label.large_binary": "hygiene",
    "label.vendored": "hygiene",
    "label.secrets": "hygiene",
    "vintage.shallow": "history",
    "vintage.aged": "history",
    "vintage.recent": "history",
    "vintage.no_history": "history",
    "vintage.empty": "history",
    "vintage.declared": "history",
    "nose.documented": "documentation",
    "nose.exhaustive_readme": "documentation",
    "nose.debug_prints": "hygiene",
    "nose.thin_readme": "documentation",
    "nose.no_license": "documentation",
    "nose.no_readme": "documentation",
    "nose.no_tests": "testing",
    "nose.no_gitignore": "hygiene",
    "palate.sampled": "body",
    "palate.body": "body",
    "palate.full_bodied": "body",
    "palate.thin": "body",
    "palate.flat": "body",
    "palate.deep_nesting": "body",
    "palate.long_function": "body",
    "palate.abyssal": "body",
    "palate.cry_for_help": "body",
    "palate.empty": "body",
    "structure.undeclared": "structure",
    "structure.declared": "structure",
    "structure.austere": "structure",
    "structure.tannic": "structure",
    "structure.drift": "structure",
    "structure.no_lockfile": "structure",
    "structure.opaque": "structure",
    "abandonment.suspiciously_clean": "markers",
    "abandonment.notes": "markers",
    "abandonment.aggressive": "markers",
    "finish.single_estate": "authorship",
    "finish.crowded": "authorship",
    "finish.abrupt": "history",
    "finish.fix_ratio": "history",
    "finish.the_silence": "history",
    "finish.dormant": "history",
    "finish.history": "history",
    "finish.no_history": "history",
    "finish.void": "history",
}

ABANDONMENT_BAND = (
    "abandonment.suspiciously_clean",
    "abandonment.notes",
    "abandonment.aggressive",
)
FILE_SIZE_BAND = ("palate.full_bodied", "palate.cry_for_help")
INDENT_BAND = ("palate.deep_nesting", "palate.abyssal")
DEPENDENCY_BAND = ("structure.tannic", "structure.opaque")
AGE_BAND = ("vintage.aged", "vintage.recent")
HISTORY_BAND = ("vintage.no_history", "vintage.empty")
FINISH_HISTORY_BAND = ("finish.no_history", "finish.void")

MANIFEST_PATHS: dict[str, str] = {
    "javascript": "package.json",
    "python": "pyproject.toml",
    "go": "go.mod",
    "rust": "Cargo.toml",
}
LOCKFILE_PATHS: dict[str, str] = {
    "javascript": "package-lock.json",
    "python": "requirements.lock",
    "go": "go.sum",
    "rust": "Cargo.lock",
}
# ecosystem -> (highest count that is still untannic, highest count still tannic)
DEPENDENCY_LIMITS: dict[str, tuple[int, int]] = {
    "javascript": (40, 100),
    "python": (25, 60),
    "go": (20, 50),
    "rust": (20, 50),
}

TODAY = dt.date.today()


def days_ago(count: int) -> dt.date:
    return TODAY - dt.timedelta(days=count)


BASE_GIT = GitMetrics(
    is_repo=True,
    has_commits=True,
    shallow=False,
    first_commit_date=days_ago(730).isoformat(),
    last_commit_date=days_ago(10).isoformat(),
    first_commit_year=days_ago(730).year,
    last_commit_year=days_ago(10).year,
    commit_count=120,
    fix_commit_count=12,
    fix_ratio=0.10,
    longest_gap_days=21,
    longest_gap_start=days_ago(400).isoformat(),
    longest_gap_end=days_ago(379).isoformat(),
    days_since_last_commit=10,
    author_count=4,
    top_author_name="alice",
    top_author_commits=60,
    top_author_share=0.5,
    last_commit_subject="add caching layer",
)

BASE_TERROIR = TerroirMetrics(
    languages=(
        LanguageShare(name="Python", file_count=24, line_count=2400, share=0.6),
        LanguageShare(name="JavaScript", file_count=16, line_count=1600, share=0.4),
    ),
    primary_language="Python",
    frameworks=("Django",),
)

BASE_NOSE = NoseMetrics(
    readme_path="README.md",
    readme_lines=120,
    readme_bytes=4096,
    license_path="LICENSE",
    license_name="MIT",
    gitignore_path=".gitignore",
    gitignore_rules=24,
    has_contributing=True,
    has_ci=True,
    has_tests=True,
)

BASE_LANGUAGE_PALATE = LanguagePalate(
    name="Python",
    file_count=40,
    line_count=4000,
    max_indent_depth=3,
    max_indent_path="src/app.py",
    largest_file_lines=180,
    largest_file_path="src/app.py",
    longest_function_lines=42,
    longest_function_name="handle",
    longest_function_path="src/app.py",
    function_detector_ran=True,
)

BASE_PALATE = PalateMetrics(
    inventory="git",
    source_file_count=40,
    total_file_count=46,
    total_lines=4000,
    average_lines=100.0,
    largest_file_path="src/app.py",
    largest_file_lines=180,
    max_indent_depth=3,
    max_indent_path="src/app.py",
    longest_function_lines=42,
    longest_function_name="handle",
    longest_function_path="src/app.py",
    sampled=False,
    scanned_file_count=40,
    by_language=(BASE_LANGUAGE_PALATE,),
)

# Everything measured, nothing withheld. A test that cares about a gap says
# so by replacing the field it cares about.
BASE_COVERAGE = Coverage(
    lines_complete=True,
    truncated_files=0,
    structural_scan_complete=True,
    function_detector_files=40,
    attributed_files=40,
    source_files=40,
    history_complete=True,
    authorship_measured=True,
    dependencies_measured=True,
)

BASE_MANIFEST = DependencyManifest(
    ecosystem="python",
    manifest_path="pyproject.toml",
    declared_count=8,
    dev_count=0,
    lockfile_path="requirements.lock",
    locked_count=8,
    drift=False,
    drift_reason=None,
)

BASE_STRUCTURE = StructureMetrics(
    manifests=(BASE_MANIFEST,),
    total_declared=8,
    undeclared=False,
    ecosystems=("python",),
)

BASE_ABANDONMENT = AbandonmentMetrics(
    todo=6,
    fixme=2,
    hack=0,
    xxx=0,
    total=8,
    per_kloc=2.0,
    worst_file_path="src/app.py",
    worst_file_count=3,
    debug_print_count=0,
    commented_out_code_lines=0,
)

BASE_SEDIMENT = SedimentMetrics(
    items=(),
    vendored_file_count=0,
    vendored_dir_count=0,
    secret_file_count=0,
    os_cruft_count=0,
    large_binary_count=0,
    largest_binary_path=None,
    largest_binary_bytes=0,
)

# A repository that trips nothing except the always emitted identity line.
BASE_METRICS = RepoMetrics(
    path="/repos/cellar",
    name="cellar",
    is_git_repo=True,
    is_empty=False,
    git=BASE_GIT,
    terroir=BASE_TERROIR,
    nose=BASE_NOSE,
    palate=BASE_PALATE,
    coverage=BASE_COVERAGE,
    structure=BASE_STRUCTURE,
    abandonment=BASE_ABANDONMENT,
    sediment=BASE_SEDIMENT,
    dropped=(),
)


def repo_with_git(
    *,
    is_repo: bool = BASE_GIT.is_repo,
    has_commits: bool = BASE_GIT.has_commits,
    shallow: bool = BASE_GIT.shallow,
    first_commit_date: str | None = BASE_GIT.first_commit_date,
    last_commit_date: str | None = BASE_GIT.last_commit_date,
    first_commit_year: int | None = BASE_GIT.first_commit_year,
    last_commit_year: int | None = BASE_GIT.last_commit_year,
    commit_count: int = BASE_GIT.commit_count,
    fix_commit_count: int = BASE_GIT.fix_commit_count,
    fix_ratio: float = BASE_GIT.fix_ratio,
    longest_gap_days: int = BASE_GIT.longest_gap_days,
    longest_gap_start: str | None = BASE_GIT.longest_gap_start,
    longest_gap_end: str | None = BASE_GIT.longest_gap_end,
    days_since_last_commit: int = BASE_GIT.days_since_last_commit,
    author_count: int = BASE_GIT.author_count,
    top_author_name: str | None = BASE_GIT.top_author_name,
    top_author_commits: int = BASE_GIT.top_author_commits,
    top_author_share: float = BASE_GIT.top_author_share,
    last_commit_subject: str | None = BASE_GIT.last_commit_subject,
) -> RepoMetrics:
    return replace(
        BASE_METRICS,
        git=GitMetrics(
            is_repo=is_repo,
            has_commits=has_commits,
            shallow=shallow,
            first_commit_date=first_commit_date,
            last_commit_date=last_commit_date,
            first_commit_year=first_commit_year,
            last_commit_year=last_commit_year,
            commit_count=commit_count,
            fix_commit_count=fix_commit_count,
            fix_ratio=fix_ratio,
            longest_gap_days=longest_gap_days,
            longest_gap_start=longest_gap_start,
            longest_gap_end=longest_gap_end,
            days_since_last_commit=days_since_last_commit,
            author_count=author_count,
            top_author_name=top_author_name,
            top_author_commits=top_author_commits,
            top_author_share=top_author_share,
            last_commit_subject=last_commit_subject,
        ),
    )


def repo_with_nose(
    *,
    readme_path: str | None = BASE_NOSE.readme_path,
    readme_lines: int = BASE_NOSE.readme_lines,
    readme_bytes: int = BASE_NOSE.readme_bytes,
    license_path: str | None = BASE_NOSE.license_path,
    license_name: str | None = BASE_NOSE.license_name,
    gitignore_path: str | None = BASE_NOSE.gitignore_path,
    gitignore_rules: int = BASE_NOSE.gitignore_rules,
    has_contributing: bool = BASE_NOSE.has_contributing,
    has_ci: bool = BASE_NOSE.has_ci,
    has_tests: bool = BASE_NOSE.has_tests,
) -> RepoMetrics:
    return replace(
        BASE_METRICS,
        nose=NoseMetrics(
            readme_path=readme_path,
            readme_lines=readme_lines,
            readme_bytes=readme_bytes,
            license_path=license_path,
            license_name=license_name,
            gitignore_path=gitignore_path,
            gitignore_rules=gitignore_rules,
            has_contributing=has_contributing,
            has_ci=has_ci,
            has_tests=has_tests,
        ),
    )


def repo_with_palate(
    *,
    source_file_count: int = BASE_PALATE.source_file_count,
    total_file_count: int = BASE_PALATE.total_file_count,
    total_lines: int = BASE_PALATE.total_lines,
    average_lines: float = BASE_PALATE.average_lines,
    largest_file_path: str | None = BASE_PALATE.largest_file_path,
    largest_file_lines: int = BASE_PALATE.largest_file_lines,
    max_indent_depth: int = BASE_PALATE.max_indent_depth,
    max_indent_path: str | None = BASE_PALATE.max_indent_path,
    longest_function_lines: int = BASE_PALATE.longest_function_lines,
    longest_function_name: str | None = BASE_PALATE.longest_function_name,
    longest_function_path: str | None = BASE_PALATE.longest_function_path,
    sampled: bool = BASE_PALATE.sampled,
    scanned_file_count: int = BASE_PALATE.scanned_file_count,
    by_language: tuple[LanguagePalate, ...] = BASE_PALATE.by_language,
) -> RepoMetrics:
    return replace(
        BASE_METRICS,
        palate=PalateMetrics(
            source_file_count=source_file_count,
            total_file_count=total_file_count,
            total_lines=total_lines,
            average_lines=average_lines,
            largest_file_path=largest_file_path,
            largest_file_lines=largest_file_lines,
            max_indent_depth=max_indent_depth,
            max_indent_path=max_indent_path,
            longest_function_lines=longest_function_lines,
            longest_function_name=longest_function_name,
            longest_function_path=longest_function_path,
            sampled=sampled,
            inventory="git",
            scanned_file_count=scanned_file_count,
            by_language=by_language,
        ),
    )


def repo_with_history(first_days_ago: int, last_days_ago: int) -> RepoMetrics:
    first = days_ago(first_days_ago)
    last = days_ago(last_days_ago)
    return repo_with_git(
        first_commit_date=first.isoformat(),
        last_commit_date=last.isoformat(),
        first_commit_year=first.year,
        last_commit_year=last.year,
        days_since_last_commit=last_days_ago,
    )


def repo_with_markers(per_kloc: float) -> RepoMetrics:
    total = int(round(per_kloc * BASE_PALATE.total_lines / 1000.0))
    abandonment = replace(
        BASE_ABANDONMENT,
        todo=total,
        fixme=0,
        hack=0,
        xxx=0,
        total=total,
        per_kloc=per_kloc,
        worst_file_path="src/app.py" if total else None,
        worst_file_count=min(total, 3),
    )
    return replace(BASE_METRICS, abandonment=abandonment)


def repo_with_debug_prints(count: int) -> RepoMetrics:
    abandonment = replace(BASE_ABANDONMENT, debug_print_count=count)
    return replace(BASE_METRICS, abandonment=abandonment)


def repo_with_dependencies(ecosystem: str, declared: int) -> RepoMetrics:
    manifest = DependencyManifest(
        ecosystem=ecosystem,
        manifest_path=MANIFEST_PATHS[ecosystem],
        declared_count=declared,
        dev_count=0,
        lockfile_path=LOCKFILE_PATHS[ecosystem],
        locked_count=declared,
        drift=False,
        drift_reason=None,
    )
    structure = StructureMetrics(
        manifests=(manifest,),
        total_declared=declared,
        undeclared=False,
        ecosystems=(ecosystem,),
    )
    return replace(BASE_METRICS, structure=structure)


def repo_with_austerity(declared: int, source_files: int) -> RepoMetrics:
    """A manifest that declares almost nothing, over a stated number of files."""
    manifest = replace(BASE_MANIFEST, declared_count=declared, locked_count=declared)
    return replace(
        repo_with_palate(source_file_count=source_files),
        structure=StructureMetrics(
            manifests=(manifest,),
            total_declared=declared,
            undeclared=False,
            ecosystems=("python",),
        ),
    )


def repo_with_languages(*shares: float) -> RepoMetrics:
    names = ("Python", "JavaScript", "Go", "Rust", "Ruby", "Java")
    shared: list[LanguageShare] = []
    for index, share in enumerate(shares):
        file_count = max(1, int(round(share * 100)))
        shared.append(
            LanguageShare(
                name=names[index],
                file_count=file_count,
                line_count=file_count * 100,
                share=share,
            )
        )
    ordered = tuple(sorted(shared, key=lambda item: (-item.file_count, item.name)))
    terroir = TerroirMetrics(
        languages=ordered,
        primary_language=ordered[0].name if ordered else None,
        frameworks=(),
    )
    return replace(BASE_METRICS, terroir=terroir)


def repo_with_sediment_item(
    kind: str,
    path: str,
    detail: str,
    size_bytes: int,
    file_count: int,
    *,
    vendored_file_count: int = 0,
    vendored_dir_count: int = 0,
    secret_file_count: int = 0,
    os_cruft_count: int = 0,
    large_binary_count: int = 0,
    largest_binary_path: str | None = None,
    largest_binary_bytes: int = 0,
) -> RepoMetrics:
    item = SedimentItem(
        kind=kind,
        path=path,
        detail=detail,
        size_bytes=size_bytes,
        file_count=file_count,
    )
    return replace(
        BASE_METRICS,
        sediment=SedimentMetrics(
            items=(item,),
            vendored_file_count=vendored_file_count,
            vendored_dir_count=vendored_dir_count,
            secret_file_count=secret_file_count,
            os_cruft_count=os_cruft_count,
            large_binary_count=large_binary_count,
            largest_binary_path=largest_binary_path,
            largest_binary_bytes=largest_binary_bytes,
        ),
    )


def worst_metrics() -> RepoMetrics:
    """A repository that trips as many negative bands as the contract allows."""
    first = days_ago(3000)
    last = days_ago(900)
    git = replace(
        BASE_GIT,
        shallow=True,
        first_commit_date=first.isoformat(),
        last_commit_date=last.isoformat(),
        first_commit_year=first.year,
        last_commit_year=last.year,
        commit_count=40,
        fix_commit_count=20,
        fix_ratio=0.5,
        longest_gap_days=600,
        longest_gap_start=days_ago(2000).isoformat(),
        longest_gap_end=days_ago(1400).isoformat(),
        days_since_last_commit=900,
        author_count=1,
        top_author_commits=40,
        top_author_share=1.0,
        last_commit_subject="fix the build",
    )
    terroir = TerroirMetrics(
        languages=(
            LanguageShare(
                name="JavaScript", file_count=6000, line_count=900000, share=1.0
            ),
        ),
        primary_language="JavaScript",
        frameworks=("React",),
    )
    nose = NoseMetrics(
        readme_path=None,
        readme_lines=0,
        readme_bytes=0,
        license_path=None,
        license_name=None,
        gitignore_path=None,
        gitignore_rules=0,
        has_contributing=False,
        has_ci=False,
        has_tests=False,
    )
    palate = PalateMetrics(
        source_file_count=6000,
        total_file_count=20190,
        total_lines=900000,
        average_lines=150.0,
        largest_file_path="src/legacy.js",
        largest_file_lines=2400,
        max_indent_depth=12,
        max_indent_path="src/legacy.js",
        longest_function_lines=400,
        longest_function_name="render",
        longest_function_path="src/legacy.js",
        sampled=True,
        inventory="git",
        scanned_file_count=5000,
        by_language=(
            LanguagePalate(
                name="JavaScript",
                file_count=5000,
                line_count=900000,
                max_indent_depth=12,
                max_indent_path="src/legacy.js",
                largest_file_lines=2400,
                largest_file_path="src/legacy.js",
                longest_function_lines=400,
                longest_function_name="render",
                longest_function_path="src/legacy.js",
                function_detector_ran=True,
            ),
        ),
    )
    # Sampled, so the line totals describe 5,000 files of 6,000.
    coverage = replace(
        BASE_COVERAGE,
        lines_complete=False,
        structural_scan_complete=False,
        function_detector_files=5000,
        attributed_files=6000,
        source_files=6000,
    )
    manifest = DependencyManifest(
        ecosystem="javascript",
        manifest_path="package.json",
        declared_count=320,
        dev_count=90,
        lockfile_path=None,
        locked_count=0,
        drift=True,
        drift_reason="no lockfile",
    )
    structure = StructureMetrics(
        manifests=(manifest,),
        total_declared=320,
        undeclared=False,
        ecosystems=("javascript",),
    )
    abandonment = AbandonmentMetrics(
        todo=1800,
        fixme=600,
        hack=120,
        xxx=40,
        total=2560,
        per_kloc=60.0,
        worst_file_path="src/legacy.js",
        worst_file_count=180,
        debug_print_count=340,
        commented_out_code_lines=2200,
    )
    sediment = SedimentMetrics(
        items=(
            SedimentItem(
                kind="vendored",
                path="node_modules",
                detail="14190 files",
                size_bytes=620000000,
                file_count=14190,
            ),
            SedimentItem(
                kind="large_binary",
                path="assets/demo.mov",
                detail="7.2 MB",
                size_bytes=7549747,
                file_count=1,
            ),
            SedimentItem(
                kind="secret",
                path=".env",
                detail="1 file",
                size_bytes=512,
                file_count=1,
            ),
            SedimentItem(
                kind="os_cruft",
                path=".DS_Store",
                detail="1 file",
                size_bytes=6148,
                file_count=1,
            ),
        ),
        vendored_file_count=14190,
        vendored_dir_count=1,
        secret_file_count=1,
        os_cruft_count=1,
        large_binary_count=1,
        largest_binary_path="assets/demo.mov",
        largest_binary_bytes=7549747,
    )
    return RepoMetrics(
        path="/repos/legacy",
        name="legacy",
        is_git_repo=True,
        is_empty=False,
        git=git,
        terroir=terroir,
        nose=nose,
        palate=palate,
        coverage=coverage,
        structure=structure,
        abandonment=abandonment,
        sediment=sediment,
        dropped=(),
    )


def empty_metrics() -> RepoMetrics:
    git = replace(
        BASE_GIT,
        has_commits=False,
        first_commit_date=None,
        last_commit_date=None,
        first_commit_year=None,
        last_commit_year=None,
        commit_count=0,
        fix_commit_count=0,
        fix_ratio=0.0,
        longest_gap_days=0,
        longest_gap_start=None,
        longest_gap_end=None,
        days_since_last_commit=0,
        author_count=0,
        top_author_name=None,
        top_author_commits=0,
        top_author_share=0.0,
        last_commit_subject=None,
    )
    palate = replace(
        BASE_PALATE,
        source_file_count=0,
        total_file_count=0,
        total_lines=0,
        average_lines=0.0,
        largest_file_path=None,
        largest_file_lines=0,
        max_indent_depth=0,
        max_indent_path=None,
        longest_function_lines=0,
        longest_function_name=None,
        longest_function_path=None,
        inventory="git",
        scanned_file_count=0,
        by_language=(),
    )
    # Nothing to read is not a gap in the reading.
    coverage = replace(
        BASE_COVERAGE,
        function_detector_files=0,
        attributed_files=0,
        source_files=0,
        history_complete=False,
        authorship_measured=False,
    )
    terroir = TerroirMetrics(languages=(), primary_language=None, frameworks=())
    abandonment = replace(
        BASE_ABANDONMENT,
        todo=0,
        fixme=0,
        hack=0,
        xxx=0,
        total=0,
        per_kloc=0.0,
        worst_file_path=None,
        worst_file_count=0,
    )
    return replace(
        BASE_METRICS,
        name="fresh",
        is_empty=True,
        git=git,
        terroir=terroir,
        palate=palate,
        coverage=coverage,
        abandonment=abandonment,
    )


def no_history_metrics() -> RepoMetrics:
    git = replace(
        BASE_GIT,
        is_repo=False,
        has_commits=False,
        first_commit_date=None,
        last_commit_date=None,
        first_commit_year=None,
        last_commit_year=None,
        commit_count=0,
        fix_commit_count=0,
        fix_ratio=0.0,
        longest_gap_days=0,
        longest_gap_start=None,
        longest_gap_end=None,
        days_since_last_commit=0,
        author_count=0,
        top_author_name=None,
        top_author_commits=0,
        top_author_share=0.0,
        last_commit_subject=None,
    )
    coverage = replace(
        BASE_COVERAGE, history_complete=False, authorship_measured=False
    )
    return replace(
        BASE_METRICS,
        name="loose-files",
        is_git_repo=False,
        git=git,
        coverage=coverage,
    )


def spread() -> tuple[tuple[str, RepoMetrics], ...]:
    """A range of repositories from spotless to catastrophic."""
    return (
        ("pristine", BASE_METRICS),
        ("thin readme", repo_with_nose(readme_lines=4, readme_bytes=80)),
        ("no gitignore", repo_with_nose(gitignore_path=None, gitignore_rules=0)),
        ("markers", repo_with_markers(24.0)),
        ("huge file", repo_with_palate(largest_file_lines=1600)),
        ("deep nesting", repo_with_palate(max_indent_depth=11)),
        ("dependency load", repo_with_dependencies("javascript", 240)),
        ("dormant", repo_with_history(2000, 900)),
        ("empty", empty_metrics()),
        ("no history", no_history_metrics()),
        ("worst", worst_metrics()),
    )


def sort_key(finding: Finding) -> tuple[int, int, str]:
    return (COURSES.index(finding.course), -finding.severity, finding.key)


class BandTestCase(unittest.TestCase):
    def keys_for(self, metrics: RepoMetrics) -> dict[str, Finding]:
        return {finding.key: finding for finding in judge(metrics).findings}

    def assert_band(
        self,
        metrics: RepoMetrics,
        *,
        family: Sequence[str],
        expected: str | None,
        note: str,
    ) -> None:
        found = self.keys_for(metrics)
        for key in family:
            if key == expected:
                self.assertIn(key, found, f"{note}: expected {key} to be emitted")
                self.assertEqual(
                    EXPECTED_SEVERITY[key],
                    found[key].severity,
                    f"{note}: wrong severity on {key}",
                )
            else:
                self.assertNotIn(
                    key, found, f"{note}: {key} must not be emitted here"
                )


class AbandonmentBandTests(BandTestCase):
    def test_todo_per_kloc_bands(self) -> None:
        cases: tuple[tuple[float, str | None], ...] = (
            (0.0, "abandonment.suspiciously_clean"),
            (0.25, None),
            (4.9, None),
            (5.0, "abandonment.notes"),
            (12.5, "abandonment.notes"),
            (20.0, "abandonment.notes"),
            (20.1, "abandonment.aggressive"),
            (75.0, "abandonment.aggressive"),
        )
        for per_kloc, expected in cases:
            with self.subTest(per_kloc=per_kloc):
                self.assert_band(
                    repo_with_markers(per_kloc),
                    family=ABANDONMENT_BAND,
                    expected=expected,
                    note=f"todo per kloc {per_kloc}",
                )


class PalateBandTests(BandTestCase):
    def test_largest_file_bands(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (0, None),
            (299, None),
            (300, "palate.full_bodied"),
            (550, "palate.full_bodied"),
            (800, "palate.full_bodied"),
            (801, "palate.cry_for_help"),
            (4000, "palate.cry_for_help"),
        )
        for lines, expected in cases:
            with self.subTest(largest_file_lines=lines):
                self.assert_band(
                    repo_with_palate(largest_file_lines=lines),
                    family=FILE_SIZE_BAND,
                    expected=expected,
                    note=f"largest file {lines} lines",
                )

    def test_indent_depth_bands(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (0, None),
            (5, None),
            (6, "palate.deep_nesting"),
            (8, "palate.deep_nesting"),
            (9, "palate.abyssal"),
            (14, "palate.abyssal"),
        )
        for depth, expected in cases:
            with self.subTest(max_indent_depth=depth):
                self.assert_band(
                    repo_with_palate(max_indent_depth=depth),
                    family=INDENT_BAND,
                    expected=expected,
                    note=f"indent depth {depth}",
                )

    def test_longest_function_bands(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (40, None),
            (100, None),
            (101, "palate.long_function"),
            (900, "palate.long_function"),
        )
        for length, expected in cases:
            with self.subTest(longest_function_lines=length):
                self.assert_band(
                    repo_with_palate(longest_function_lines=length),
                    family=("palate.long_function",),
                    expected=expected,
                    note=f"longest function {length} lines",
                )

    def test_barrel_sample_is_declared(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("palate.sampled",),
            expected=None,
            note="unsampled repository",
        )
        self.assert_band(
            repo_with_palate(
                sampled=True, source_file_count=12000, scanned_file_count=5000
            ),
            family=("palate.sampled",),
            expected="palate.sampled",
            note="sampled repository",
        )

    def test_no_source_files(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("palate.empty",),
            expected=None,
            note="repository with source files",
        )
        self.assert_band(
            empty_metrics(),
            family=("palate.empty",),
            expected="palate.empty",
            note="repository with no source files",
        )

    def test_thin_body_band(self) -> None:
        """The deficient end of the file size axis, against full bodied."""
        cases: tuple[tuple[int, float, str | None], ...] = (
            (24, 19.0, None),
            (25, 20.0, None),
            (25, 19.9, "palate.thin"),
            (400, 4.0, "palate.thin"),
        )
        for files, average, expected in cases:
            with self.subTest(source_files=files, average_lines=average):
                self.assert_band(
                    repo_with_palate(source_file_count=files, average_lines=average),
                    family=("palate.thin",),
                    expected=expected,
                    note=f"{files} files averaging {average} lines",
                )

    def test_flat_band(self) -> None:
        """The deficient end of the nesting axis, against deep and abyssal."""
        cases: tuple[tuple[int, int, str | None], ...] = (
            (24, 0, None),
            (25, 1, None),
            (25, 0, "palate.flat"),
            (309, 0, "palate.flat"),
        )
        for files, depth, expected in cases:
            with self.subTest(source_files=files, max_indent_depth=depth):
                self.assert_band(
                    repo_with_palate(source_file_count=files, max_indent_depth=depth),
                    family=("palate.flat",),
                    expected=expected,
                    note=f"{files} files nesting to depth {depth}",
                )

    def test_flat_and_deep_are_the_same_axis(self) -> None:
        """One nesting finding at a time, whichever end it falls off."""
        keys = self.keys_for(
            repo_with_palate(source_file_count=25, max_indent_depth=0)
        )
        self.assertIn("palate.flat", keys)
        self.assertNotIn("palate.deep_nesting", keys)
        self.assertNotIn("palate.abyssal", keys)


class NoseBandTests(BandTestCase):
    def test_readme_absence_and_thinness(self) -> None:
        missing = repo_with_nose(readme_path=None, readme_lines=0, readme_bytes=0)
        self.assert_band(
            missing,
            family=("nose.no_readme", "nose.thin_readme"),
            expected="nose.no_readme",
            note="no readme",
        )
        cases: tuple[tuple[int, str | None], ...] = (
            (1, "nose.thin_readme"),
            (9, "nose.thin_readme"),
            (10, None),
            (11, None),
        )
        for lines, expected in cases:
            with self.subTest(readme_lines=lines):
                self.assert_band(
                    repo_with_nose(readme_lines=lines, readme_bytes=lines * 40),
                    family=("nose.no_readme", "nose.thin_readme"),
                    expected=expected,
                    note=f"readme of {lines} lines",
                )

    def test_license_absence(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("nose.no_license",),
            expected=None,
            note="licensed repository",
        )
        self.assert_band(
            repo_with_nose(license_path=None, license_name=None),
            family=("nose.no_license",),
            expected="nose.no_license",
            note="unlicensed repository",
        )

    def test_gitignore_absence(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("nose.no_gitignore",),
            expected=None,
            note="repository with a gitignore",
        )
        self.assert_band(
            repo_with_nose(gitignore_path=None, gitignore_rules=0),
            family=("nose.no_gitignore",),
            expected="nose.no_gitignore",
            note="repository without a gitignore",
        )

    def test_tests_absence(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("nose.no_tests",),
            expected=None,
            note="tested repository",
        )
        self.assert_band(
            repo_with_nose(has_tests=False),
            family=("nose.no_tests",),
            expected="nose.no_tests",
            note="untested repository",
        )

    def test_readme_length_is_banded_at_both_ends(self) -> None:
        """Thin at one end, exhaustive at the other, documented in between."""
        cases: tuple[tuple[int, str], ...] = (
            (9, "nose.thin_readme"),
            (10, "nose.documented"),
            (299, "nose.documented"),
            (300, "nose.exhaustive_readme"),
            (790, "nose.exhaustive_readme"),
        )
        for lines, expected in cases:
            with self.subTest(readme_lines=lines):
                self.assert_band(
                    repo_with_nose(readme_lines=lines, readme_bytes=lines * 40),
                    family=(
                        "nose.thin_readme",
                        "nose.documented",
                        "nose.exhaustive_readme",
                    ),
                    expected=expected,
                    note=f"readme of {lines} lines",
                )

    def test_debug_print_band(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (0, None),
            (4, None),
            (5, "nose.debug_prints"),
            (6, "nose.debug_prints"),
            (340, "nose.debug_prints"),
        )
        for count, expected in cases:
            with self.subTest(debug_print_count=count):
                self.assert_band(
                    repo_with_debug_prints(count),
                    family=("nose.debug_prints",),
                    expected=expected,
                    note=f"{count} debug prints",
                )


class StructureBandTests(BandTestCase):
    def test_dependency_bands_per_ecosystem(self) -> None:
        for ecosystem, (tannic_limit, opaque_limit) in DEPENDENCY_LIMITS.items():
            cases: tuple[tuple[int, str | None], ...] = (
                (tannic_limit - 1, None),
                (tannic_limit, None),
                (tannic_limit + 1, "structure.tannic"),
                (opaque_limit, "structure.tannic"),
                (opaque_limit + 1, "structure.opaque"),
                (opaque_limit * 3, "structure.opaque"),
            )
            for declared, expected in cases:
                with self.subTest(ecosystem=ecosystem, declared=declared):
                    self.assert_band(
                        repo_with_dependencies(ecosystem, declared),
                        family=DEPENDENCY_BAND,
                        expected=expected,
                        note=f"{ecosystem} with {declared} dependencies",
                    )

    def test_austere_band(self) -> None:
        """The deficient end of the dependency axis, against tannic and opaque.

        Only asked of a repository large enough that declaring nothing is a
        claim. A four file package with no dependencies has none to declare.
        """
        cases: tuple[tuple[int, int, str | None], ...] = (
            (0, 49, None),
            (1, 50, None),
            (0, 50, "structure.austere"),
            (0, 400, "structure.austere"),
        )
        for declared, files, expected in cases:
            with self.subTest(declared=declared, source_files=files):
                self.assert_band(
                    repo_with_austerity(declared, files),
                    family=("structure.austere",),
                    expected=expected,
                    note=f"{declared} declared across {files} files",
                )

    def test_austere_replaces_the_neutral_opener(self) -> None:
        keys = self.keys_for(repo_with_austerity(0, 50))
        self.assertIn("structure.austere", keys)
        self.assertNotIn("structure.declared", keys)

    def test_undeclared_dependencies(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("structure.undeclared",),
            expected=None,
            note="repository with a manifest",
        )
        bare = replace(
            BASE_METRICS,
            structure=StructureMetrics(
                manifests=(),
                total_declared=0,
                undeclared=True,
                ecosystems=(),
            ),
        )
        self.assert_band(
            bare,
            family=("structure.undeclared",),
            expected="structure.undeclared",
            note="repository without a manifest",
        )

    def test_lockfile_drift(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("structure.drift",),
            expected=None,
            note="manifest agrees with lockfile",
        )
        drifting = replace(
            BASE_METRICS,
            structure=replace(
                BASE_STRUCTURE,
                manifests=(
                    replace(
                        BASE_MANIFEST,
                        lockfile_path=None,
                        locked_count=0,
                        drift=True,
                        drift_reason="no lockfile",
                    ),
                ),
            ),
        )
        self.assert_band(
            drifting,
            family=("structure.drift", "structure.no_lockfile"),
            expected="structure.no_lockfile",
            note="manifest without a lockfile",
        )

    def test_nothing_declared_and_no_lockfile_is_not_drift(self) -> None:
        """Nothing to lock is not a disagreement, it is an empty manifest."""
        unlocked = replace(
            BASE_METRICS,
            structure=replace(
                BASE_STRUCTURE,
                total_declared=0,
                manifests=(
                    replace(
                        BASE_MANIFEST,
                        declared_count=0,
                        lockfile_path=None,
                        locked_count=0,
                        drift=False,
                        drift_reason=None,
                    ),
                ),
            ),
        )
        keys = {finding.key for finding in judge(unlocked).findings}
        self.assertNotIn("structure.drift", keys)
        self.assertNotIn("structure.no_lockfile", keys)


class LabelBandTests(BandTestCase):
    def test_identity_is_always_emitted(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                found = self.keys_for(metrics)
                self.assertIn("label.identity", found)
                self.assertEqual(0, found["label.identity"].severity)

    def test_polyglot_band(self) -> None:
        cases: tuple[tuple[tuple[float, ...], str | None], ...] = (
            ((1.0,), None),
            ((0.6, 0.4), None),
            ((0.4, 0.35, 0.25), None),
            ((0.5, 0.25, 0.21, 0.04), None),
            ((0.5, 0.25, 0.2, 0.05), "label.polyglot"),
            ((0.4, 0.2, 0.2, 0.1, 0.1), "label.polyglot"),
        )
        for shares, expected in cases:
            with self.subTest(shares=shares):
                self.assert_band(
                    repo_with_languages(*shares),
                    family=("label.polyglot",),
                    expected=expected,
                    note=f"language shares {shares}",
                )

    def test_monoculture_band(self) -> None:
        cases: tuple[tuple[tuple[float, ...], str | None], ...] = (
            ((0.6, 0.4), None),
            ((0.94, 0.06), None),
            ((0.95, 0.05), None),
            ((0.96, 0.04), "label.monoculture"),
            ((1.0,), "label.monoculture"),
        )
        for shares, expected in cases:
            with self.subTest(shares=shares):
                self.assert_band(
                    repo_with_languages(*shares),
                    family=("label.monoculture",),
                    expected=expected,
                    note=f"language shares {shares}",
                )

    def test_vendored_sediment(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("label.vendored",),
            expected=None,
            note="no vendored files",
        )
        self.assert_band(
            repo_with_sediment_item(
                "vendored",
                "node_modules",
                "14190 files",
                620000000,
                14190,
                vendored_file_count=14190,
                vendored_dir_count=1,
            ),
            family=("label.vendored",),
            expected="label.vendored",
            note="vendored files committed",
        )

    def test_secret_sediment(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("label.secrets",),
            expected=None,
            note="no tracked secrets",
        )
        self.assert_band(
            repo_with_sediment_item(
                "secret",
                ".env",
                "1 file",
                512,
                1,
                secret_file_count=1,
            ),
            family=("label.secrets",),
            expected="label.secrets",
            note="tracked env file",
        )

    def test_os_cruft_sediment(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("label.os_cruft",),
            expected=None,
            note="no operating system cruft",
        )
        self.assert_band(
            repo_with_sediment_item(
                "os_cruft",
                ".DS_Store",
                "1 file",
                6148,
                1,
                os_cruft_count=1,
            ),
            family=("label.os_cruft",),
            expected="label.os_cruft",
            note="committed DS_Store",
        )

    def test_large_binary_sediment(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("label.large_binary",),
            expected=None,
            note="no large binaries",
        )
        self.assert_band(
            repo_with_sediment_item(
                "large_binary",
                "assets/demo.mov",
                "7.2 MB",
                7549747,
                1,
                large_binary_count=1,
                largest_binary_path="assets/demo.mov",
                largest_binary_bytes=7549747,
            ),
            family=("label.large_binary",),
            expected="label.large_binary",
            note="large binary committed",
        )


class VintageBandTests(BandTestCase):
    def test_history_presence(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=HISTORY_BAND,
            expected=None,
            note="repository with commits",
        )
        self.assert_band(
            no_history_metrics(),
            family=HISTORY_BAND,
            expected="vintage.no_history",
            note="directory that is not a repository",
        )
        self.assert_band(
            empty_metrics(),
            family=HISTORY_BAND,
            expected="vintage.empty",
            note="repository with no commits",
        )

    def test_shallow_clone(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=("vintage.shallow",),
            expected=None,
            note="full clone",
        )
        self.assert_band(
            repo_with_git(shallow=True),
            family=("vintage.shallow",),
            expected="vintage.shallow",
            note="shallow clone",
        )

    def test_first_commit_age_bands(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (7, "vintage.recent"),
            (89, "vintage.recent"),
            (90, None),
            (91, None),
            (1000, None),
            (1830, "vintage.aged"),
            (4000, "vintage.aged"),
        )
        for first_days, expected in cases:
            last_days = min(5, first_days)
            with self.subTest(first_commit_days_ago=first_days):
                self.assert_band(
                    repo_with_history(first_days, last_days),
                    family=AGE_BAND,
                    expected=expected,
                    note=f"first commit {first_days} days ago",
                )


class FinishBandTests(BandTestCase):
    def test_fix_ratio_band(self) -> None:
        cases: tuple[tuple[int, float, str | None], ...] = (
            (10, 0.10, None),
            (29, 0.29, None),
            (30, 0.30, None),
            (31, 0.31, "finish.fix_ratio"),
            (72, 0.72, "finish.fix_ratio"),
        )
        for fix_commits, ratio, expected in cases:
            with self.subTest(fix_ratio=ratio):
                self.assert_band(
                    repo_with_git(
                        commit_count=100,
                        fix_commit_count=fix_commits,
                        fix_ratio=ratio,
                    ),
                    family=("finish.fix_ratio",),
                    expected=expected,
                    note=f"fix ratio {ratio}",
                )

    def test_longest_gap_band(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (0, None),
            (179, None),
            (180, None),
            (181, "finish.the_silence"),
            (900, "finish.the_silence"),
        )
        for gap, expected in cases:
            with self.subTest(longest_gap_days=gap):
                self.assert_band(
                    repo_with_git(longest_gap_days=gap),
                    family=("finish.the_silence",),
                    expected=expected,
                    note=f"longest gap of {gap} days",
                )

    def test_bus_factor_band(self) -> None:
        cases: tuple[tuple[float, int, str | None], ...] = (
            (0.50, 120, None),
            (0.90, 120, None),
            (0.91, 9, None),
            (1.00, 9, None),
            (0.91, 10, "finish.single_estate"),
            (1.00, 400, "finish.single_estate"),
        )
        for share, commits, expected in cases:
            with self.subTest(top_author_share=share, commit_count=commits):
                self.assert_band(
                    repo_with_git(
                        commit_count=commits,
                        fix_commit_count=0,
                        fix_ratio=0.0,
                        author_count=2,
                        top_author_commits=int(round(share * commits)),
                        top_author_share=share,
                    ),
                    family=("finish.single_estate",),
                    expected=expected,
                    note=f"share {share} over {commits} commits",
                )

    def test_crowded_band(self) -> None:
        """The excess end of the authorship axis, against single estate.

        BASE_PALATE holds 4,000 lines, so the threshold of 100 authors per
        thousand lines falls at 400 names in the log.
        """
        cases: tuple[tuple[int, str | None], ...] = (
            (4, None),
            (399, None),
            (400, "finish.crowded"),
            (1656, "finish.crowded"),
        )
        for authors, expected in cases:
            with self.subTest(author_count=authors):
                self.assert_band(
                    repo_with_git(author_count=authors),
                    family=("finish.crowded",),
                    expected=expected,
                    note=f"{authors} authors over 4,000 lines",
                )

    def test_dormancy_band(self) -> None:
        cases: tuple[tuple[int, str | None], ...] = (
            (10, None),
            (364, None),
            (365, None),
            (366, "finish.dormant"),
            (1500, "finish.dormant"),
        )
        for last_days, expected in cases:
            with self.subTest(days_since_last_commit=last_days):
                self.assert_band(
                    repo_with_history(2000, last_days),
                    family=("finish.dormant",),
                    expected=expected,
                    note=f"last commit {last_days} days ago",
                )

    def test_finish_mirrors_history_presence(self) -> None:
        self.assert_band(
            BASE_METRICS,
            family=FINISH_HISTORY_BAND,
            expected=None,
            note="repository with commits",
        )
        self.assert_band(
            no_history_metrics(),
            family=FINISH_HISTORY_BAND,
            expected="finish.no_history",
            note="directory that is not a repository",
        )
        self.assert_band(
            empty_metrics(),
            family=FINISH_HISTORY_BAND,
            expected="finish.void",
            note="repository with no commits",
        )

    def test_abrupt_last_commit_subject(self) -> None:
        cases: tuple[tuple[str, str | None], ...] = (
            ("add caching layer", None),
            ("prefix the header", None),
            ("fixing the parser", None),
            ("fix the parser", "finish.abrupt"),
            ("Fixed the parser", "finish.abrupt"),
            ("fixes the parser", "finish.abrupt"),
            ("hotfix, fix login redirect", "finish.abrupt"),
        )
        for subject, expected in cases:
            with self.subTest(subject=subject):
                self.assert_band(
                    repo_with_git(last_commit_subject=subject),
                    family=("finish.abrupt",),
                    expected=expected,
                    note=f"last commit subject {subject}",
                )


class JudgementShapeTests(unittest.TestCase):
    def test_pristine_repository_carries_only_the_opening_findings(self) -> None:
        """A clean repository still fills every course.

        The opening findings are severity zero and exist so that no course
        renders blank on a repository that did everything right.
        """
        keys = {finding.key for finding in judge(BASE_METRICS).findings}
        self.assertEqual(
            {
                "label.identity",
                "vintage.declared",
                "nose.documented",
                "palate.body",
                "structure.declared",
                "finish.history",
            },
            keys,
        )

    def test_every_course_speaks_on_a_pristine_repository(self) -> None:
        courses = {finding.course for finding in judge(BASE_METRICS).findings}
        self.assertEqual(set(COURSES), courses)

    def test_every_course_speaks_on_the_worst_repository(self) -> None:
        courses = {finding.course for finding in judge(worst_metrics()).findings}
        self.assertEqual(set(COURSES), courses)

    def test_total_severity_is_the_sum_of_findings(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                judgement = judge(metrics)
                total = sum(finding.severity for finding in judgement.findings)
                self.assertEqual(total, judgement.total_severity)

    def test_every_key_is_counted_on_a_declared_dimension(self) -> None:
        self.assertEqual(set(EXPECTED_DIMENSION), set(ALL_KEYS))
        for key, dimension in EXPECTED_DIMENSION.items():
            with self.subTest(key=key):
                self.assertIn(dimension, DIMENSIONS)
                self.assertEqual(dimension, KEY_DIMENSIONS[key])

    def test_findings_are_sorted(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                findings = judge(metrics).findings
                self.assertEqual(tuple(sorted(findings, key=sort_key)), findings)

    def test_findings_are_unique(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                keys = [finding.key for finding in judge(metrics).findings]
                self.assertEqual(len(set(keys)), len(keys))

    def test_findings_use_declared_courses(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                for finding in judge(metrics).findings:
                    self.assertIn(finding.course, COURSES)

    def test_findings_are_declared_in_all_keys(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                for finding in judge(metrics).findings:
                    self.assertIn(finding.key, ALL_KEYS)

    def test_all_keys_matches_the_contract(self) -> None:
        self.assertEqual(set(EXPECTED_SEVERITY), set(ALL_KEYS))

    def test_severities_match_the_contract(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                for finding in judge(metrics).findings:
                    self.assertEqual(
                        EXPECTED_SEVERITY[finding.key],
                        finding.severity,
                        f"{finding.key} carries the wrong severity",
                    )

    def test_findings_supply_every_declared_fact(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                for finding in judge(metrics).findings:
                    for fact in KEY_FACTS[finding.key]:
                        self.assertIn(
                            fact,
                            finding.facts,
                            f"{finding.key} is missing the fact {fact}",
                        )
                    for name, value in finding.facts.items():
                        self.assertIsInstance(
                            value,
                            Fact,
                            f"{finding.key}.{name} is not a typed fact",
                        )
                        self.assertIsInstance(value.written(), str)

    def test_every_fact_names_a_measurement_with_one_unit(self) -> None:
        """A quantity is written the same way wherever it is cited.

        This is the structural half of the promise that a card never prints
        one number at two precisions. The other half is plan.py refusing to
        say a measurement twice, and it can only rely on the identity if the
        identity is stable.
        """
        for name, metrics in spread():
            with self.subTest(case=name):
                for finding in judge(metrics).findings:
                    for fact in finding.facts.values():
                        if fact.measurement.startswith("absent:"):
                            continue
                        self.assertIn(
                            fact.measurement,
                            MEASUREMENTS,
                            f"{finding.key} cites an unregistered measurement",
                        )
                        self.assertIn(fact.unit, UNITS)

    def test_a_measurement_written_twice_agrees_with_itself(self) -> None:
        """One finding may write one measurement twice, in exactly three ways.

        A count and the same count with its noun. A date and the year inside
        it. A day count and the same span in years, which the template signposts
        as a conversion. Anything else is a measurement disagreeing with itself
        inside a single sentence, which is the defect the typed facts exist to
        make impossible rather than merely unlikely.
        """
        nouned = ({COUNT, COMMITS}, {COUNT, AUTHORS}, {COUNT, DIRECTORIES})
        for name, metrics in spread():
            with self.subTest(case=name):
                for finding in judge(metrics).findings:
                    written: dict[str, dict[str, str]] = {}
                    for fact in finding.facts.values():
                        written.setdefault(fact.measurement, {})[fact.unit] = (
                            fact.written()
                        )
                    for measurement, seen in written.items():
                        if len(seen) < 2:
                            continue
                        units = set(seen)
                        label = f"{finding.key} writes {measurement} as {seen}"
                        if units in nouned:
                            plain, *_ = seen[COUNT].split(" ")
                            self.assertTrue(
                                seen[units.difference({COUNT}).pop()].startswith(
                                    plain
                                ),
                                label,
                            )
                        elif units == {DATE, YEAR}:
                            self.assertTrue(seen[DATE].startswith(seen[YEAR]), label)
                        else:
                            self.assertEqual({DAYS, YEARS}, units, label)

    def test_judgement_survives_a_bare_directory(self) -> None:
        judgement = judge(empty_metrics())
        self.assertIsNone(judgement.score)
        self.assertEqual("no_source_files", judgement.refusal)
        self.assertTrue(judgement.findings)

    def test_every_refusal_code_declares_its_facts(self) -> None:
        self.assertEqual(set(REFUSALS), set(REFUSAL_FACTS))
        for code in REFUSALS:
            with self.subTest(code=code):
                self.assertTrue(REFUSAL_FACTS[code], f"{code} declares no facts")

    def test_refusal_facts_are_complete_when_a_refusal_fires(self) -> None:
        judgement = judge(empty_metrics())
        assert judgement.refusal is not None
        for fact in REFUSAL_FACTS[judgement.refusal]:
            self.assertIn(fact, judgement.refusal_facts)

    def test_gate_names_are_the_declared_ones(self) -> None:
        for name, metrics in spread():
            with self.subTest(case=name):
                judgement = judge(metrics)
                self.assertEqual(
                    BASE_GATES, tuple(gate.name for gate in judgement.gates)
                )
                self.assertEqual(
                    CARE_GATES, tuple(gate.name for gate in judgement.care_gates)
                )

    def test_bands_table_is_contiguous_and_ordered(self) -> None:
        bands = BANDS["score_bands"]
        assert isinstance(bands, tuple)
        # Listed from the top down, and every band abuts the next.
        edges = [(entry[1], entry[2]) for entry in bands]
        for low, high in edges:
            self.assertLessEqual(low, high)
        for (upper_low, _), (_, lower_high) in zip(edges, edges[1:]):
            self.assertEqual(upper_low - 1, lower_high, "the bands leave a gap")


if __name__ == "__main__":
    unittest.main()
