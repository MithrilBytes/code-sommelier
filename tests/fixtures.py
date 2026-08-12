"""Synthetic repositories for the code-sommelier test suite.

Every builder returns a :class:`Fixture` that owns a temporary directory. The
caller is responsible for calling :meth:`Fixture.cleanup`, either directly or by
using the fixture as a context manager. All git history is written with explicit
author and committer dates and explicit author identities, so the numbers the
collector reports are reproducible on any machine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Final

from sommelier.collect import (
    AbandonmentMetrics,
    DependencyManifest,
    DroppedAnalyzer,
    GitMetrics,
    LanguageShare,
    NoseMetrics,
    PalateMetrics,
    RepoMetrics,
    SedimentMetrics,
    StructureMetrics,
    TerroirMetrics,
)

GIT_TIMEOUT_SECONDS: Final[float] = 60.0

ADA_NAME: Final[str] = "Ada Lovelace"
ADA_EMAIL: Final[str] = "ada@example.invalid"
GRACE_NAME: Final[str] = "Grace Hopper"
GRACE_EMAIL: Final[str] = "grace@example.invalid"
DANA_NAME: Final[str] = "Dana Scully"
DANA_EMAIL: Final[str] = "dana@example.invalid"

HEALTHY_NAME: Final[str] = "cellar-book"
HEALTHY_FIRST_DAY: Final[str] = "2021-03-01"
HEALTHY_SECOND_DAY: Final[str] = "2021-03-05"
HEALTHY_THIRD_DAY: Final[str] = "2022-01-10"
HEALTHY_LAST_DAY: Final[str] = "2022-01-20"
HEALTHY_COMMIT_COUNT: Final[int] = 4
HEALTHY_FIX_COMMIT_COUNT: Final[int] = 1
HEALTHY_LAST_SUBJECT: Final[str] = "Add a test for the pour helper"
HEALTHY_LONGEST_GAP_DAYS: Final[int] = 311
HEALTHY_README_LINES: Final[int] = 13
HEALTHY_GITIGNORE_RULES: Final[int] = 5
HEALTHY_REQUIREMENT_COUNT: Final[int] = 6
HEALTHY_LARGEST_FILE: Final[str] = "src/cellar/core.py"

NEGLECTED_NAME: Final[str] = "todo-app"
NEGLECTED_FIRST_DAY: Final[str] = "2019-01-15"
NEGLECTED_SECOND_DAY: Final[str] = "2019-02-02"
NEGLECTED_LAST_DAY: Final[str] = "2019-11-03"
NEGLECTED_COMMIT_COUNT: Final[int] = 3
NEGLECTED_LAST_SUBJECT: Final[str] = "fix login again"
NEGLECTED_LONGEST_GAP_DAYS: Final[int] = 274
NEGLECTED_LEGACY_PATH: Final[str] = "src/legacy.js"
NEGLECTED_LEGACY_LINES: Final[int] = 900
NEGLECTED_LEGACY_TODOS: Final[int] = 20
NEGLECTED_APP_TODOS: Final[int] = 6
NEGLECTED_UTIL_TODOS: Final[int] = 4
NEGLECTED_TODO_COUNT: Final[int] = 30
NEGLECTED_FIXME_COUNT: Final[int] = 3
NEGLECTED_HACK_COUNT: Final[int] = 2
NEGLECTED_XXX_COUNT: Final[int] = 1
NEGLECTED_MARKER_TOTAL: Final[int] = 36
NEGLECTED_DEBUG_PRINTS: Final[int] = 4
NEGLECTED_VENDORED_FILES: Final[int] = 12
NEGLECTED_DEPENDENCIES: Final[int] = 5
NEGLECTED_DEV_DEPENDENCIES: Final[int] = 3
NEGLECTED_OS_CRUFT: Final[int] = 2
NEGLECTED_BINARY_PATH: Final[str] = "assets/hero.bin"
NEGLECTED_BINARY_BYTES: Final[int] = 6 * 1024 * 1024

UNKNOWN_TODO_COUNT: Final[int] = 7
UNKNOWN_FIXME_COUNT: Final[int] = 1
UNKNOWN_HACK_COUNT: Final[int] = 1
UNKNOWN_XXX_COUNT: Final[int] = 1

DEEP_PATH: Final[str] = "src/deep.py"
DEEP_INDENT_DEPTH: Final[int] = 10
LONG_PATH: Final[str] = "src/long.py"
LONG_FUNCTION_NAME: Final[str] = "long_function"
LONG_FUNCTION_BODY_LINES: Final[int] = 200


def _default_git() -> GitMetrics:
    return GitMetrics(
        is_repo=True,
        has_commits=True,
        shallow=False,
        first_commit_date="2021-03-01",
        last_commit_date="2022-01-20",
        first_commit_year=2021,
        last_commit_year=2022,
        commit_count=40,
        fix_commit_count=8,
        fix_ratio=0.2,
        longest_gap_days=31,
        longest_gap_start="2021-05-01",
        longest_gap_end="2021-06-01",
        days_since_last_commit=120,
        author_count=3,
        top_author_name=ADA_NAME,
        top_author_commits=20,
        top_author_share=0.5,
        last_commit_subject="Add the pour helper",
    )


def _default_nose() -> NoseMetrics:
    return NoseMetrics(
        readme_path="README.md",
        readme_lines=40,
        readme_bytes=1200,
        license_path="LICENSE",
        license_name="MIT",
        gitignore_path=".gitignore",
        gitignore_rules=12,
        has_contributing=True,
        has_ci=True,
        has_tests=True,
    )


def _default_structure() -> StructureMetrics:
    manifest = DependencyManifest(
        ecosystem="python",
        manifest_path="requirements.txt",
        declared_count=6,
        dev_count=0,
        lockfile_path=None,
        locked_count=0,
        drift=True,
        drift_reason="no lockfile",
    )
    return StructureMetrics(
        manifests=(manifest,),
        total_declared=6,
        undeclared=False,
        ecosystems=("python",),
    )


def _default_abandonment() -> AbandonmentMetrics:
    return AbandonmentMetrics(
        todo=9,
        fixme=2,
        hack=1,
        xxx=0,
        total=12,
        per_kloc=9.2,
        worst_file_path="src/core.py",
        worst_file_count=5,
        debug_print_count=1,
        commented_out_code_lines=4,
    )


def _default_sediment() -> SedimentMetrics:
    return SedimentMetrics(
        items=(),
        vendored_file_count=0,
        vendored_dir_count=0,
        secret_file_count=0,
        os_cruft_count=0,
        large_binary_count=0,
        largest_binary_path=None,
        largest_binary_bytes=0,
    )


def synthetic_metrics(
    *,
    name: str = "cellar-book",
    path: str | None = None,
    is_git_repo: bool = True,
    is_empty: bool = False,
    primary_language: str | None = "Python",
    languages: tuple[LanguageShare, ...] | None = None,
    frameworks: tuple[str, ...] = (),
    source_file_count: int = 13,
    total_file_count: int | None = None,
    total_lines: int = 1300,
    average_lines: float | None = None,
    largest_file_path: str | None = "src/core.py",
    largest_file_lines: int = 220,
    max_indent_depth: int = 3,
    max_indent_path: str | None = "src/core.py",
    longest_function_lines: int = 40,
    longest_function_name: str | None = "pour",
    longest_function_path: str | None = "src/core.py",
    sampled: bool = False,
    scanned_file_count: int | None = None,
    git: GitMetrics | None = None,
    nose: NoseMetrics | None = None,
    structure: StructureMetrics | None = None,
    abandonment: AbandonmentMetrics | None = None,
    sediment: SedimentMetrics | None = None,
    dropped: tuple[DroppedAnalyzer, ...] = (),
) -> RepoMetrics:
    """Build a complete RepoMetrics without touching the filesystem.

    Every field has a plausible default so that a caller can state only the
    numbers its assertion depends on.
    """
    if languages is None:
        languages = (
            ()
            if primary_language is None
            else (
                LanguageShare(
                    name=primary_language,
                    file_count=source_file_count,
                    line_count=total_lines,
                    share=1.0,
                ),
            )
        )
    resolved_total_files = (
        source_file_count if total_file_count is None else total_file_count
    )
    resolved_scanned = (
        source_file_count if scanned_file_count is None else scanned_file_count
    )
    resolved_average = (
        (total_lines / source_file_count if source_file_count else 0.0)
        if average_lines is None
        else average_lines
    )
    palate = PalateMetrics(
        source_file_count=source_file_count,
        total_file_count=resolved_total_files,
        total_lines=total_lines,
        average_lines=resolved_average,
        largest_file_path=largest_file_path,
        largest_file_lines=largest_file_lines,
        max_indent_depth=max_indent_depth,
        max_indent_path=max_indent_path,
        longest_function_lines=longest_function_lines,
        longest_function_name=longest_function_name,
        longest_function_path=longest_function_path,
        sampled=sampled,
        inventory="git",
        scanned_file_count=resolved_scanned,
    )
    return RepoMetrics(
        path=f"/synthetic/{name}" if path is None else path,
        name=name,
        is_git_repo=is_git_repo,
        is_empty=is_empty,
        git=_default_git() if git is None else git,
        terroir=TerroirMetrics(
            languages=languages,
            primary_language=primary_language,
            frameworks=frameworks,
        ),
        nose=_default_nose() if nose is None else nose,
        palate=palate,
        structure=_default_structure() if structure is None else structure,
        abandonment=_default_abandonment() if abandonment is None else abandonment,
        sediment=_default_sediment() if sediment is None else sediment,
        dropped=dropped,
    )


class Fixture:
    """A synthetic repository rooted in a temporary directory."""

    def __init__(self, name: str) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="sommelier-fixture-")
        self.name: str = name
        self.path: Path = Path(self._temporary.name).resolve() / name
        self.path.mkdir(parents=True)

    def cleanup(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> Fixture:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()


def git_available() -> bool:
    """Report whether a usable git binary is on PATH."""
    if shutil.which("git") is None:
        return False
    try:
        completed = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def require_git() -> None:
    """Skip the calling test when git cannot be run."""
    if not git_available():
        raise unittest.SkipTest("git is not available on this machine")


def write_tree(root: Path, files: Mapping[str, str]) -> None:
    """Write a mapping of POSIX relative path to text content under ``root``."""
    for relative in sorted(files):
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[relative], encoding="utf-8", newline="\n")


def write_binary(root: Path, relative: str, payload: bytes) -> None:
    """Write raw bytes to a POSIX relative path under ``root``."""
    target = root.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def binary_blob(size_bytes: int, *, random_bytes: bool = False) -> bytes:
    """Build binary content at test time so no blob is committed to this repo."""
    if random_bytes:
        return os.urandom(size_bytes)
    pattern = bytes(range(256))
    repeats = size_bytes // len(pattern) + 1
    return (pattern * repeats)[:size_bytes]


# A suite launched from a git hook inherits variables that point git at the
# surrounding repository, its index and its extra configuration. Left in place,
# the builders below would initialise and commit into that repository instead of
# into the temporary directory.
_INHERITED_GIT_VARIABLES: Final[tuple[str, ...]] = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_TEMPLATE_DIR",
    "GIT_WORK_TREE",
)


def isolated_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that ignores the machine's own git configuration."""
    env = dict(os.environ)
    for name in _INHERITED_GIT_VARIABLES:
        env.pop(name, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    if extra is not None:
        env.update(extra)
    return env


def run_git(
    args: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run git with an isolated environment and no shell."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=isolated_env() if env is None else dict(env),
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=True,
    )


def git_init(root: Path) -> None:
    """Create a repository with a fixed default branch name."""
    run_git(["-c", "init.defaultBranch=main", "init", "--quiet"], root)


def git_commit(
    root: Path,
    message: str,
    *,
    day: str,
    author_name: str = ADA_NAME,
    author_email: str = ADA_EMAIL,
) -> None:
    """Stage everything and commit it at noon UTC on ``day``."""
    stamp = f"{day}T12:00:00+00:00"
    env = isolated_env(
        {
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
    )
    run_git(["add", "-A"], root, env)
    run_git(
        [
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--no-verify",
            "-m",
            message,
        ],
        root,
        env,
    )


_MIT_LICENSE: Final[str] = """MIT License

Copyright (c) 2021 The Cellar Book Authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""

_HEALTHY_README: Final[str] = """# cellar book

A small library for keeping notes about bottles.

## Install

    pip install -r requirements.txt

## Usage

    from cellar.core import Cellar

See CONTRIBUTING.md for the development workflow.
"""

_HEALTHY_GITIGNORE: Final[str] = """# Python build output
__pycache__/
*.pyc

# Local environment
.venv/
.env
build/
"""

_HEALTHY_REQUIREMENTS: Final[str] = """# Runtime dependencies
click>=8.1
requests==2.31.0
rich>=13.0

# Support libraries
python-dateutil>=2.8
pyyaml>=6.0
tomli>=2.0
"""

_HEALTHY_CORE: Final[str] = '''"""The cellar book core model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bottle:
    name: str
    year: int
    region: str

    def label(self) -> str:
        return f"{self.name} {self.year}"


class Cellar:
    """An ordered collection of bottles."""

    def __init__(self) -> None:
        self._bottles: list[Bottle] = []

    def add(self, bottle: Bottle) -> None:
        self._bottles.append(bottle)

    def remove(self, name: str) -> bool:
        for index, bottle in enumerate(self._bottles):
            if bottle.name == name:
                del self._bottles[index]
                return True
        return False

    def by_year(self, year: int) -> list[Bottle]:
        return [bottle for bottle in self._bottles if bottle.year == year]

    def regions(self) -> list[str]:
        seen: set[str] = set()
        for bottle in self._bottles:
            seen.add(bottle.region)
        return sorted(seen)

    def oldest(self) -> Bottle | None:
        if not self._bottles:
            return None
        return min(self._bottles, key=lambda bottle: bottle.year)

    def newest(self) -> Bottle | None:
        if not self._bottles:
            return None
        return max(self._bottles, key=lambda bottle: bottle.year)

    def count(self) -> int:
        return len(self._bottles)

    def labels(self) -> list[str]:
        return sorted(bottle.label() for bottle in self._bottles)

    def pour(self, name: str) -> Bottle | None:
        for bottle in self._bottles:
            if bottle.name == name:
                return bottle
        return None
'''

_HEALTHY_UTIL: Final[str] = '''"""Small helpers."""

from __future__ import annotations


def normalise(value: str) -> str:
    return value.strip().lower()


def decade(year: int) -> int:
    return year - (year % 10)
'''

_HEALTHY_TEST: Final[str] = '''"""Tests for the core model."""

from __future__ import annotations

import unittest

from cellar.core import Bottle, Cellar


class CellarTest(unittest.TestCase):
    def test_pour_returns_the_bottle(self) -> None:
        cellar = Cellar()
        bottle = Bottle(name="barolo", year=2016, region="piedmont")
        cellar.add(bottle)
        self.assertEqual(cellar.pour("barolo"), bottle)
'''

_HEALTHY_CI: Final[str] = """name: ci

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m unittest discover
"""

_HEALTHY_CONTRIBUTING: Final[str] = """# Contributing

Open an issue before large changes. Run the test suite before opening a pull
request.
"""


def healthy_python_repo() -> Fixture:
    """A tidy Python project with four commits and two authors."""
    fixture = Fixture(HEALTHY_NAME)
    root = fixture.path
    git_init(root)

    write_tree(
        root,
        {
            "README.md": _HEALTHY_README,
            "LICENSE": _MIT_LICENSE,
            ".gitignore": _HEALTHY_GITIGNORE,
        },
    )
    git_commit(root, "Initial commit", day=HEALTHY_FIRST_DAY)

    write_tree(
        root,
        {
            "requirements.txt": _HEALTHY_REQUIREMENTS,
            "src/cellar/__init__.py": "from __future__ import annotations\n",
            "src/cellar/core.py": _HEALTHY_CORE,
        },
    )
    git_commit(root, "Add the core model", day=HEALTHY_SECOND_DAY)

    write_tree(
        root,
        {
            "src/cellar/util.py": _HEALTHY_UTIL,
            "CONTRIBUTING.md": _HEALTHY_CONTRIBUTING,
        },
    )
    git_commit(root, "fix: correct the decade helper", day=HEALTHY_THIRD_DAY)

    write_tree(
        root,
        {
            "tests/test_core.py": _HEALTHY_TEST,
            ".github/workflows/ci.yml": _HEALTHY_CI,
        },
    )
    git_commit(
        root,
        HEALTHY_LAST_SUBJECT,
        day=HEALTHY_LAST_DAY,
        author_name=GRACE_NAME,
        author_email=GRACE_EMAIL,
    )
    return fixture


def _legacy_js() -> str:
    lines: list[str] = []
    stride = NEGLECTED_LEGACY_LINES // NEGLECTED_LEGACY_TODOS
    for index in range(NEGLECTED_LEGACY_LINES):
        if index % stride == 0:
            lines.append(f"// TODO: revisit branch {index}")
        else:
            lines.append(f"const value{index} = {index};")
    return "\n".join(lines) + "\n"


_NEGLECTED_APP: Final[str] = """const express = require("express");

const app = express();

// TODO: move the port into configuration
// TODO: add a health check
// TODO: retire the global cache
// TODO: split this file
// TODO: write one test
// TODO: rename the handler
// FIXME: the session cookie never expires
// FIXME: the error path swallows the stack
// FIXME: this leaks a file handle on restart
// HACK: sleeping here hides a race
// HACK: hard coded user id for the demo
// XXX: do not ship this
// const previous = buildCache(config);
// return previous.get(key);

const cache = {};

function handler(request, response) {
  console.log("request", request.url);
  if (cache[request.url]) {
    console.log("cache hit");
    return response.send(cache[request.url]);
  }
  const body = render(request.url);
  cache[request.url] = body;
  console.log("cache store");
  return response.send(body);
}

function render(url) {
  console.log("render", url);
  return "<html><body>" + url + "</body></html>";
}

app.get("/*", handler);

module.exports = { app, handler, render };
"""

_NEGLECTED_UTIL: Final[str] = """// TODO: replace with the standard library
// TODO: add types
// TODO: delete the dead branch below
// TODO: benchmark this

function pad(value, width) {
  let out = String(value);
  while (out.length < width) {
    out = " " + out;
  }
  return out;
}

module.exports = { pad };
"""

_NEGLECTED_PACKAGE_JSON: Final[str] = """{
  "name": "todo-app",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "start": "node src/app.js"
  },
  "dependencies": {
    "express": "^4.17.1",
    "lodash": "^4.17.15",
    "chalk": "^2.4.2",
    "left-pad": "^1.3.0",
    "moment": "^2.24.0"
  },
  "devDependencies": {
    "eslint": "^6.8.0",
    "jest": "^24.9.0",
    "nodemon": "^2.0.2"
  }
}
"""

_NEGLECTED_ENV: Final[str] = """API_TOKEN=placeholder-value
DATABASE_URL=postgres://local/app
SESSION_SECRET=placeholder-value
"""

_VENDORED_INDEX: Final[str] = """// TODO: vendored marker that must not be counted
// TODO: vendored marker that must not be counted
// TODO: vendored marker that must not be counted

module.exports = function noop(value) {
  console.log("vendored", value);
  console.log("vendored", value);
  return value;
};
"""


def _vendored_files() -> dict[str, str]:
    package = '{"name": "%s", "version": "1.0.0", "main": "index.js"}\n'
    files: dict[str, str] = {
        "node_modules/left-pad/README.md": "# left-pad\n\nVendored copy.\n",
    }
    for name in ("left-pad", "right-pad", "is-odd", "is-even", "chalk"):
        files[f"node_modules/{name}/package.json"] = package % name
        files[f"node_modules/{name}/index.js"] = _VENDORED_INDEX
    files["node_modules/.bin-note.txt"] = "Vendored tooling shims live here.\n"
    return files


def neglected_js_repo() -> Fixture:
    """A JavaScript project with committed vendored code, a secret and rot."""
    fixture = Fixture(NEGLECTED_NAME)
    root = fixture.path
    git_init(root)

    write_tree(
        root,
        {
            "package.json": _NEGLECTED_PACKAGE_JSON,
            "src/app.js": _NEGLECTED_APP,
        },
    )
    git_commit(root, "Initial commit", day=NEGLECTED_FIRST_DAY, author_name=DANA_NAME, author_email=DANA_EMAIL)

    write_tree(root, _vendored_files())
    write_tree(
        root,
        {
            ".env": _NEGLECTED_ENV,
            "src/util.js": _NEGLECTED_UTIL,
            NEGLECTED_LEGACY_PATH: _legacy_js(),
        },
    )
    write_binary(root, ".DS_Store", binary_blob(1024))
    write_binary(root, "src/.DS_Store", binary_blob(1024))
    write_binary(root, NEGLECTED_BINARY_PATH, binary_blob(NEGLECTED_BINARY_BYTES))
    git_commit(root, "Add everything", day=NEGLECTED_SECOND_DAY, author_name=DANA_NAME, author_email=DANA_EMAIL)

    write_tree(root, {"src/util.js": _NEGLECTED_UTIL.replace("width) {", "width) { // adjusted")})
    git_commit(
        root,
        NEGLECTED_LAST_SUBJECT,
        day=NEGLECTED_LAST_DAY,
        author_name=DANA_NAME,
        author_email=DANA_EMAIL,
    )
    return fixture


def bare_directory() -> Fixture:
    """Source files with no git repository anywhere above them."""
    fixture = Fixture("loose-scripts")
    write_tree(
        fixture.path,
        {
            "README.md": "# loose scripts\n\nNo history at all.\n",
            "main.py": "from __future__ import annotations\n\n\ndef main() -> int:\n    return 0\n",
            "helper.py": "from __future__ import annotations\n\n\ndef helper() -> str:\n    return 'ok'\n",
        },
    )
    return fixture


def git_repo_without_commits() -> Fixture:
    """An initialised repository whose history has not started."""
    fixture = Fixture("unstarted")
    git_init(fixture.path)
    write_tree(
        fixture.path,
        {
            "README.md": "# unstarted\n\nNothing has been committed.\n",
            "main.py": "from __future__ import annotations\n\n\ndef main() -> int:\n    return 0\n",
        },
    )
    return fixture


def empty_directory() -> Fixture:
    """A directory with nothing in it."""
    return Fixture("void")


# The markup comment opener carries a character the house style bans in source,
# so it is assembled from its code point.
_MARKUP_OPEN: Final[str] = "<" + chr(33) + "--"

_ZZZ_FILES: Final[dict[str, str]] = {
    "hash.zzz": "value 1\n# TODO: hash comment marker\nvalue 2\n",
    "slash.zzz": "value 1\n// TODO: double slash marker\nvalue 2\n",
    "block.zzz": "value 1\n/* TODO: block comment marker */\nvalue 2\n",
    "sql.zzz": "value 1\n-- TODO: double dash marker\nvalue 2\n",
    "lisp.zzz": "value 1\n; TODO: semicolon marker\nvalue 2\n",
    "tex.zzz": "value 1\n% TODO: percent marker\nvalue 2\n",
    "markup.zzz": f"value 1\n{_MARKUP_OPEN} TODO: markup marker -->\nvalue 2\n",
    "others.zzz": "value 1\n# FIXME: broken\n// HACK: propped up\n/* XXX: unreviewed */\nvalue 2\n",
}


def unknown_language_repo() -> Fixture:
    """Files in an unrecognised language using every known comment syntax."""
    fixture = Fixture("zzz-project")
    write_tree(fixture.path, dict(_ZZZ_FILES))
    return fixture


def _deep_python() -> str:
    lines = ["def deep_function(flag: bool) -> int:", "    total = 0"]
    for level in range(1, DEEP_INDENT_DEPTH):
        lines.append("    " * level + "if flag:")
    lines.append("    " * DEEP_INDENT_DEPTH + "total += 1")
    lines.append("    return total")
    return "\n".join(lines) + "\n"


def _long_python() -> str:
    lines = [
        "def short_helper(value: int) -> int:",
        "    return value + 1",
        "",
        "",
        f"def {LONG_FUNCTION_NAME}(value: int) -> int:",
        "    total = value",
    ]
    for index in range(LONG_FUNCTION_BODY_LINES - 2):
        lines.append(f"    total += {index}")
    lines.append("    return total")
    return "\n".join(lines) + "\n"


def deep_and_long_repo() -> Fixture:
    """A directory holding one deeply nested file and one very long function."""
    fixture = Fixture("nested-things")
    write_tree(
        fixture.path,
        {
            DEEP_PATH: _deep_python(),
            LONG_PATH: _long_python(),
            "README.md": "# nested things\n\nOne deep file and one long file.\n",
        },
    )
    return fixture
