"""The style gate.

These tests fail the build. They enforce the house rules that no reviewer
should have to enforce by hand: no long dashes, no emoji, no exclamation
marks in the voice, no third party imports, and a cellar that can only cite
numbers the judge actually provides.
"""

from __future__ import annotations

import ast
import importlib
import shutil
import subprocess
import sys
import unittest
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from string import Formatter
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "sommelier"
TESTS_DIR = REPO_ROOT / "tests"

# Built from codepoints so that this file does not trip its own scan.
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
BANNED_DASHES = (EM_DASH, EN_DASH)

# Explicit codepoint ranges rather than a library, since the package has no
# dependencies and neither may its tests.
EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0xFE00, 0xFE0F),
    (0x1F000, 0x1FAFF),
)

ALLOWED_IMPORT_ROOTS = frozenset(sys.stdlib_module_names) | {"sommelier"}


# Cloned third party repositories used by the corpus tests. They live under
# tests/ so they are easy to find, which puts them in the way of every gate
# that walks the tree. The house rules are ours and do not apply to them.
VENDORED_TEST_DATA = (TESTS_DIR / "corpus_cache",)


def _is_vendored(path: Path) -> bool:
    return any(path.is_relative_to(directory) for directory in VENDORED_TEST_DATA)


def python_sources() -> list[Path]:
    found: list[Path] = []
    for directory in (PACKAGE_DIR, TESTS_DIR):
        if directory.is_dir():
            found.extend(
                sorted(p for p in directory.rglob("*.py") if not _is_vendored(p))
            )
    return found


