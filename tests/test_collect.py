"""Tests for sommelier.collect against synthetic repositories."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import ClassVar
from unittest import mock

from sommelier.collect import (
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
