"""Tests for sommelier.collect against synthetic repositories."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import ClassVar
from unittest import mock

from sommelier.collect import (
    BINARY_SNIFF_BYTES,
    LanguagePalate,
    MAX_LINE_CHARS,
    RepoMetrics,
    TastingError,
    _FileRecord,
    _is_secret_name,
    _is_source,
    collect,
)
from tests import fixtures


def _assert_optional_str(case: unittest.TestCase, value: str | None) -> None:
    if value is not None:
        case.assertIsInstance(value, str)


def _assert_relative_posix(case: unittest.TestCase, value: str | None) -> None:
    if value is None:
        return
    case.assertIsInstance(value, str)
    case.assertNotIn("\\", value)
    case.assertFalse(value.startswith("/"))
    case.assertFalse(Path(value).is_absolute())


def assert_full_metrics(case: unittest.TestCase, metrics: RepoMetrics) -> None:
    """Assert that every field of a RepoMetrics is present and well typed."""
    case.assertIsInstance(metrics, RepoMetrics)
    case.assertIsInstance(metrics.path, str)
    case.assertTrue(Path(metrics.path).is_absolute())
    case.assertIsInstance(metrics.name, str)
    case.assertIsInstance(metrics.is_git_repo, bool)
    case.assertIsInstance(metrics.is_empty, bool)

    git = metrics.git
    case.assertIsInstance(git.is_repo, bool)
    case.assertIsInstance(git.has_commits, bool)
    case.assertIsInstance(git.shallow, bool)
    _assert_optional_str(case, git.first_commit_date)
    _assert_optional_str(case, git.last_commit_date)
    _assert_optional_str(case, git.longest_gap_start)
    _assert_optional_str(case, git.longest_gap_end)
    _assert_optional_str(case, git.top_author_name)
    _assert_optional_str(case, git.last_commit_subject)
    case.assertIsInstance(git.commit_count, int)
    case.assertIsInstance(git.fix_commit_count, int)
    case.assertIsInstance(git.fix_ratio, float)
    case.assertIsInstance(git.longest_gap_days, int)
    case.assertIsInstance(git.days_since_last_commit, int)
    case.assertIsInstance(git.author_count, int)
    case.assertIsInstance(git.top_author_commits, int)
    case.assertIsInstance(git.top_author_share, float)
    case.assertGreaterEqual(git.commit_count, 0)
    case.assertGreaterEqual(git.fix_ratio, 0.0)
    case.assertLessEqual(git.fix_ratio, 1.0)
    case.assertGreaterEqual(git.top_author_share, 0.0)
    case.assertLessEqual(git.top_author_share, 1.0)

    terroir = metrics.terroir
    case.assertIsInstance(terroir.languages, tuple)
    for language in terroir.languages:
        case.assertIsInstance(language.name, str)
        case.assertIsInstance(language.file_count, int)
        case.assertIsInstance(language.line_count, int)
        case.assertIsInstance(language.share, float)
    case.assertEqual(
        list(terroir.languages),
        sorted(terroir.languages, key=lambda item: (-item.file_count, item.name)),
    )
    _assert_optional_str(case, terroir.primary_language)
    case.assertIsInstance(terroir.frameworks, tuple)
    case.assertEqual(list(terroir.frameworks), sorted(terroir.frameworks))

    nose = metrics.nose
    _assert_relative_posix(case, nose.readme_path)
    _assert_relative_posix(case, nose.license_path)
    _assert_relative_posix(case, nose.gitignore_path)
    _assert_optional_str(case, nose.license_name)
    case.assertIsInstance(nose.readme_lines, int)
    case.assertIsInstance(nose.readme_bytes, int)
    case.assertIsInstance(nose.gitignore_rules, int)
    case.assertIsInstance(nose.has_contributing, bool)
    case.assertIsInstance(nose.has_ci, bool)
    case.assertIsInstance(nose.has_tests, bool)

    palate = metrics.palate
    case.assertIsInstance(palate.source_file_count, int)
    case.assertIsInstance(palate.total_file_count, int)
    case.assertIsInstance(palate.total_lines, int)
    case.assertIsInstance(palate.average_lines, float)
    _assert_relative_posix(case, palate.largest_file_path)
    _assert_relative_posix(case, palate.max_indent_path)
    _assert_relative_posix(case, palate.longest_function_path)
    _assert_optional_str(case, palate.longest_function_name)
    case.assertIsInstance(palate.largest_file_lines, int)
    case.assertIsInstance(palate.max_indent_depth, int)
    case.assertIsInstance(palate.longest_function_lines, int)
    case.assertIsInstance(palate.sampled, bool)
    case.assertIsInstance(palate.scanned_file_count, int)
    case.assertLessEqual(palate.source_file_count, palate.total_file_count)

    case.assertIsInstance(palate.by_language, tuple)
    for language_palate in palate.by_language:
        case.assertIsInstance(language_palate.name, str)
        case.assertIsInstance(language_palate.file_count, int)
        case.assertIsInstance(language_palate.line_count, int)
        case.assertIsInstance(language_palate.max_indent_depth, int)
        case.assertIsInstance(language_palate.largest_file_lines, int)
        case.assertIsInstance(language_palate.longest_function_lines, int)
        case.assertIsInstance(language_palate.function_detector_ran, bool)
        _assert_relative_posix(case, language_palate.max_indent_path)
        _assert_relative_posix(case, language_palate.largest_file_path)
        _assert_relative_posix(case, language_palate.longest_function_path)
        _assert_optional_str(case, language_palate.longest_function_name)
    case.assertEqual(
        list(palate.by_language),
        sorted(palate.by_language, key=lambda item: (-item.file_count, item.name)),
    )
    case.assertEqual(
        len({item.name for item in palate.by_language}),
        len(palate.by_language),
        "a language may appear once",
    )
    # The split has to add back up to the whole, or one of the two is wrong.
    case.assertEqual(
        sum(item.file_count for item in palate.by_language),
        palate.scanned_file_count,
    )
    case.assertEqual(
        sum(item.line_count for item in palate.by_language),
        palate.total_lines,
    )
    case.assertEqual(
        max((item.largest_file_lines for item in palate.by_language), default=0),
        palate.largest_file_lines,
    )
    case.assertEqual(
        max((item.max_indent_depth for item in palate.by_language), default=0),
        palate.max_indent_depth,
    )
    case.assertEqual(
        max((item.longest_function_lines for item in palate.by_language), default=0),
        palate.longest_function_lines,
    )

    coverage = metrics.coverage
    case.assertIsInstance(coverage.lines_complete, bool)
    case.assertIsInstance(coverage.truncated_files, int)
    case.assertIsInstance(coverage.structural_scan_complete, bool)
    case.assertIsInstance(coverage.function_detector_files, int)
    case.assertIsInstance(coverage.attributed_files, int)
    case.assertIsInstance(coverage.source_files, int)
    case.assertIsInstance(coverage.history_complete, bool)
    case.assertIsInstance(coverage.authorship_measured, bool)
    case.assertIsInstance(coverage.dependencies_measured, bool)
    case.assertGreaterEqual(coverage.truncated_files, 0)
    case.assertEqual(coverage.source_files, palate.source_file_count)
    case.assertLessEqual(coverage.attributed_files, coverage.source_files)
    case.assertLessEqual(coverage.function_detector_files, palate.scanned_file_count)
    case.assertEqual(
        coverage.function_detector_files,
        sum(
            item.file_count
            for item in palate.by_language
            if item.function_detector_ran
        ),
    )
    if coverage.truncated_files > 0:
        case.assertFalse(coverage.lines_complete)
    if not coverage.lines_complete:
        case.assertFalse(coverage.structural_scan_complete)

    structure = metrics.structure
    case.assertIsInstance(structure.manifests, tuple)
    for manifest in structure.manifests:
        case.assertIsInstance(manifest.ecosystem, str)
        _assert_relative_posix(case, manifest.manifest_path)
        _assert_relative_posix(case, manifest.lockfile_path)
        case.assertIsInstance(manifest.declared_count, int)
        case.assertIsInstance(manifest.dev_count, int)
        case.assertIsInstance(manifest.locked_count, int)
        case.assertIsInstance(manifest.drift, bool)
        _assert_optional_str(case, manifest.drift_reason)
    case.assertEqual(
        list(structure.manifests),
        sorted(structure.manifests, key=lambda item: item.manifest_path),
    )
    case.assertIsInstance(structure.total_declared, int)
    case.assertIsInstance(structure.undeclared, bool)
    case.assertIsInstance(structure.ecosystems, tuple)

    abandonment = metrics.abandonment
    case.assertIsInstance(abandonment.todo, int)
    case.assertIsInstance(abandonment.fixme, int)
    case.assertIsInstance(abandonment.hack, int)
    case.assertIsInstance(abandonment.xxx, int)
    case.assertIsInstance(abandonment.total, int)
    case.assertIsInstance(abandonment.per_kloc, float)
    _assert_relative_posix(case, abandonment.worst_file_path)
    case.assertIsInstance(abandonment.worst_file_count, int)
    case.assertIsInstance(abandonment.debug_print_count, int)
    case.assertIsInstance(abandonment.commented_out_code_lines, int)

    sediment = metrics.sediment
    case.assertIsInstance(sediment.items, tuple)
    for item in sediment.items:
        case.assertIn(
            item.kind,
            {"vendored", "secret", "os_cruft", "large_binary", "editor"},
        )
        _assert_relative_posix(case, item.path)
        case.assertIsInstance(item.detail, str)
        case.assertIsInstance(item.size_bytes, int)
        case.assertIsInstance(item.file_count, int)
    case.assertEqual(
        list(sediment.items),
        sorted(sediment.items, key=lambda item: (-item.size_bytes, item.path)),
    )
    case.assertIsInstance(sediment.vendored_file_count, int)
    case.assertIsInstance(sediment.vendored_dir_count, int)
    case.assertIsInstance(sediment.secret_file_count, int)
    case.assertIsInstance(sediment.os_cruft_count, int)
    case.assertIsInstance(sediment.large_binary_count, int)
    _assert_relative_posix(case, sediment.largest_binary_path)
    case.assertIsInstance(sediment.largest_binary_bytes, int)

    case.assertIsInstance(metrics.dropped, tuple)
    for dropped in metrics.dropped:
        case.assertIsInstance(dropped.name, str)
        case.assertIn(
            dropped.reason,
            {"exceeded time budget", "unreadable", "git unavailable"},
        )


class HealthyPythonRepoTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        fixtures.require_git()
        cls.fixture = fixtures.healthy_python_repo()
        cls.metrics = collect(cls.fixture.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_identity(self) -> None:
        self.assertEqual(self.metrics.path, str(self.fixture.path))
        self.assertEqual(self.metrics.name, fixtures.HEALTHY_NAME)
        self.assertTrue(self.metrics.is_git_repo)
        self.assertFalse(self.metrics.is_empty)

    def test_both_ends_of_the_git_log(self) -> None:
        git = self.metrics.git
        self.assertTrue(git.is_repo)
        self.assertTrue(git.has_commits)
        self.assertFalse(git.shallow)
        self.assertEqual(git.first_commit_date, fixtures.HEALTHY_FIRST_DAY)
        self.assertEqual(git.last_commit_date, fixtures.HEALTHY_LAST_DAY)
        self.assertEqual(git.first_commit_year, 2021)
        self.assertEqual(git.last_commit_year, 2022)

    def test_commit_and_fix_counts(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.commit_count, fixtures.HEALTHY_COMMIT_COUNT)
        self.assertEqual(git.fix_commit_count, fixtures.HEALTHY_FIX_COMMIT_COUNT)
        self.assertAlmostEqual(git.fix_ratio, 0.25, places=6)

    def test_longest_gap(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.longest_gap_days, fixtures.HEALTHY_LONGEST_GAP_DAYS)
        self.assertEqual(git.longest_gap_start, fixtures.HEALTHY_SECOND_DAY)
        self.assertEqual(git.longest_gap_end, fixtures.HEALTHY_THIRD_DAY)

    def test_bus_factor(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.author_count, 2)
        self.assertEqual(git.top_author_name, fixtures.ADA_NAME)
        self.assertEqual(git.top_author_commits, 3)
        self.assertAlmostEqual(git.top_author_share, 0.75, places=6)

    def test_last_commit_subject_and_age(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.last_commit_subject, fixtures.HEALTHY_LAST_SUBJECT)
        expected = (date.today() - date(2022, 1, 20)).days
        self.assertEqual(git.days_since_last_commit, expected)

    def test_nose_finds_every_document(self) -> None:
        nose = self.metrics.nose
        self.assertEqual(nose.readme_path, "README.md")
        self.assertGreaterEqual(nose.readme_lines, fixtures.HEALTHY_README_LINES)
        self.assertLessEqual(nose.readme_lines, fixtures.HEALTHY_README_LINES + 1)
        self.assertGreater(nose.readme_bytes, 100)
        self.assertEqual(nose.license_path, "LICENSE")
        self.assertEqual(nose.license_name, "MIT")
        self.assertEqual(nose.gitignore_path, ".gitignore")
        self.assertEqual(nose.gitignore_rules, fixtures.HEALTHY_GITIGNORE_RULES)
        self.assertTrue(nose.has_contributing)
        self.assertTrue(nose.has_ci)
        self.assertTrue(nose.has_tests)

    def test_palate(self) -> None:
        palate = self.metrics.palate
        self.assertEqual(palate.largest_file_path, fixtures.HEALTHY_LARGEST_FILE)
        self.assertGreaterEqual(palate.source_file_count, 4)
        self.assertGreater(palate.total_lines, 0)
        self.assertFalse(palate.sampled)
        self.assertGreater(palate.scanned_file_count, 0)
        self.assertLessEqual(palate.scanned_file_count, palate.total_file_count)
        self.assertAlmostEqual(
            palate.average_lines,
            palate.total_lines / palate.scanned_file_count,
            places=3,
        )
        self.assertLess(palate.max_indent_depth, 6)

    def test_terroir(self) -> None:
        terroir = self.metrics.terroir
        self.assertEqual(terroir.primary_language, "Python")
        python = [item for item in terroir.languages if item.name == "Python"]
        self.assertEqual(len(python), 1)
        self.assertEqual(python[0].file_count, 4)
        self.assertGreater(python[0].share, 0.4)
        self.assertLessEqual(python[0].share, 1.0)

    def test_requirements_txt_dependency_count(self) -> None:
        structure = self.metrics.structure
        self.assertFalse(structure.undeclared)
        self.assertEqual(len(structure.manifests), 1)
        manifest = structure.manifests[0]
        self.assertEqual(manifest.ecosystem, "python")
        self.assertEqual(manifest.manifest_path, "requirements.txt")
        self.assertEqual(manifest.declared_count, fixtures.HEALTHY_REQUIREMENT_COUNT)
        self.assertEqual(manifest.dev_count, 0)
        self.assertIsNone(manifest.lockfile_path)
        self.assertEqual(structure.total_declared, fixtures.HEALTHY_REQUIREMENT_COUNT)
        self.assertEqual(structure.ecosystems, ("python",))

    def test_abandonment_is_clean(self) -> None:
        abandonment = self.metrics.abandonment
        self.assertEqual(abandonment.todo, 0)
        self.assertEqual(abandonment.fixme, 0)
        self.assertEqual(abandonment.hack, 0)
        self.assertEqual(abandonment.xxx, 0)
        self.assertEqual(abandonment.total, 0)
        self.assertEqual(abandonment.per_kloc, 0.0)
        self.assertIsNone(abandonment.worst_file_path)
        self.assertEqual(abandonment.worst_file_count, 0)
        self.assertEqual(abandonment.debug_print_count, 0)

    def test_sediment_is_empty_and_git_is_not_a_sin(self) -> None:
        sediment = self.metrics.sediment
        self.assertEqual(sediment.items, ())
        self.assertEqual(sediment.vendored_file_count, 0)
        self.assertEqual(sediment.vendored_dir_count, 0)
        self.assertEqual(sediment.secret_file_count, 0)
        self.assertEqual(sediment.os_cruft_count, 0)
        self.assertEqual(sediment.large_binary_count, 0)
        self.assertIsNone(sediment.largest_binary_path)
        self.assertEqual(sediment.largest_binary_bytes, 0)

    def test_collect_is_deterministic(self) -> None:
        again = collect(self.fixture.path)
        self.assertEqual(again, self.metrics)

    def test_budget_keyword_is_accepted(self) -> None:
        metrics = collect(self.fixture.path, budget_seconds=30.0)
        self.assertEqual(metrics.name, fixtures.HEALTHY_NAME)


class NeglectedJavaScriptRepoTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        fixtures.require_git()
        cls.fixture = fixtures.neglected_js_repo()
        cls.metrics = collect(cls.fixture.path, budget_seconds=60.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_both_ends_of_the_git_log(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.first_commit_date, fixtures.NEGLECTED_FIRST_DAY)
        self.assertEqual(git.last_commit_date, fixtures.NEGLECTED_LAST_DAY)
        self.assertEqual(git.first_commit_year, 2019)
        self.assertEqual(git.last_commit_year, 2019)

    def test_commit_and_fix_counts(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.commit_count, fixtures.NEGLECTED_COMMIT_COUNT)
        self.assertEqual(git.fix_commit_count, 1)
        self.assertAlmostEqual(git.fix_ratio, 1.0 / 3.0, places=4)

    def test_longest_gap(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.longest_gap_days, fixtures.NEGLECTED_LONGEST_GAP_DAYS)
        self.assertEqual(git.longest_gap_start, fixtures.NEGLECTED_SECOND_DAY)
        self.assertEqual(git.longest_gap_end, fixtures.NEGLECTED_LAST_DAY)

    def test_bus_factor_is_one(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.author_count, 1)
        self.assertEqual(git.top_author_name, fixtures.DANA_NAME)
        self.assertEqual(git.top_author_commits, fixtures.NEGLECTED_COMMIT_COUNT)
        self.assertAlmostEqual(git.top_author_share, 1.0, places=6)

    def test_dormancy(self) -> None:
        git = self.metrics.git
        self.assertEqual(git.last_commit_subject, fixtures.NEGLECTED_LAST_SUBJECT)
        expected = (date.today() - date(2019, 11, 3)).days
        self.assertEqual(git.days_since_last_commit, expected)
        self.assertGreater(git.days_since_last_commit, 365)

    def test_vendored_code_is_excluded_from_the_palate(self) -> None:
        palate = self.metrics.palate
        for path in (
            palate.largest_file_path,
            palate.max_indent_path,
            palate.longest_function_path,
        ):
            if path is not None:
                self.assertFalse(path.startswith("node_modules"))
        self.assertLess(palate.source_file_count, 20)
        self.assertGreaterEqual(
            palate.total_file_count,
            palate.source_file_count + fixtures.NEGLECTED_VENDORED_FILES,
        )

    def test_vendored_code_is_reported_as_sediment(self) -> None:
        sediment = self.metrics.sediment
        self.assertEqual(sediment.vendored_file_count, fixtures.NEGLECTED_VENDORED_FILES)
        self.assertEqual(sediment.vendored_dir_count, 1)
        vendored = [item for item in sediment.items if item.kind == "vendored"]
        self.assertEqual(len(vendored), 1)
        self.assertEqual(vendored[0].path, "node_modules")
        self.assertEqual(vendored[0].file_count, fixtures.NEGLECTED_VENDORED_FILES)
        self.assertGreater(vendored[0].size_bytes, 0)

    def test_env_file_is_detected(self) -> None:
        sediment = self.metrics.sediment
        self.assertEqual(sediment.secret_file_count, 1)
        secrets = [item for item in sediment.items if item.kind == "secret"]
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets[0].path, ".env")

    def test_os_cruft_and_large_binary(self) -> None:
        sediment = self.metrics.sediment
        self.assertEqual(sediment.os_cruft_count, fixtures.NEGLECTED_OS_CRUFT)
        self.assertEqual(sediment.large_binary_count, 1)
        self.assertEqual(sediment.largest_binary_path, fixtures.NEGLECTED_BINARY_PATH)
        self.assertEqual(sediment.largest_binary_bytes, fixtures.NEGLECTED_BINARY_BYTES)
        kinds = {item.kind for item in sediment.items}
        self.assertEqual(kinds, {"vendored", "secret", "os_cruft", "large_binary"})

    def test_todo_density(self) -> None:
        abandonment = self.metrics.abandonment
        self.assertEqual(abandonment.todo, fixtures.NEGLECTED_TODO_COUNT)
        self.assertEqual(abandonment.fixme, fixtures.NEGLECTED_FIXME_COUNT)
        self.assertEqual(abandonment.hack, fixtures.NEGLECTED_HACK_COUNT)
        self.assertEqual(abandonment.xxx, fixtures.NEGLECTED_XXX_COUNT)
        self.assertEqual(abandonment.total, fixtures.NEGLECTED_MARKER_TOTAL)
        self.assertEqual(abandonment.worst_file_path, fixtures.NEGLECTED_LEGACY_PATH)
        self.assertEqual(abandonment.worst_file_count, fixtures.NEGLECTED_LEGACY_TODOS)
        self.assertEqual(abandonment.debug_print_count, fixtures.NEGLECTED_DEBUG_PRINTS)
        self.assertGreaterEqual(abandonment.commented_out_code_lines, 2)
        expected = abandonment.total / (self.metrics.palate.total_lines / 1000.0)
        self.assertAlmostEqual(abandonment.per_kloc, expected, places=2)
        self.assertGreater(abandonment.per_kloc, 20.0)

    def test_largest_file(self) -> None:
        palate = self.metrics.palate
        self.assertEqual(palate.largest_file_path, fixtures.NEGLECTED_LEGACY_PATH)
        self.assertGreaterEqual(palate.largest_file_lines, fixtures.NEGLECTED_LEGACY_LINES)
        self.assertLessEqual(palate.largest_file_lines, fixtures.NEGLECTED_LEGACY_LINES + 1)

    def test_package_json_dependency_counts(self) -> None:
        structure = self.metrics.structure
        self.assertFalse(structure.undeclared)
        self.assertEqual(len(structure.manifests), 1)
        manifest = structure.manifests[0]
        self.assertEqual(manifest.ecosystem, "javascript")
        self.assertEqual(manifest.manifest_path, "package.json")
        self.assertEqual(manifest.declared_count, fixtures.NEGLECTED_DEPENDENCIES)
        self.assertEqual(manifest.dev_count, fixtures.NEGLECTED_DEV_DEPENDENCIES)
        self.assertIsNone(manifest.lockfile_path)
        self.assertEqual(manifest.locked_count, 0)
        self.assertTrue(manifest.drift)
        self.assertEqual(manifest.drift_reason, "no lockfile")
        self.assertEqual(structure.ecosystems, ("javascript",))

    def test_terroir_ignores_vendored_javascript(self) -> None:
        terroir = self.metrics.terroir
        self.assertEqual(terroir.primary_language, "JavaScript")
        javascript = [item for item in terroir.languages if item.name == "JavaScript"]
        self.assertEqual(len(javascript), 1)
        self.assertEqual(javascript[0].file_count, 3)

    def test_nose_records_the_absences(self) -> None:
        nose = self.metrics.nose
        self.assertIsNone(nose.readme_path)
        self.assertEqual(nose.readme_lines, 0)
        self.assertIsNone(nose.license_path)
        self.assertIsNone(nose.gitignore_path)
        self.assertEqual(nose.gitignore_rules, 0)
        self.assertFalse(nose.has_contributing)
        self.assertFalse(nose.has_ci)
        self.assertFalse(nose.has_tests)


class TestDirectoryTest(unittest.TestCase):
    """A directory named tests is not a test suite until something is in it.

    The tested gate is one of the seven that admit a repository to the
    nineties, and it is supposed to cost the author real work. An empty
    directory costs one command, and emptying a real one used to leave the
    answer unchanged, which made removing the tests free.
    """

    def test_an_empty_test_directory_is_not_a_test_suite(self) -> None:
        with fixtures.Fixture("hollow") as fixture:
            fixtures.write_tree(fixture.path, {"src/app.py": "VALUE = 1\n"})
            (fixture.path / "tests").mkdir()
            self.assertFalse(collect(fixture.path).nose.has_tests)

    def test_a_populated_test_directory_is_one(self) -> None:
        with fixtures.Fixture("populated") as fixture:
            fixtures.write_tree(
                fixture.path,
                {"src/app.py": "VALUE = 1\n", "tests/cases.py": "CASES = ()\n"},
            )
            self.assertTrue(collect(fixture.path).nose.has_tests)

    def test_a_test_directory_counts_on_a_file_nested_inside_it(self) -> None:
        with fixtures.Fixture("nested") as fixture:
            fixtures.write_tree(
                fixture.path,
                {
                    "src/app.py": "VALUE = 1\n",
                    "tests/unit/cases.py": "CASES = ()\n",
                },
            )
            self.assertTrue(collect(fixture.path).nose.has_tests)

    def test_emptying_a_test_directory_removes_the_evidence(self) -> None:
        with fixtures.Fixture("emptied") as fixture:
            fixtures.write_tree(
                fixture.path,
                {"src/app.py": "VALUE = 1\n", "tests/cases.py": "CASES = ()\n"},
            )
            self.assertTrue(collect(fixture.path).nose.has_tests)
            (fixture.path / "tests" / "cases.py").unlink()
            self.assertFalse(collect(fixture.path).nose.has_tests)


class ContainmentTest(unittest.TestCase):
    """The tool tastes the path it is handed and nothing above it."""

    def test_a_subdirectory_does_not_inherit_the_parent_history(self) -> None:
        fixtures.require_git()
        with fixtures.Fixture("parent") as fixture:
            fixtures.write_tree(
                fixture.path, {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"}
            )
            fixtures.git_init(fixture.path)
            fixtures.git_commit(fixture.path, "add everything", day="2024-03-01")
            root = collect(fixture.path)
            inner = collect(fixture.path / "pkg")
        self.assertTrue(root.git.is_repo)
        self.assertGreater(root.git.commit_count, 0)
        self.assertFalse(inner.git.is_repo)
        self.assertEqual(inner.git.commit_count, 0)
        self.assertEqual(inner.palate.source_file_count, 1)

    def test_symlinks_out_of_the_tree_are_not_followed(self) -> None:
        with fixtures.Fixture("linked") as fixture:
            outside = fixture.path.parent / "outside"
            outside.mkdir(exist_ok=True)
            (outside / ".env").write_text("SECRET=1\n", encoding="utf-8")
            (outside / "big.py").write_text("x = 1\n" * 500, encoding="utf-8")
            fixtures.write_tree(fixture.path, {"a.py": "y = 1\n"})
            try:
                (fixture.path / "link_dir").symlink_to(outside)
                (fixture.path / "link_file").symlink_to(outside / "big.py")
            except OSError:
                self.skipTest("symlinks unavailable")
            metrics = collect(fixture.path)
        self.assertEqual(metrics.palate.source_file_count, 1)
        self.assertEqual(metrics.sediment.secret_file_count, 0)


class FalsePositiveTest(unittest.TestCase):
    """Claims the card states with conviction had better be true.

    Both cases here were found on psf/requests, where the tool reported the
    max nesting depth of a 2.1 MB Adobe Illustrator logo and called the
    expired certificates of an HTTPS test suite committed secrets.
    """

    def test_vector_and_page_formats_are_not_source(self) -> None:
        for name in ("logo.ai", "figure.eps", "print.ps", "part.stl", "ui.psd"):
            with self.subTest(name=name):
                record = _FileRecord(
                    rel=f"ext/{name}",
                    name=name,
                    ext=Path(name).suffix,
                    size=2_100_000,
                    depth=1,
                    language=None,
                )
                self.assertFalse(_is_source(record))

    def test_an_unknown_code_extension_is_still_source(self) -> None:
        """The exclusions must not undo the universality guarantee."""
        record = _FileRecord(
            rel="thing.zzz", name="thing.zzz", ext=".zzz", size=100,
            depth=0, language=None,
        )
        self.assertTrue(_is_source(record))

    def test_certificates_under_a_test_tree_are_fixtures(self) -> None:
        fixtures.require_git()
        files = {
            "main.py": "x = 1\n",
            "tests/certs/valid/server/server.pem": "----- FAKE -----\n",
            "tests/certs/expired/ca.pem": "----- FAKE -----\n",
            "testdata/client.key": "----- FAKE -----\n",
            "spec/fixtures/id_rsa": "----- FAKE -----\n",
        }
        with fixtures.Fixture("certs") as fixture:
            fixtures.write_tree(fixture.path, files)
            fixtures.git_init(fixture.path)
            fixtures.git_commit(fixture.path, "add suite", day="2024-03-01")
            sediment = collect(fixture.path).sediment
        self.assertEqual(sediment.secret_file_count, 0)

    def test_a_real_leaked_secret_is_still_caught(self) -> None:
        """The fixture carve-out must not blind the detector everywhere else."""
        fixtures.require_git()
        files = {"main.py": "x = 1\n", ".env": "TOKEN=1\n", "deploy/server.pem": "K\n"}
        with fixtures.Fixture("leak") as fixture:
            fixtures.write_tree(fixture.path, files)
            fixtures.git_init(fixture.path)
            fixtures.git_commit(fixture.path, "add leak", day="2024-03-01")
            sediment = collect(fixture.path).sediment
        self.assertEqual(sediment.secret_file_count, 2)


class FileInventoryTest(unittest.TestCase):
    """The file inventory asks git what belongs to the project.

    Body, largest file, nesting depth and marker density all describe the code
    the author wrote. Generated output that git has been told to ignore is not
    that, however much of it is sitting on disk.
    """

    def _repo(self, files: dict[str, str], *, commit: bool = True) -> fixtures.Fixture:
        fixture = fixtures.Fixture("inventory")
        fixtures.write_tree(fixture.path, files)
        fixtures.git_init(fixture.path)
        if commit:
            fixtures.git_commit(fixture.path, "add everything", day="2024-03-01")
        return fixture

    def test_gitignored_source_directory_is_excluded(self) -> None:
        fixtures.require_git()
        body = "package junk\n" + "var x = 1\n" * 300
        files = {
            "main.go": "package main\nfunc main() {}\n",
            ".gitignore": "junk/\n",
        }
        files.update({f"junk/big{n}.go": body for n in range(1, 6)})
        with self._repo(files) as fixture:
            palate = collect(fixture.path).palate
        self.assertEqual(palate.inventory, "git")
        self.assertEqual(palate.source_file_count, 1)
        self.assertEqual(palate.largest_file_path, "main.go")
        self.assertLess(palate.total_lines, 100)

    def test_untracked_but_unignored_file_is_included(self) -> None:
        """A repo mid-change still counts work that is not committed yet."""
        fixtures.require_git()
        with self._repo({"main.go": "package main\n"}) as fixture:
            fixtures.write_tree(fixture.path, {"brandnew.go": "package new\nvar z = 3\n"})
            palate = collect(fixture.path).palate
        self.assertEqual(palate.inventory, "git")
        self.assertEqual(palate.source_file_count, 2)

    def test_vendored_directory_is_excluded_without_a_gitignore(self) -> None:
        """--others would otherwise surface an unignored node_modules."""
        fixtures.require_git()
        files = {"main.js": "var a = 1;\n"}
        files.update({f"node_modules/m{n}.js": "var m = 1;\n" for n in range(1, 4)})
        with self._repo(files) as fixture:
            metrics = collect(fixture.path)
        self.assertEqual(metrics.palate.inventory, "git")
        self.assertEqual(metrics.palate.source_file_count, 1)
        self.assertGreater(metrics.sediment.vendored_file_count, 0)

    def test_editor_directory_is_not_counted_as_source(self) -> None:
        fixtures.require_git()
        files = {"main.js": "var a = 1;\n", "util.js": "var b = 2;\n"}
        files.update({f".vscode/s{n}.js": "var v = 1;\n" for n in range(1, 4)})
        with self._repo(files) as fixture:
            metrics = collect(fixture.path)
        self.assertEqual(metrics.palate.source_file_count, 2)
        editor = [item.path for item in metrics.sediment.items if item.kind == "editor"]
        self.assertIn(".vscode", editor)

    def test_directory_without_git_still_tastes(self) -> None:
        with fixtures.Fixture("nogit") as fixture:
            fixtures.write_tree(fixture.path, {"a.py": "def a():\n    return 1\n"})
            metrics = collect(fixture.path)
        assert_full_metrics(self, metrics)
        self.assertEqual(metrics.palate.inventory, "filesystem")
        self.assertEqual(metrics.palate.source_file_count, 1)

    def test_broken_git_falls_back_and_says_so(self) -> None:
        """A .git that git cannot read must degrade, not raise."""
        with fixtures.Fixture("brokengit") as fixture:
            (fixture.path / ".git").mkdir()
            fixtures.write_tree(fixture.path, {"a.py": "def a():\n    return 1\n"})
            metrics = collect(fixture.path)
        assert_full_metrics(self, metrics)
        self.assertEqual(metrics.palate.inventory, "filesystem")
        self.assertIn("inventory", [item.name for item in metrics.dropped])

    def test_sediment_still_reports_only_what_was_committed(self) -> None:
        """The inventory change must not leak into the sediment course."""
        fixtures.require_git()
        with self._repo({"a.py": "x = 1\n"}) as fixture:
            fixtures.write_tree(fixture.path, {".venv/lib.py": "y = 1\n"})
            metrics = collect(fixture.path)
        self.assertEqual(metrics.sediment.vendored_file_count, 0)
        self.assertEqual(metrics.palate.source_file_count, 1)


class SecretNameTest(unittest.TestCase):
    """What counts as a committed secret, and what deliberately does not."""

    def test_secret_names_are_recognised(self) -> None:
        for name in (".env", ".env.local", ".envrc", "prod.env", "secrets.env",
                     "id_rsa", "server.pem", "keystore.p12", "credentials"):
            with self.subTest(name=name):
                self.assertTrue(_is_secret_name(name))

    def test_sample_files_are_not_secrets(self) -> None:
        for name in (".env.example", ".env.sample", "prod.env.template",
                     "config.env.dist", "readme.md", "environment.py"):
            with self.subTest(name=name):
                self.assertFalse(_is_secret_name(name))


class DirectoryWithoutGitTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = fixtures.bare_directory()
        cls.metrics = collect(cls.fixture.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_git_absence_is_reported_as_data(self) -> None:
        git = self.metrics.git
        self.assertFalse(self.metrics.is_git_repo)
        self.assertFalse(git.is_repo)
        self.assertFalse(git.has_commits)
        self.assertFalse(git.shallow)
        self.assertEqual(git.commit_count, 0)
        self.assertEqual(git.fix_commit_count, 0)
        self.assertEqual(git.fix_ratio, 0.0)
        self.assertEqual(git.longest_gap_days, 0)
        self.assertIsNone(git.first_commit_date)
        self.assertIsNone(git.last_commit_date)
        self.assertIsNone(git.first_commit_year)
        self.assertIsNone(git.last_commit_year)
        self.assertIsNone(git.longest_gap_start)
        self.assertIsNone(git.longest_gap_end)
        self.assertIsNone(git.top_author_name)
        self.assertIsNone(git.last_commit_subject)
        self.assertEqual(git.author_count, 0)
        self.assertEqual(git.top_author_commits, 0)
        self.assertEqual(git.top_author_share, 0.0)

    def test_the_files_are_still_tasted(self) -> None:
        self.assertFalse(self.metrics.is_empty)
        self.assertGreaterEqual(self.metrics.palate.source_file_count, 2)
        self.assertGreater(self.metrics.palate.total_lines, 0)
        self.assertEqual(self.metrics.nose.readme_path, "README.md")
        self.assertEqual(self.metrics.terroir.primary_language, "Python")

    def test_no_manifest_is_reported_as_undeclared(self) -> None:
        self.assertEqual(self.metrics.structure.manifests, ())
        self.assertTrue(self.metrics.structure.undeclared)
        self.assertEqual(self.metrics.structure.total_declared, 0)
        self.assertEqual(self.metrics.structure.ecosystems, ())


class GitRepoWithoutCommitsTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        fixtures.require_git()
        cls.fixture = fixtures.git_repo_without_commits()
        cls.metrics = collect(cls.fixture.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_repository_without_history(self) -> None:
        git = self.metrics.git
        self.assertTrue(self.metrics.is_git_repo)
        self.assertTrue(git.is_repo)
        self.assertFalse(git.has_commits)
        self.assertEqual(git.commit_count, 0)
        self.assertEqual(git.fix_commit_count, 0)
        self.assertEqual(git.fix_ratio, 0.0)
        self.assertIsNone(git.first_commit_date)
        self.assertIsNone(git.last_commit_date)
        self.assertIsNone(git.last_commit_subject)
        self.assertEqual(git.author_count, 0)
        self.assertEqual(git.top_author_commits, 0)
        self.assertEqual(git.top_author_share, 0.0)
        self.assertEqual(git.longest_gap_days, 0)
        self.assertGreaterEqual(git.days_since_last_commit, 0)

    def test_files_are_present_so_the_repo_is_not_empty(self) -> None:
        self.assertFalse(self.metrics.is_empty)
        self.assertGreaterEqual(self.metrics.palate.source_file_count, 1)


class EmptyDirectoryTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = fixtures.empty_directory()
        cls.metrics = collect(cls.fixture.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_nothing_is_reported_as_nothing(self) -> None:
        self.assertTrue(self.metrics.is_empty)
        self.assertFalse(self.metrics.is_git_repo)
        palate = self.metrics.palate
        self.assertEqual(palate.source_file_count, 0)
        self.assertEqual(palate.total_file_count, 0)
        self.assertEqual(palate.total_lines, 0)
        self.assertEqual(palate.average_lines, 0.0)
        self.assertIsNone(palate.largest_file_path)
        self.assertEqual(palate.largest_file_lines, 0)
        self.assertEqual(palate.max_indent_depth, 0)
        self.assertEqual(palate.longest_function_lines, 0)
        self.assertFalse(palate.sampled)
        self.assertEqual(palate.scanned_file_count, 0)
        self.assertEqual(self.metrics.terroir.languages, ())
        self.assertIsNone(self.metrics.terroir.primary_language)
        self.assertEqual(self.metrics.abandonment.total, 0)
        self.assertEqual(self.metrics.abandonment.per_kloc, 0.0)
        self.assertEqual(self.metrics.sediment.items, ())
        self.assertTrue(self.metrics.structure.undeclared)
        self.assertEqual(self.metrics.dropped, ())

    def test_nose_finds_no_documents(self) -> None:
        nose = self.metrics.nose
        self.assertIsNone(nose.readme_path)
        self.assertIsNone(nose.license_path)
        self.assertIsNone(nose.license_name)
        self.assertIsNone(nose.gitignore_path)
        self.assertFalse(nose.has_contributing)
        self.assertFalse(nose.has_ci)
        self.assertFalse(nose.has_tests)


class UnknownLanguageRepoTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = fixtures.unknown_language_repo()
        cls.metrics = collect(cls.fixture.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_markers_are_found_in_every_comment_syntax(self) -> None:
        abandonment = self.metrics.abandonment
        self.assertEqual(abandonment.todo, fixtures.UNKNOWN_TODO_COUNT)
        self.assertEqual(abandonment.fixme, fixtures.UNKNOWN_FIXME_COUNT)
        self.assertEqual(abandonment.hack, fixtures.UNKNOWN_HACK_COUNT)
        self.assertEqual(abandonment.xxx, fixtures.UNKNOWN_XXX_COUNT)
        self.assertEqual(
            abandonment.total,
            fixtures.UNKNOWN_TODO_COUNT
            + fixtures.UNKNOWN_FIXME_COUNT
            + fixtures.UNKNOWN_HACK_COUNT
            + fixtures.UNKNOWN_XXX_COUNT,
        )

    def test_no_language_is_invented(self) -> None:
        names = {item.name for item in self.metrics.terroir.languages}
        self.assertNotIn("Python", names)
        self.assertNotIn("JavaScript", names)
        self.assertEqual(self.metrics.terroir.frameworks, ())


class DeepAndLongRepoTest(unittest.TestCase):
    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = fixtures.deep_and_long_repo()
        cls.metrics = collect(cls.fixture.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_indentation_depth(self) -> None:
        palate = self.metrics.palate
        self.assertEqual(palate.max_indent_depth, fixtures.DEEP_INDENT_DEPTH)
        self.assertEqual(palate.max_indent_path, fixtures.DEEP_PATH)

    def test_longest_function(self) -> None:
        palate = self.metrics.palate
        self.assertEqual(palate.longest_function_name, fixtures.LONG_FUNCTION_NAME)
        self.assertEqual(palate.longest_function_path, fixtures.LONG_PATH)
        self.assertGreaterEqual(
            palate.longest_function_lines,
            fixtures.LONG_FUNCTION_BODY_LINES,
        )
        self.assertLessEqual(
            palate.longest_function_lines,
            fixtures.LONG_FUNCTION_BODY_LINES + 2,
        )

    def test_largest_file_is_the_long_one(self) -> None:
        self.assertEqual(self.metrics.palate.largest_file_path, fixtures.LONG_PATH)


class WholeFileCountTest(unittest.TestCase):
    """Lines and markers are counted over the whole file, not its first 64 KiB.

    The tool used to read every file to a cap and then report the resulting
    count as the file's length. psf/requests tests/test_requests.py is 3,094
    lines and was reported as 1,850 under the metric the card calls the
    largest file. A number that is 40 percent short is worse than no number,
    because nothing marked it as short.
    """

    LINES: ClassVar[int] = 4000
    MARKER_LINE: ClassVar[int] = 3900

    def _long_file(self) -> str:
        lines = []
        for index in range(self.LINES):
            if index == self.MARKER_LINE:
                lines.append("# TODO: this marker sits far past the read cap")
            else:
                lines.append(f"value_{index} = {index}  # padding to make bytes")
        return "\n".join(lines) + "\n"

    def setUp(self) -> None:
        self.fixture = fixtures.Fixture("longfile")
        self.addCleanup(self.fixture.cleanup)
        body = self._long_file()
        # The point of the fixture is that it is comfortably over the cap.
        self.assertGreater(len(body.encode("utf-8")), 65536 * 2)
        fixtures.write_tree(self.fixture.path, {"big.py": body, "small.py": "x = 1\n"})
        self.metrics = collect(self.fixture.path, budget_seconds=60.0)

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_the_whole_file_is_counted(self) -> None:
        palate = self.metrics.palate
        self.assertEqual(palate.largest_file_path, "big.py")
        self.assertEqual(palate.largest_file_lines, self.LINES)
        self.assertEqual(palate.total_lines, self.LINES + 1)

    def test_a_marker_past_the_cap_is_found(self) -> None:
        self.assertEqual(self.metrics.abandonment.todo, 1)
        self.assertEqual(self.metrics.abandonment.worst_file_path, "big.py")

    def test_the_line_count_is_complete_and_says_so(self) -> None:
        coverage = self.metrics.coverage
        self.assertTrue(coverage.lines_complete)
        self.assertEqual(coverage.truncated_files, 0)

    def test_the_structural_cap_is_recorded_rather_than_hidden(self) -> None:
        """The expensive analysis still stops. Stopping quietly is the defect."""
        self.assertFalse(self.metrics.coverage.structural_scan_complete)


class NotMeasuredTest(unittest.TestCase):
    """Zero and "no detector for this language" must not be the same reading."""

    def test_a_language_without_a_detector_says_so(self) -> None:
        with fixtures.Fixture("nodetector") as fixture:
            fixtures.write_tree(
                fixture.path,
                {
                    "site.css": "body { color: red; }\n.wide { width: 100%; }\n",
                    "query.sql": "select 1;\nselect 2;\n",
                },
            )
            metrics = collect(fixture.path)
        assert_full_metrics(self, metrics)
        self.assertEqual(metrics.palate.longest_function_lines, 0)
        self.assertEqual(metrics.coverage.function_detector_files, 0)
        for language in metrics.palate.by_language:
            self.assertFalse(language.function_detector_ran, language.name)
            self.assertEqual(language.longest_function_lines, 0)

    def test_a_language_with_a_detector_is_distinguishable(self) -> None:
        with fixtures.Fixture("detector") as fixture:
            fixtures.write_tree(
                fixture.path,
                {"a.py": "def one() -> int:\n    return 1\n", "b.css": "a { b: c; }\n"},
            )
            metrics = collect(fixture.path)
        assert_full_metrics(self, metrics)
        by_name = {item.name: item for item in metrics.palate.by_language}
        self.assertTrue(by_name["Python"].function_detector_ran)
        self.assertFalse(by_name["CSS"].function_detector_ran)
        self.assertEqual(metrics.coverage.function_detector_files, 1)


class LanguageCoverageTest(unittest.TestCase):
    """A score computed over files nobody recognised should say how many.

    github/gitignore reports 309 source files with none of them attributed to
    any language, and rbenv/rbenv took the corpus top score on a repository
    where 6 files of 30 were recognised.
    """

    def test_unattributed_files_are_counted_and_bucketed(self) -> None:
        files = {f"templates/t{index}.zzz": "value\nvalue\n" for index in range(5)}
        with fixtures.Fixture("unattributed") as fixture:
            fixtures.write_tree(fixture.path, files)
            metrics = collect(fixture.path)
        assert_full_metrics(self, metrics)
        coverage = metrics.coverage
        self.assertEqual(coverage.source_files, 5)
        self.assertEqual(coverage.attributed_files, 0)
        self.assertEqual(metrics.terroir.languages, ())
        self.assertEqual(len(metrics.palate.by_language), 1)
        bucket = metrics.palate.by_language[0]
        self.assertEqual(bucket.name, "")
        self.assertEqual(bucket.file_count, 5)

    def test_a_partly_recognised_tree_reports_both_halves(self) -> None:
        files = {"main.py": "x = 1\n", "run.zzz": "value\n", "other.zzz": "value\n"}
        with fixtures.Fixture("partly") as fixture:
            fixtures.write_tree(fixture.path, files)
            metrics = collect(fixture.path)
        coverage = metrics.coverage
        self.assertEqual(coverage.source_files, 3)
        self.assertEqual(coverage.attributed_files, 1)
        names = {item.name for item in metrics.palate.by_language}
        self.assertEqual(names, {"", "Python"})


class ReadSeamTest(unittest.TestCase):
    """A file arrives in chunks, and a line can sit across the join.

    The reader hands the analysis lines rather than bytes, so every join is
    somewhere one line can become two, or a word can be cut in half and stop
    matching. A TODO with its letters in two different reads is the case no
    fixture small enough to fit in a single read can ever reach.
    """

    FILLER: ClassVar[str] = "value = 1\n"
    MARKER: ClassVar[str] = "# TODO: a marker written across the join\n"

    def payload_with_a_split_marker(self, letters_before: int) -> bytes:
        """One file whose TODO has `letters_before` letters in the first read."""
        start = BINARY_SNIFF_BYTES - letters_before - self.MARKER.index("TODO")
        lead = self.FILLER * (start // len(self.FILLER))
        pad = start - len(lead)
        if pad:
            lead += "#" * (pad - 1) + "\n"
        payload = (lead + self.MARKER + self.FILLER * 200).encode("utf-8")
        # Without this the test could pass on a file that never straddles.
        self.assertEqual(
            payload[BINARY_SNIFF_BYTES - letters_before :][:4],
            b"TODO",
            "the fixture does not split the marker where the test claims",
        )
        return payload

    def test_a_marker_split_across_the_join_is_counted_once(self) -> None:
        for letters_before in (1, 2, 3):
            with self.subTest(letters_before=letters_before):
                payload = self.payload_with_a_split_marker(letters_before)
                with fixtures.Fixture("seam") as fixture:
                    (fixture.path / "body.py").write_bytes(payload)
                    metrics = collect(fixture.path, budget_seconds=60.0)
                self.assertEqual(metrics.abandonment.todo, 1)
                self.assertEqual(metrics.abandonment.worst_file_path, "body.py")
                self.assertEqual(
                    metrics.palate.largest_file_lines,
                    len(payload.decode("utf-8").splitlines()),
                )


class LongSingleLineTest(unittest.TestCase):
    """A minified bundle is one line of several megabytes, and still one line.

    The reader stops accumulating an unbroken line past a cap, which is what
    keeps the whole bundle out of memory. Two things have to survive that:
    the line counts once, and the lines after it are read as normal rather
    than swallowed along with the tail that was dropped.
    """

    def test_an_overlong_line_counts_once_and_does_not_eat_the_next(self) -> None:
        minified = "var a=1;" * (MAX_LINE_CHARS // 4)
        self.assertGreater(len(minified), MAX_LINE_CHARS)
        with fixtures.Fixture("minified") as fixture:
            fixtures.write_tree(
                fixture.path,
                {"bundle.js": minified + "\nvar b = 2; // TODO: after the long line\n"},
            )
            metrics = collect(fixture.path, budget_seconds=60.0)
        assert_full_metrics(self, metrics)
        self.assertEqual(metrics.palate.largest_file_lines, 2)
        self.assertEqual(metrics.abandonment.todo, 1)
        self.assertEqual(metrics.abandonment.worst_file_path, "bundle.js")
        coverage = metrics.coverage
        self.assertTrue(coverage.lines_complete)
        self.assertEqual(coverage.truncated_files, 0)
        # Part of that line was never handed to the analysis, and the record
        # says as much rather than reporting the head as the whole.
        self.assertFalse(coverage.structural_scan_complete)


class FunctionDetectorCoverageTest(unittest.TestCase):
    """Zero and "nobody looked" are two readings of the same number.

    52 of the 78 known languages have no function detector, so
    longest_function_lines of zero means either that the longest function in
    this repository is short or that nothing ever measured one. A score
    computed over the second reading is not a score, and until the detector
    could say which one it was holding, judge had no way to ask.
    """

    def measure(self, files: dict[str, str]) -> RepoMetrics:
        with fixtures.Fixture("detector") as fixture:
            fixtures.write_tree(fixture.path, files)
            return collect(fixture.path, budget_seconds=60.0)

    def test_a_language_without_a_detector_reports_not_measured(self) -> None:
        metrics = self.measure(
            {
                "site.css": "body { color: red; }\n.wide { width: 100%; }\n",
                "report.sql": "select name\nfrom bottles\nwhere year > 2010;\n",
            }
        )
        assert_full_metrics(self, metrics)
        self.assertEqual(metrics.palate.longest_function_lines, 0)
        self.assertIsNone(metrics.palate.longest_function_name)
        self.assertIsNone(metrics.palate.longest_function_path)
        self.assertEqual(metrics.coverage.function_detector_files, 0)
        self.assertEqual(
            {
                item.name: item.function_detector_ran
                for item in metrics.palate.by_language
            },
            {"CSS": False, "SQL": False},
        )

    def test_short_functions_report_a_detector_that_ran(self) -> None:
        metrics = self.measure(
            {
                "cellar.py": "def pour(bottle):\n    return bottle\n",
                "cellar.rb": "def pour(bottle)\n  bottle\nend\n",
            }
        )
        assert_full_metrics(self, metrics)
        self.assertEqual(metrics.coverage.function_detector_files, 2)
        self.assertEqual(
            {
                item.name: item.function_detector_ran
                for item in metrics.palate.by_language
            },
            {"Python": True, "Ruby": True},
        )
        self.assertGreater(metrics.palate.longest_function_lines, 0)
        self.assertLess(metrics.palate.longest_function_lines, 5)

    def test_a_measured_zero_is_distinguishable_from_an_unmeasured_one(self) -> None:
        """Same scalar, two different facts. This is the whole defect."""
        measured = self.measure({"constants.py": "ALPHA = 1\nBETA = 2\n"})
        unmeasured = self.measure({"theme.css": "body { color: red; }\n"})
        self.assertEqual(measured.palate.longest_function_lines, 0)
        self.assertEqual(unmeasured.palate.longest_function_lines, 0)
        self.assertEqual(measured.coverage.function_detector_files, 1)
        self.assertEqual(unmeasured.coverage.function_detector_files, 0)
        self.assertTrue(measured.palate.by_language[0].function_detector_ran)
        self.assertFalse(unmeasured.palate.by_language[0].function_detector_ran)


class LanguageAttributionTest(unittest.TestCase):
    """How much of the tree anyone recognised, stated as a fraction.

    github/gitignore reports 309 source files with none of them attributed
    to a language, and rbenv/rbenv took the corpus top score of 94 on a
    repository where 6 files of 30 were recognised. Both numbers were
    computed over files that no detector could read, and neither said so.
    """

    def test_an_unrecognised_tree_reports_none_attributed(self) -> None:
        with fixtures.unknown_language_repo() as fixture:
            metrics = collect(fixture.path, budget_seconds=60.0)
        assert_full_metrics(self, metrics)
        coverage = metrics.coverage
        self.assertEqual(coverage.source_files, fixtures.UNKNOWN_FILE_COUNT)
        self.assertEqual(coverage.attributed_files, 0)
        self.assertGreater(
            coverage.source_files,
            0,
            "no language recognised is not the same as no files found",
        )
        self.assertEqual(metrics.terroir.languages, ())
        self.assertIsNone(metrics.terroir.primary_language)

    def test_unattributed_files_still_get_a_bucket(self) -> None:
        """A repository can be nothing but unattributed files, and that is data."""
        with fixtures.unknown_language_repo() as fixture:
            metrics = collect(fixture.path, budget_seconds=60.0)
        self.assertEqual(len(metrics.palate.by_language), 1)
        bucket = metrics.palate.by_language[0]
        self.assertEqual(bucket.name, "")
        self.assertEqual(bucket.file_count, fixtures.UNKNOWN_FILE_COUNT)
        self.assertEqual(bucket.line_count, metrics.palate.total_lines)
        self.assertEqual(bucket.largest_file_lines, metrics.palate.largest_file_lines)
        self.assertFalse(bucket.function_detector_ran)

    def test_a_partly_recognised_tree_reports_both_halves(self) -> None:
        files = {"tool.py": "def run():\n    return 1\n"}
        files.update({f"templates/t{index}.zzz": "value\n" for index in range(4)})
        with fixtures.Fixture("partly-known") as fixture:
            fixtures.write_tree(fixture.path, files)
            metrics = collect(fixture.path, budget_seconds=60.0)
        assert_full_metrics(self, metrics)
        coverage = metrics.coverage
        self.assertEqual(coverage.source_files, 5)
        self.assertEqual(coverage.attributed_files, 1)
        buckets = {item.name: item.file_count for item in metrics.palate.by_language}
        self.assertEqual(buckets, {"": 4, "Python": 1})
        # The unattributed bucket is the whole difference, not a remainder
        # that some other bucket quietly absorbed.
        self.assertEqual(
            coverage.source_files - coverage.attributed_files, buckets[""]
        )


def _nested_python(depth: int) -> str:
    """A short Python file whose only notable property is how deep it nests."""
    lines = ["def nested(flag: bool) -> int:", "    total = 0"]
    for level in range(1, depth):
        lines.append("    " * level + "if flag:")
    lines.append("    " * depth + "total += 1")
    lines.append("    return total")
    return "\n".join(lines) + "\n"


def _long_go(body_lines: int, name: str) -> str:
    """A flat Go file whose only notable property is one very long function."""
    lines = ["package main", "", f"func {name}() int {{", "\ttotal := 0"]
    lines.extend(f"\ttotal += {index}" for index in range(body_lines))
    lines.extend(["\treturn total", "}"])
    return "\n".join(lines) + "\n"


class LanguageSplitTest(unittest.TestCase):
    """Two languages, two sets of numbers, and one repository wide view.

    Nesting depth means one thing in Python and less in Go, which is why the
    split exists. It is only worth having while it agrees with the scalars
    beside it, so this fixture puts the deepest nesting in one language and
    the longest function in the other. If the two views ever drift, the
    repository wide maximum stops naming a file that holds it.
    """

    PYTHON_PATH: ClassVar[str] = "src/nested.py"
    GO_PATH: ClassVar[str] = "src/accumulate.go"
    PYTHON_DEPTH: ClassVar[int] = 8
    GO_BODY_LINES: ClassVar[int] = 120
    GO_FUNCTION_NAME: ClassVar[str] = "accumulate"

    fixture: ClassVar[fixtures.Fixture]
    metrics: ClassVar[RepoMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = fixtures.Fixture("two-languages")
        fixtures.write_tree(
            cls.fixture.path,
            {
                cls.PYTHON_PATH: _nested_python(cls.PYTHON_DEPTH),
                cls.GO_PATH: _long_go(cls.GO_BODY_LINES, cls.GO_FUNCTION_NAME),
            },
        )
        cls.metrics = collect(cls.fixture.path, budget_seconds=60.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def bucket(self, name: str) -> LanguagePalate:
        found = [item for item in self.metrics.palate.by_language if item.name == name]
        self.assertEqual(len(found), 1, f"expected exactly one {name} bucket")
        return found[0]

    def test_returns_a_full_repo_metrics(self) -> None:
        assert_full_metrics(self, self.metrics)

    def test_each_language_gets_its_own_entry(self) -> None:
        palate = self.metrics.palate
        self.assertEqual(
            {item.name: item.file_count for item in palate.by_language},
            {"Go": 1, "Python": 1},
        )
        self.assertEqual(
            sum(item.line_count for item in palate.by_language), palate.total_lines
        )
        for item in palate.by_language:
            self.assertTrue(item.function_detector_ran, item.name)

    def test_the_two_languages_disagree_about_depth_and_length(self) -> None:
        """Without this the maxima could come from one bucket and prove nothing."""
        python = self.bucket("Python")
        go = self.bucket("Go")
        self.assertEqual(python.max_indent_depth, self.PYTHON_DEPTH)
        self.assertLess(go.max_indent_depth, python.max_indent_depth)
        self.assertGreaterEqual(go.longest_function_lines, self.GO_BODY_LINES)
        self.assertLess(python.longest_function_lines, go.longest_function_lines)
        self.assertGreater(go.largest_file_lines, python.largest_file_lines)

    def test_the_repository_wide_scalars_are_the_maximum_across_buckets(self) -> None:
        palate = self.metrics.palate
        python = self.bucket("Python")
        go = self.bucket("Go")

        self.assertEqual(palate.max_indent_depth, python.max_indent_depth)
        self.assertEqual(palate.max_indent_path, python.max_indent_path)
        self.assertEqual(palate.max_indent_path, self.PYTHON_PATH)

        self.assertEqual(palate.longest_function_lines, go.longest_function_lines)
        self.assertEqual(palate.longest_function_name, go.longest_function_name)
        self.assertEqual(palate.longest_function_path, go.longest_function_path)
        self.assertEqual(palate.longest_function_name, self.GO_FUNCTION_NAME)

        self.assertEqual(palate.largest_file_lines, go.largest_file_lines)
        self.assertEqual(palate.largest_file_path, go.largest_file_path)
        self.assertEqual(palate.largest_file_path, self.GO_PATH)


class ShallowCloneTest(unittest.TestCase):
    """A clone told to fetch one commit knows one commit, and must say so.

    Measured on pallets/itsdangerous, a full clone scored 92 and
    `git clone --depth 1` scored 93. Nothing was dropped and nothing was
    flagged, so withholding the history paid a point. Coverage is where the
    withholding becomes visible.
    """

    def test_a_shallow_clone_reports_an_incomplete_history(self) -> None:
        fixtures.require_git()
        with fixtures.healthy_python_repo() as source:
            with fixtures.Fixture("shallow") as destination:
                target = destination.path / "clone"
                try:
                    fixtures.run_git(
                        [
                            "clone",
                            "--quiet",
                            "--depth",
                            "1",
                            # A local path is copied whole and --depth is
                            # ignored. Only file:// produces a real shallow
                            # clone, so a plain path would test nothing.
                            source.path.as_uri(),
                            str(target),
                        ],
                        destination.path,
                    )
                except subprocess.CalledProcessError as error:
                    self.fail(f"git clone --depth 1 failed: {error.stderr}")
                full = collect(source.path)
                shallow = collect(target)

        assert_full_metrics(self, shallow)
        self.assertTrue(shallow.git.shallow)
        self.assertFalse(shallow.coverage.history_complete)
        self.assertTrue(full.coverage.history_complete)

        # Not merely a smaller history: a wrong one. The shallow clone dates
        # the first commit to the day of the last, which is the falsehood the
        # flag exists to mark.
        self.assertEqual(shallow.git.commit_count, 1)
        self.assertEqual(full.git.commit_count, fixtures.HEALTHY_COMMIT_COUNT)
        self.assertEqual(full.git.first_commit_date, fixtures.HEALTHY_FIRST_DAY)
        self.assertEqual(shallow.git.first_commit_date, fixtures.HEALTHY_LAST_DAY)

        # Every file is present in both, so this is a gap in the history and
        # nowhere else.
        self.assertEqual(
            shallow.palate.source_file_count, full.palate.source_file_count
        )
        self.assertEqual(shallow.palate.total_lines, full.palate.total_lines)
        self.assertTrue(shallow.coverage.lines_complete)


class CoverageAbsenceTest(unittest.TestCase):
    """Each Coverage flag answers one question about the run that set it."""

    def test_a_directory_without_git_measured_no_history(self) -> None:
        with fixtures.bare_directory() as fixture:
            metrics = collect(fixture.path)
        self.assertFalse(metrics.coverage.history_complete)
        self.assertFalse(metrics.coverage.authorship_measured)

    def test_a_repository_without_commits_measured_no_history(self) -> None:
        fixtures.require_git()
        with fixtures.git_repo_without_commits() as fixture:
            metrics = collect(fixture.path)
        self.assertTrue(metrics.git.is_repo)
        self.assertFalse(metrics.coverage.history_complete)
        self.assertFalse(metrics.coverage.authorship_measured)

    def test_dependencies_measured_follows_the_manifest(self) -> None:
        """Zero declared dependencies is austere. No manifest is unmeasured."""
        fixtures.require_git()
        with fixtures.healthy_python_repo() as fixture:
            declared = collect(fixture.path)
        with fixtures.bare_directory() as fixture:
            undeclared = collect(fixture.path)
        self.assertTrue(declared.coverage.dependencies_measured)
        self.assertTrue(declared.coverage.history_complete)
        self.assertTrue(declared.coverage.authorship_measured)
        self.assertFalse(undeclared.coverage.dependencies_measured)
        self.assertEqual(undeclared.structure.manifests, ())


class UnpourableTest(unittest.TestCase):
    def test_missing_path_raises_tasting_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "no-such-cellar"
            with self.assertRaises(TastingError) as caught:
                collect(missing)
            self.assertIsInstance(caught.exception.message, str)
            self.assertNotEqual(caught.exception.message, "")

    def test_tasting_error_is_an_exception(self) -> None:
        self.assertTrue(issubclass(TastingError, Exception))


class FixtureIsolationTest(unittest.TestCase):
    """The builders must never reach the repository the suite was started from."""

    def test_inherited_git_location_variables_are_dropped(self) -> None:
        polluted = {
            "GIT_DIR": "/elsewhere/.git",
            "GIT_WORK_TREE": "/elsewhere",
            "GIT_INDEX_FILE": "/elsewhere/.git/index",
            "GIT_OBJECT_DIRECTORY": "/elsewhere/.git/objects",
            "GIT_CONFIG_PARAMETERS": "'core.autocrlf=true'",
        }
        with mock.patch.dict(os.environ, polluted, clear=False):
            env = fixtures.isolated_env()
        for name in polluted:
            self.assertNotIn(name, env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_CONFIG_SYSTEM"], os.devnull)


if __name__ == "__main__":
    unittest.main()