def scanned_files() -> list[Path]:
    found = python_sources()
    found.extend(sorted(REPO_ROOT.glob("*.md")))
    pyproject = REPO_ROOT / "pyproject.toml"
    if pyproject.is_file():
        found.append(pyproject)
    return found


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def numbered_lines(path: Path) -> Iterable[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    return enumerate(text.splitlines(), start=1)


def is_emoji(character: str) -> bool:
    point = ord(character)
    return any(low <= point <= high for low, high in EMOJI_RANGES)


def load_module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except Exception as error:  # any import failure is a style gate failure
        raise AssertionError(f"{name} must be importable: {error}") from error


def cellar() -> Mapping[str, Sequence[str]]:
    templates: Mapping[str, Sequence[str]] = load_module("sommelier.lines").CELLAR
    return templates


def all_keys() -> tuple[str, ...]:
    keys: Sequence[str] = load_module("sommelier.judge").ALL_KEYS
    return tuple(keys)


def key_facts() -> Mapping[str, Sequence[str]]:
    facts: Mapping[str, Sequence[str]] = load_module("sommelier.judge").KEY_FACTS
    return facts


def placeholders(template: str) -> set[str]:
    names: set[str] = set()
    for _text, field, _spec, _conversion in Formatter().parse(template):
        if field is None:
            continue
        root = field.split(".")[0].split("[")[0].strip()
        names.add(root)
    return names


def string_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    literals: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append((node.lineno, node.value))
    return literals


class DashTests(unittest.TestCase):
    def test_no_long_dashes_anywhere(self) -> None:
        paths = scanned_files()
        self.assertTrue(paths, "the dash scan found nothing to read")
        offences: list[str] = []
        for path in paths:
            for number, line in numbered_lines(path):
                for column, character in enumerate(line, start=1):
                    if character in BANNED_DASHES:
                        name = "em dash" if character == EM_DASH else "en dash"
                        offences.append(
                            f"{relative(path)}:{number}:{column} contains an {name}"
                        )
        self.assertEqual(
            [],
            offences,
            "long dashes are banned, use a comma or a full stop:\n"
            + "\n".join(offences),
        )


class EmojiTests(unittest.TestCase):
    def test_no_emoji_anywhere(self) -> None:
        paths = scanned_files()
        self.assertTrue(paths, "the emoji scan found nothing to read")
        offences: list[str] = []
        for path in paths:
            for number, line in numbered_lines(path):
                for column, character in enumerate(line, start=1):
                    if is_emoji(character):
                        point = ord(character)
                        offences.append(
                            f"{relative(path)}:{number}:{column} "
                            f"contains U+{point:04X}"
                        )
        self.assertEqual(
            [], offences, "emoji are banned:\n" + "\n".join(offences)
        )


class ExclamationTests(unittest.TestCase):
    def test_no_exclamation_marks_in_the_cellar(self) -> None:
        path = PACKAGE_DIR / "lines.py"
        self.assertTrue(path.is_file(), f"{relative(path)} is missing")
        offences = [
            f"{relative(path)}:{number}"
            for number, value in string_literals(path)
            if "!" in value
        ]
        self.assertEqual(
            [],
            offences,
            "the sommelier never raises its voice:\n" + "\n".join(offences),
        )

    def test_no_exclamation_marks_in_the_readme(self) -> None:
        path = REPO_ROOT / "README.md"
        self.assertTrue(path.is_file(), "README.md is missing")
        offences = [
            f"{relative(path)}:{number}"
            for number, line in numbered_lines(path)
            if "!" in line
        ]
        self.assertEqual(
            [],
            offences,
            "the readme never raises its voice:\n" + "\n".join(offences),
        )


class CellarTests(unittest.TestCase):
    def test_every_key_has_at_least_three_templates(self) -> None:
        templates = cellar()
        thin = sorted(
            f"{key} has {len(templates[key])}"
            for key in templates
            if len(templates[key]) < 3
        )
        self.assertEqual(
            [],
            thin,
            "every key needs at least three templates:\n" + "\n".join(thin),
        )

    def test_every_judge_key_is_stocked(self) -> None:
        templates = cellar()
        missing = sorted(key for key in all_keys() if key not in templates)
        self.assertEqual(
            [],
            missing,
            "judge can emit keys the cellar cannot pour:\n" + "\n".join(missing),
        )

    def test_the_cellar_holds_no_unreachable_keys(self) -> None:
        emittable = set(all_keys())
        stranded = sorted(key for key in cellar() if key not in emittable)
        self.assertEqual(
            [],
            stranded,
            "the cellar holds keys judge can never emit:\n" + "\n".join(stranded),
        )

    def test_templates_only_cite_facts_that_exist(self) -> None:
        facts = key_facts()
        offences: list[str] = []
        for key, templates in sorted(cellar().items()):
            available = set(facts.get(key, ()))
            for index, template in enumerate(templates):
                try:
                    used = placeholders(template)
                except ValueError as error:
                    offences.append(f"{key}[{index}] is not a format string: {error}")
                    continue
                for name in sorted(used):
                    if not name:
                        offences.append(
                            f"{key}[{index}] uses a positional placeholder"
                        )
                    elif name.isdigit():
                        offences.append(
                            f"{key}[{index}] uses the positional placeholder {name}"
                        )
                    elif name not in available:
                        offences.append(f"{key}[{index}] cites unknown fact {name}")
        self.assertEqual(
            [],
            offences,
            "templates may only cite facts their key provides:\n"
            + "\n".join(offences),
        )


class DependencyTests(unittest.TestCase):
    def test_package_imports_only_the_standard_library(self) -> None:
        modules = sorted(PACKAGE_DIR.rglob("*.py")) if PACKAGE_DIR.is_dir() else []
        self.assertTrue(modules, "the sommelier package has no modules")
        offences: list[str] = []
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                roots: list[str] = []
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        continue
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    if root and root not in ALLOWED_IMPORT_ROOTS:
                        offences.append(
                            f"{relative(path)}:{node.lineno} imports {root}"
                        )
        self.assertEqual(
            [],
            sorted(offences),
            "the package is standard library only:\n" + "\n".join(sorted(offences)),
        )


# Every commit after the root is checked. The root itself is GitHub's own
# "Initial commit" and is left alone. Pinning the root rather than a moving
# point means this constant never needs touching again.
COMMIT_BASELINE = "01550740dbceb37dd9024e3ed482be8ca1234173"

ALLOWED_PREFIXES = ("add", "fix", "rm", "docs", "test", "perf")
SUBJECT_LIMIT = 50


def git_available() -> bool:
    return shutil.which("git") is not None and (REPO_ROOT / ".git").exists()


def commits_since_baseline() -> list[tuple[str, str]]:
    """(sha, full message) for every commit after the baseline."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", COMMIT_BASELINE],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if probe.returncode != 0:
        raise unittest.SkipTest("baseline commit is not present in this clone")
    result = subprocess.run(
        ["git", "log", f"{COMMIT_BASELINE}..HEAD", "--format=%H%x1f%B%x1e"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise unittest.SkipTest("git log failed")
    commits: list[tuple[str, str]] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, message = record.partition("\x1f")
        commits.append((sha, message))
    return commits


class CommitMessageTests(unittest.TestCase):
    """Subject line only. No bodies, no footers, no trailers, no essays."""

    def setUp(self) -> None:
        if not git_available():
            self.skipTest("git is unavailable")

    def test_commits_carry_a_subject_and_nothing_else(self) -> None:
        offences: list[str] = []
        for sha, message in commits_since_baseline():
            lines = [line for line in message.splitlines() if line.strip()]
            if len(lines) > 1:
                offences.append(
                    f"{sha[:9]} has {len(lines)} non-blank lines, expected 1: "
                    f"{lines[0][:48]}"
                )
        self.assertEqual(
            [], offences, "commit messages are one line:\n" + "\n".join(offences)
        )

    def test_subjects_obey_the_house_rules(self) -> None:
        offences: list[str] = []
        for sha, message in commits_since_baseline():
            subject = message.splitlines()[0] if message.splitlines() else ""
            label = f"{sha[:9]} {subject!r}"
            if len(subject) > SUBJECT_LIMIT:
                offences.append(f"{label} is {len(subject)} chars, limit {SUBJECT_LIMIT}")
            if subject != subject.lower():
                offences.append(f"{label} is not lower case")
            if subject.endswith("."):
                offences.append(f"{label} ends with a full stop")
            if not subject.split(" ")[0] in ALLOWED_PREFIXES:
                offences.append(
                    f"{label} prefix is not one of {', '.join(ALLOWED_PREFIXES)}"
                )
        self.assertEqual(
            [], offences, "commit subjects:\n" + "\n".join(offences)
        )


if __name__ == "__main__":
    unittest.main()
