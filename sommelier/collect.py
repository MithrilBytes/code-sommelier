"""Repository measurement.

Every function here is a pure collector. Nothing in this module judges, scores,
or narrates. Absence of an input is recorded as data, never raised. The only
exception that escapes is TastingError, and only when the requested path does
not exist or cannot be read at all.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import shutil
import subprocess
import threading
import time
import tomllib
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

# Built at runtime so that no string literal in this package carries the
# character; the marker still has to be matched in Rust source.
_BANG: Final[str] = chr(33)

MAX_READ_BYTES: Final[int] = 65536
BINARY_SNIFF_BYTES: Final[int] = 8192
STREAM_CHUNK_BYTES: Final[int] = 65536

# Lines and markers are counted over the whole file. The structural analysis,
# which is where the cost is, stops here and says so through Coverage rather
# than reporting a partial number as though it were the file's.
STRUCTURAL_SCAN_CHARS: Final[int] = 65536

# A minified bundle can be one line of several megabytes. The line still
# counts once; only the text handed to the analysis is bounded, so memory
# stays a function of this constant rather than of the largest file present.
MAX_LINE_CHARS: Final[int] = 1 << 20

# Every separator str.splitlines() breaks on. Kept in step with it on purpose:
# the streamed count has to agree with the whole-file count it replaced.
_LINE_BREAKS: Final[str] = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
SOURCE_SAMPLE_LIMIT: Final[int] = 5000
LARGE_BINARY_BYTES: Final[int] = 5 * 1024 * 1024
BINARY_CHECK_BYTES: Final[int] = 1024 * 1024
LOCKFILE_SCAN_BYTES: Final[int] = 4 * 1024 * 1024
GIT_CALL_TIMEOUT: Final[float] = 5.0
MANIFEST_MAX_DEPTH: Final[int] = 2
MANIFEST_LIMIT: Final[int] = 25

_WALK_FRACTION: Final[float] = 0.45
_GIT_FRACTION: Final[float] = 0.75

VENDORED_DIRS: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        ".git",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "bower_components",
        "Pods",
        ".gradle",
        ".next",
        ".nuxt",
        "out",
        "coverage",
        "site-packages",
        ".terraform",
        "elm-stuff",
        ".svelte-kit",
        "obj",
        ".dart_tool",
        "DerivedData",
        "_build",
        "deps",
        ".stack-work",
        "env",
        ".direnv",
        ".turbo",
        ".parcel-cache",
        ".bundle",
        ".cargo",
        ".yarn",
        "vendor-bundle",
    }
)

# .git is skipped for every purpose, including sediment. It is plumbing.
_SILENT_DIRS: Final[frozenset[str]] = frozenset({".git"})


class TastingError(Exception):
    """Raised only when the path cannot be opened at all."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class GitMetrics:
    is_repo: bool
    has_commits: bool
    shallow: bool
    first_commit_date: str | None
    last_commit_date: str | None
    first_commit_year: int | None
    last_commit_year: int | None
    commit_count: int
    fix_commit_count: int
    fix_ratio: float
    longest_gap_days: int
    longest_gap_start: str | None
    longest_gap_end: str | None
    days_since_last_commit: int
    author_count: int
    top_author_name: str | None
    top_author_commits: int
    top_author_share: float
    last_commit_subject: str | None


@dataclass(frozen=True)
class LanguageShare:
    name: str
    file_count: int
    line_count: int
    share: float


@dataclass(frozen=True)
class TerroirMetrics:
    languages: tuple[LanguageShare, ...]
    primary_language: str | None
    frameworks: tuple[str, ...]


@dataclass(frozen=True)
class NoseMetrics:
    readme_path: str | None
    readme_lines: int
    readme_bytes: int
    license_path: str | None
    license_name: str | None
    gitignore_path: str | None
    gitignore_rules: int
    has_contributing: bool
    has_ci: bool
    has_tests: bool


@dataclass(frozen=True)
class LanguagePalate:
    """One language's share of the palate, measured over the files scanned.

    The repository wide scalars on PalateMetrics answer "how deep does this
    tree nest", which is a question about a tree that may hold four languages
    with four different answers. These answer it one language at a time, so a
    depth of nine in Python and a depth of two in Go stay distinguishable.
    """

    name: str
    """The language, or the empty string for the unattributed bucket."""

    file_count: int
    """Files of this language the scan actually read."""

    line_count: int
    max_indent_depth: int
    max_indent_path: str | None
    largest_file_lines: int
    largest_file_path: str | None
    longest_function_lines: int
    longest_function_name: str | None
    longest_function_path: str | None
    function_detector_ran: bool
    """Whether a function detector exists for this language and ran.

    False makes longest_function_lines of zero readable as "not measured"
    rather than as "the longest function here is nothing".
    """


@dataclass(frozen=True)
class PalateMetrics:
    source_file_count: int
    total_file_count: int
    total_lines: int
    average_lines: float
    largest_file_path: str | None
    largest_file_lines: int
    max_indent_depth: int
    max_indent_path: str | None
    longest_function_lines: int
    longest_function_name: str | None
    longest_function_path: str | None
    sampled: bool
    scanned_file_count: int
    inventory: str
    """Where the file list came from: "git" or "filesystem".

    Printed by --sober and carried in --json so a reader can tell whether the
    counts were filtered by git or taken straight off the disk.
    """

    by_language: tuple[LanguagePalate, ...]
    """The same measurements split by language, unattributed files included.

    Ordered by file count and then by name, so the tuple is stable.
    """


@dataclass(frozen=True)
class DependencyManifest:
    ecosystem: str
    manifest_path: str
    declared_count: int
    dev_count: int
    lockfile_path: str | None
    locked_count: int
    drift: bool
    drift_reason: str | None


@dataclass(frozen=True)
class StructureMetrics:
    manifests: tuple[DependencyManifest, ...]
    total_declared: int
    undeclared: bool
    ecosystems: tuple[str, ...]


@dataclass(frozen=True)
class AbandonmentMetrics:
    todo: int
    fixme: int
    hack: int
    xxx: int
    total: int
    per_kloc: float
    worst_file_path: str | None
    worst_file_count: int
    debug_print_count: int
    commented_out_code_lines: int


@dataclass(frozen=True)
class SedimentItem:
    kind: str
    path: str
    detail: str
    size_bytes: int
    file_count: int


@dataclass(frozen=True)
class SedimentMetrics:
    items: tuple[SedimentItem, ...]
    vendored_file_count: int
    vendored_dir_count: int
    secret_file_count: int
    os_cruft_count: int
    large_binary_count: int
    largest_binary_path: str | None
    largest_binary_bytes: int


@dataclass(frozen=True)
class DroppedAnalyzer:
    name: str
    reason: str


@dataclass(frozen=True)
class Coverage:
    """What was measured, stated separately from what the measurements say.

    Zero is a number and absence is not. Without this record the two are the
    same value: a repository with no function detector for its language and a
    repository whose longest function is nothing both report zero, and every
    layer above has to guess which it is holding. Each field below answers
    one question, and answers it about the run that produced this record.
    """

    lines_complete: bool
    """Every text file in the source set was counted to its last line.

    False when a read stopped at the budget, and false when the barrel sample
    or the budget meant some files were never opened at all. A binary file is
    not counted against it, having no lines to miss.
    """

    truncated_files: int
    """Files whose read stopped early, so their line count is a floor."""

    structural_scan_complete: bool
    """Every line that was counted was also analysed, all the way through.

    False when a file ran past the structural cap, so its nesting depth and
    function length describe its head rather than the file. False also when
    lines_complete is false, since a file that was never read was never
    analysed either.
    """

    function_detector_files: int
    """Files a function length detector actually ran on."""

    attributed_files: int
    """Source files whose name or extension identified a language."""

    source_files: int
    """Source files found, attributed or not. The denominator for the above."""

    history_complete: bool
    """git answered, the repository has commits, and the clone is not shallow.

    A shallow clone reports a first commit that is not the first commit, so
    age, gaps and commit counts measured over it describe the clone rather
    than the project.
    """

    authorship_measured: bool
    """At least one author was counted, so the bus factor rests on evidence."""

    dependencies_measured: bool
    """A dependency manifest was found, so a count of zero means zero."""


@dataclass(frozen=True)
class RepoMetrics:
    path: str
    name: str
    is_git_repo: bool
    is_empty: bool
    git: GitMetrics
    terroir: TerroirMetrics
    nose: NoseMetrics
    palate: PalateMetrics
    coverage: Coverage
    structure: StructureMetrics
    abandonment: AbandonmentMetrics
    sediment: SedimentMetrics
    dropped: tuple[DroppedAnalyzer, ...]


LANGUAGE_BY_EXTENSION: Final[Mapping[str, str]] = {
    ".ada": "Ada",
    ".adb": "Ada",
    ".ads": "Ada",
    ".asm": "Assembly",
    ".astro": "Astro",
    ".awk": "Awk",
    ".bash": "Shell",
    ".bat": "Batchfile",
    ".bzl": "Starlark",
    ".c": "C",
    ".cc": "C++",
    ".clj": "Clojure",
    ".cljc": "Clojure",
    ".cljs": "Clojure",
    ".cmake": "CMake",
    ".cmd": "Batchfile",
    ".coffee": "CoffeeScript",
    ".cpp": "C++",
    ".cr": "Crystal",
    ".cs": "C#",
    ".css": "CSS",
    ".cts": "TypeScript",
    ".cxx": "C++",
    ".d": "D",
    ".dart": "Dart",
    ".el": "Emacs Lisp",
    ".elm": "Elm",
    ".erb": "ERB",
    ".erl": "Erlang",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".f": "Fortran",
    ".f03": "Fortran",
    ".f90": "Fortran",
    ".f95": "Fortran",
    ".fish": "Fish",
    ".for": "Fortran",
    ".fs": "F#",
    ".fsx": "F#",
    ".go": "Go",
    ".gql": "GraphQL",
    ".gradle": "Groovy",
    ".graphql": "GraphQL",
    ".groovy": "Groovy",
    ".h": "C",
    ".hbs": "Handlebars",
    ".hcl": "HCL",
    ".hh": "C++",
    ".hpp": "C++",
    ".hrl": "Erlang",
    ".hs": "Haskell",
    ".htm": "HTML",
    ".html": "HTML",
    ".hx": "Haxe",
    ".hxx": "C++",
    ".ipynb": "Jupyter Notebook",
    ".java": "Java",
    ".jl": "Julia",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".less": "Less",
    ".lhs": "Haskell",
    ".lisp": "Lisp",
    ".lua": "Lua",
    ".m": "Objective-C",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ml": "OCaml",
    ".mli": "OCaml",
    ".mm": "Objective-C++",
    ".mts": "TypeScript",
    ".nim": "Nim",
    ".pas": "Pascal",
    ".php": "PHP",
    ".pl": "Perl",
    ".pm": "Perl",
    ".proto": "Protocol Buffers",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".pug": "Pug",
    ".purs": "PureScript",
    ".py": "Python",
    ".pyi": "Python",
    ".pyw": "Python",
    ".r": "R",
    ".rake": "Ruby",
    ".rb": "Ruby",
    ".re": "Reason",
    ".rkt": "Racket",
    ".rmd": "R",
    ".rs": "Rust",
    ".s": "Assembly",
    ".sass": "Sass",
    ".sc": "Scala",
    ".scala": "Scala",
    ".scm": "Scheme",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sol": "Solidity",
    ".sql": "SQL",
    ".styl": "Stylus",
    ".sv": "SystemVerilog",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".tex": "TeX",
    ".tf": "HCL",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".twig": "Twig",
    ".v": "Verilog",
    ".vb": "Visual Basic",
    ".vhd": "VHDL",
    ".vhdl": "VHDL",
    ".vue": "Vue",
    ".zig": "Zig",
    ".zsh": "Shell",
}

LANGUAGE_BY_FILENAME: Final[Mapping[str, str]] = {
    "BUILD": "Starlark",
    "CMakeLists.txt": "CMake",
    "Dockerfile": "Dockerfile",
    "Gemfile": "Ruby",
    "GNUmakefile": "Makefile",
    "Jenkinsfile": "Groovy",
    "Makefile": "Makefile",
    "Podfile": "Ruby",
    "Rakefile": "Ruby",
    "Vagrantfile": "Ruby",
    "WORKSPACE": "Starlark",
    "makefile": "Makefile",
}

# The markup opener carries a character the house style keeps out of literals.
_MARKUP_OPEN: Final[str] = "<" + _BANG + "--"
_MARKUP_CLOSE: Final[str] = "-->"

_ALL_COMMENT_TOKENS: Final[tuple[str, ...]] = (_MARKUP_OPEN, "/*", "//", "--", "#", ";", "%")
_AMBIGUOUS_TOKENS: Final[frozenset[str]] = frozenset({"--", ";", "%"})

_HASH_ONLY: Final[tuple[str, ...]] = ("#",)
_PYTHON_TOKENS: Final[tuple[str, ...]] = ("#", '"""', "'''")
_SLASH_ONLY: Final[tuple[str, ...]] = ("//", "/*")
_SLASH_AND_HASH: Final[tuple[str, ...]] = ("//", "/*", "#")
_DASH_ONLY: Final[tuple[str, ...]] = ("--",)
_SEMI_ONLY: Final[tuple[str, ...]] = (";",)
_PERCENT_ONLY: Final[tuple[str, ...]] = ("%",)
_MARKUP_ONLY: Final[tuple[str, ...]] = (_MARKUP_OPEN,)
_BLOCK_ONLY: Final[tuple[str, ...]] = ("/*",)
_MIXED_MARKUP: Final[tuple[str, ...]] = (_MARKUP_OPEN, "//", "/*")

_COMMENT_TOKENS_BY_LANGUAGE: Final[Mapping[str, tuple[str, ...]]] = {
    "Ada": _DASH_ONLY,
    "Assembly": _SEMI_ONLY,
    "Astro": _MIXED_MARKUP,
    "Awk": _HASH_ONLY,
    "C": _SLASH_ONLY,
    "C#": _SLASH_ONLY,
    "C++": _SLASH_ONLY,
    "CMake": _HASH_ONLY,
    "CSS": _BLOCK_ONLY,
    "Clojure": _SEMI_ONLY,
    "CoffeeScript": _HASH_ONLY,
    "Crystal": _HASH_ONLY,
    "D": _SLASH_ONLY,
    "Dart": _SLASH_ONLY,
    "Dockerfile": _HASH_ONLY,
    "Elixir": _HASH_ONLY,
    "Elm": _DASH_ONLY,
    "Emacs Lisp": _SEMI_ONLY,
    "Erlang": _PERCENT_ONLY,
    "F#": _SLASH_ONLY,
    "Fish": _HASH_ONLY,
    "Go": _SLASH_ONLY,
    "GraphQL": _HASH_ONLY,
    "Groovy": _SLASH_ONLY,
    "HCL": _SLASH_AND_HASH,
    "HTML": _MARKUP_ONLY,
    "Handlebars": _MARKUP_ONLY,
    "Haskell": _DASH_ONLY,
    "Haxe": _SLASH_ONLY,
    "Java": _SLASH_ONLY,
    "JavaScript": _SLASH_ONLY,
    "Julia": _PYTHON_TOKENS,
    "Kotlin": _SLASH_ONLY,
    "Less": _SLASH_ONLY,
    "Lisp": _SEMI_ONLY,
    "Lua": _DASH_ONLY,
    "Makefile": _HASH_ONLY,
    "Nim": _HASH_ONLY,
    "OCaml": _BLOCK_ONLY,
    "Objective-C": _SLASH_ONLY,
    "Objective-C++": _SLASH_ONLY,
    "PHP": _SLASH_AND_HASH,
    "Pascal": _SLASH_ONLY,
    "Perl": _HASH_ONLY,
    "PowerShell": _HASH_ONLY,
    "Protocol Buffers": _SLASH_ONLY,
    "PureScript": _DASH_ONLY,
    "Python": _HASH_ONLY,
    "R": _HASH_ONLY,
    "Racket": _SEMI_ONLY,
    "Reason": _SLASH_ONLY,
    "Ruby": _HASH_ONLY,
    "Rust": _SLASH_ONLY,
    "SCSS": _SLASH_ONLY,
    "SQL": ("--", "/*"),
    "Sass": _SLASH_ONLY,
    "Scala": _SLASH_ONLY,
    "Scheme": _SEMI_ONLY,
    "Shell": _HASH_ONLY,
    "Solidity": _SLASH_ONLY,
    "Starlark": _HASH_ONLY,
    "Stylus": _SLASH_ONLY,
    "Svelte": _MIXED_MARKUP,
    "Swift": _SLASH_ONLY,
    "SystemVerilog": _SLASH_ONLY,
    "TeX": _PERCENT_ONLY,
    "TypeScript": _SLASH_ONLY,
    "VHDL": _DASH_ONLY,
    "Verilog": _SLASH_ONLY,
    "Vue": _MIXED_MARKUP,
    "Zig": _SLASH_ONLY,
}

_BRACE_LANGUAGES: Final[frozenset[str]] = frozenset(
    {
        "Astro",
        "C",
        "C#",
        "C++",
        "D",
        "Dart",
        "Go",
        "Groovy",
        "Haxe",
        "Java",
        "JavaScript",
        "Kotlin",
        "Objective-C",
        "Objective-C++",
        "PHP",
        "Reason",
        "Rust",
        "Scala",
        "Solidity",
        "Svelte",
        "Swift",
        "TypeScript",
        "Vue",
        "Zig",
    }
)

_FUNCTION_FAMILY: Final[Mapping[str, str]] = {
    **{name: "brace" for name in _BRACE_LANGUAGES},
    "Python": "python",
    "Ruby": "ruby",
}

_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")

_PY_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9_.\-]+")

_DEBUG_PRINT_RE: Final[re.Pattern[str]] = re.compile(
    r"\bconsole\s*\.\s*(?:log|debug|info|warn|trace)\s*\("
    r"|\bprint\s*\("
    r"|\bprintln" + _BANG + r"\s*\("
    r"|\bdbg" + _BANG + r"\s*\("
    r"|\bfmt\.Print(?:ln|f)?\s*\("
    r"|\bSystem\.out\.print(?:ln)?\s*\("
    r"|\bvar_dump\s*\("
    r"|\bNSLog\s*\("
)

_CODE_SHAPE_RE: Final[re.Pattern[str]] = re.compile(
    r"[;{}]\s*$"
    r"|^(?:import|package|def|class|func|fn|function|var|let|const|public|private|"
    r"protected|static|echo|return)\s+[\w$*(\[\"']"
    r"|^(?:if|else|elif|for|while|switch|case|catch)\s*[({:]"
    r"|^[\w.\[\]\"']{1,60}\s*[-+*/|&^]?=[^=]"
    r"|^[\w.]{1,60}\([^()]{0,120}\)\s*;?\s*$"
    r"|^</?[A-Za-z][^>]{0,120}>\s*$"
)

_PY_DEF_RE: Final[re.Pattern[str]] = re.compile(r"^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)")
_RUBY_DEF_RE: Final[re.Pattern[str]] = re.compile(r"^(\s*)def\s+([A-Za-z_][\w.?]*)")
_GO_FUNC_RE: Final[re.Pattern[str]] = re.compile(r"^\s*func\s+(?:\([^)]{0,80}\)\s*)?([A-Za-z_]\w*)?")
_RUST_FN_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:fn|fun)\s+([A-Za-z_]\w*)")
_JS_FUNCTION_RE: Final[re.Pattern[str]] = re.compile(
    r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)?\s*\("
)
_ARROW_FUNC_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]{0,80})?=\s*"
    r"(?:async\s*)?[^=;{}]{0,120}=>"
)
_NAME_CALL_RE: Final[re.Pattern[str]] = re.compile(r"([A-Za-z_$~][\w$]*)\s*\(")
_LEADING_WORD_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_$][\w$]*")

_CONTROL_WORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "assert",
        "await",
        "case",
        "catch",
        "delete",
        "do",
        "elif",
        "else",
        "for",
        "foreach",
        "if",
        "in",
        "new",
        "not",
        "of",
        "or",
        "print",
        "raise",
        "require",
        "return",
        "sizeof",
        "switch",
        "throw",
        "typeof",
        "unless",
        "until",
        "when",
        "while",
        "with",
        "yield",
    }
)

_TEST_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {"test", "tests", "spec", "specs", "__tests__", "testing", "unittests"}
)

_TEST_FILE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:test_.+|.+_test\..+|.+\.test\..+|.+\.spec\..+|.+Test\.\w+|.+Tests\.\w+|.+Spec\.\w+)$"
)

_CI_FILES: Final[frozenset[str]] = frozenset(
    {
        ".gitlab-ci.yml",
        ".travis.yml",
        ".drone.yml",
        ".woodpecker.yml",
        "appveyor.yml",
        "azure-pipelines.yml",
        "bitbucket-pipelines.yml",
        "Jenkinsfile",
        "wercker.yml",
        "cloudbuild.yaml",
    }
)

_CI_PREFIXES: Final[tuple[str, ...]] = (
    ".github/workflows/",
    ".circleci/",
    ".buildkite/",
    ".teamcity/",
)

_OS_CRUFT_NAMES: Final[frozenset[str]] = frozenset(
    {".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100", ".Trashes", "ehthumbs.db"}
)

_EDITOR_DIRS: Final[frozenset[str]] = frozenset({".idea", ".vs", ".vscode", ".settings"})

_EDITOR_SUFFIXES: Final[tuple[str, ...]] = (
    ".swp",
    ".swo",
    ".iml",
    ".sublime-project",
    ".sublime-workspace",
    ".bak",
    ".orig",
    ".rej",
)

_SECRET_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".env",
        ".envrc",
        ".netrc",
        ".pgpass",
        ".npmrc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "service-account.json",
    }
)

_SECRET_SUFFIXES: Final[tuple[str, ...]] = (".pem", ".p12", ".pfx", ".jks", ".keystore", ".ppk")

_SECRET_SAFE_SUFFIXES: Final[tuple[str, ...]] = (
    ".example",
    ".sample",
    ".template",
    ".dist",
    ".tpl",
)

_LICENSE_SIGNATURES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("AGPL-3.0", ("GNU AFFERO GENERAL PUBLIC LICENSE",)),
    ("LGPL-3.0", ("GNU LESSER GENERAL PUBLIC LICENSE", "VERSION 3")),
    ("LGPL-2.1", ("GNU LESSER GENERAL PUBLIC LICENSE", "VERSION 2.1")),
    ("GPL-3.0", ("GNU GENERAL PUBLIC LICENSE", "VERSION 3")),
    ("GPL-2.0", ("GNU GENERAL PUBLIC LICENSE", "VERSION 2")),
    ("Apache-2.0", ("APACHE LICENSE", "VERSION 2.0")),
    ("MPL-2.0", ("MOZILLA PUBLIC LICENSE", "2.0")),
    ("EPL-2.0", ("ECLIPSE PUBLIC LICENSE", "V 2.0")),
    ("EPL-1.0", ("ECLIPSE PUBLIC LICENSE",)),
    ("BSL-1.0", ("BOOST SOFTWARE LICENSE",)),
    ("CC0-1.0", ("CC0 1.0",)),
    ("Unlicense", ("THIS IS FREE AND UNENCUMBERED SOFTWARE",)),
    ("ISC", ("PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE",)),
    ("MIT", ("PERMISSION IS HEREBY GRANTED, FREE OF CHARGE",)),
    ("MIT", ("MIT LICENSE",)),
    ("WTFPL", ("WTFPL",)),
)

_JS_FRAMEWORKS: Final[Mapping[str, str]] = {
    "@angular/core": "Angular",
    "@nestjs/core": "NestJS",
    "@remix-run/react": "Remix",
    "@sveltejs/kit": "SvelteKit",
    "astro": "Astro",
    "backbone": "Backbone.js",
    "bootstrap": "Bootstrap",
    "cypress": "Cypress",
    "d3": "D3",
    "electron": "Electron",
    "ember-source": "Ember.js",
    "express": "Express",
    "fastify": "Fastify",
    "gatsby": "Gatsby",
    "jest": "Jest",
    "jquery": "jQuery",
    "koa": "Koa",
    "mocha": "Mocha",
    "mongoose": "Mongoose",
    "next": "Next.js",
    "nuxt": "Nuxt",
    "playwright": "Playwright",
    "preact": "Preact",
    "prisma": "Prisma",
    "react": "React",
    "react-native": "React Native",
    "redux": "Redux",
    "sequelize": "Sequelize",
    "socket.io": "Socket.IO",
    "solid-js": "SolidJS",
    "svelte": "Svelte",
    "tailwindcss": "Tailwind CSS",
    "three": "Three.js",
    "typeorm": "TypeORM",
    "vite": "Vite",
    "vue": "Vue",
    "webpack": "webpack",
}

_PY_FRAMEWORKS: Final[Mapping[str, str]] = {
    "aiohttp": "aiohttp",
    "bottle": "Bottle",
    "celery": "Celery",
    "click": "Click",
    "django": "Django",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "numpy": "NumPy",
    "pandas": "pandas",
    "pydantic": "Pydantic",
    "pyramid": "Pyramid",
    "pytest": "pytest",
    "requests": "Requests",
    "sanic": "Sanic",
    "scikit-learn": "scikit-learn",
    "scipy": "SciPy",
    "scrapy": "Scrapy",
    "sqlalchemy": "SQLAlchemy",
    "starlette": "Starlette",
    "streamlit": "Streamlit",
    "tensorflow": "TensorFlow",
    "torch": "PyTorch",
    "tornado": "Tornado",
    "typer": "Typer",
}

_GO_FRAMEWORKS: Final[Mapping[str, str]] = {
    "github.com/gin-gonic/gin": "Gin",
    "github.com/gofiber/fiber": "Fiber",
    "github.com/gorilla/mux": "Gorilla",
    "github.com/labstack/echo": "Echo",
    "github.com/spf13/cobra": "Cobra",
    "github.com/stretchr/testify": "Testify",
    "google.golang.org/grpc": "gRPC",
    "gorm.io/gorm": "GORM",
    "k8s.io/client-go": "client-go",
}

_RUST_FRAMEWORKS: Final[Mapping[str, str]] = {
    "actix-web": "Actix Web",
    "axum": "Axum",
    "bevy": "Bevy",
    "clap": "clap",
    "diesel": "Diesel",
    "rocket": "Rocket",
    "serde": "Serde",
    "sqlx": "SQLx",
    "tauri": "Tauri",
    "tokio": "Tokio",
    "warp": "Warp",
    "yew": "Yew",
}

_TEXT_FRAMEWORK_SIGNATURES: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    "Gemfile": (("rails", "Rails"), ("sinatra", "Sinatra"), ("jekyll", "Jekyll"), ("hanami", "Hanami")),
    "composer.json": (
        ("laravel/framework", "Laravel"),
        ("symfony/", "Symfony"),
        ("cakephp/", "CakePHP"),
        ("slim/slim", "Slim"),
    ),
    "pom.xml": (
        ("spring-boot", "Spring Boot"),
        ("springframework", "Spring"),
        ("hibernate", "Hibernate"),
        ("quarkus", "Quarkus"),
        ("micronaut", "Micronaut"),
    ),
    "build.gradle": (
        ("spring-boot", "Spring Boot"),
        ("springframework", "Spring"),
        ("com.android.application", "Android"),
    ),
    "build.gradle.kts": (
        ("spring-boot", "Spring Boot"),
        ("springframework", "Spring"),
        ("com.android.application", "Android"),
    ),
    "pubspec.yaml": (("flutter:", "Flutter"),),
}

_MARKER_FILE_FRAMEWORKS: Final[Mapping[str, str]] = {
    "angular.json": "Angular",
    "artisan": "Laravel",
    "astro.config.mjs": "Astro",
    "astro.config.ts": "Astro",
    "bin/rails": "Rails",
    "config/application.rb": "Rails",
    "docker-compose.yaml": "Docker Compose",
    "docker-compose.yml": "Docker Compose",
    "Dockerfile": "Docker",
    "gatsby-config.js": "Gatsby",
    "manage.py": "Django",
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "next.config.ts": "Next.js",
    "nuxt.config.js": "Nuxt",
    "nuxt.config.ts": "Nuxt",
    "serverless.yml": "Serverless",
    "svelte.config.js": "Svelte",
    "tailwind.config.js": "Tailwind CSS",
    "tailwind.config.ts": "Tailwind CSS",
    "vite.config.js": "Vite",
    "vite.config.ts": "Vite",
    "vue.config.js": "Vue",
    "webpack.config.js": "webpack",
    "Chart.yaml": "Helm",
    "AndroidManifest.xml": "Android",
}

_MANIFEST_ECOSYSTEMS: Final[Mapping[str, str]] = {
    "package.json": "javascript",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "go.mod": "go",
    "Cargo.toml": "rust",
}

_LOCKFILES_BY_MANIFEST: Final[Mapping[str, tuple[str, ...]]] = {
    "package.json": ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"),
    "requirements.txt": ("requirements.lock",),
    "pyproject.toml": ("poetry.lock", "uv.lock", "pdm.lock"),
    "go.mod": ("go.sum",),
    "Cargo.toml": ("Cargo.lock",),
}

_LOCK_MARKERS: Final[Mapping[str, str]] = {
    "package-lock.json": '"resolved":',
    "npm-shrinkwrap.json": '"resolved":',
    # Yarn 1 writes `version "1.2.3"`, Yarn 2 and later write `version: 1.2.3`.
    "yarn.lock": "\n  version",
    "pnpm-lock.yaml": "resolution:",
    "poetry.lock": "[[package]]",
    "uv.lock": "[[package]]",
    "pdm.lock": "[[package]]",
    "Cargo.lock": "[[package]]",
    "go.sum": "/go.mod h1:",
    "requirements.lock": "\n",
}


class _Budget:
    """A monotonic deadline shared by every collection phase."""

    def __init__(self, seconds: float) -> None:
        self._start = time.monotonic()
        self._seconds = max(0.0, seconds)

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def expired(self) -> bool:
        return self.elapsed() >= self._seconds

    def over(self, fraction: float) -> bool:
        return self.elapsed() >= self._seconds * fraction

    def remaining(self) -> float:
        return max(0.0, self._seconds - self.elapsed())

    def remaining_before(self, fraction: float) -> float:
        return max(0.0, self._seconds * fraction - self.elapsed())


@dataclass(frozen=True)
class _FileRecord:
    rel: str
    name: str
    ext: str
    size: int
    depth: int
    language: str | None


@dataclass(frozen=True)
class _VendoredDir:
    rel: str
    file_count: int
    size_bytes: int


@dataclass(frozen=True)
class _WalkResult:
    files: tuple[_FileRecord, ...]
    directories: tuple[str, ...]
    vendored: tuple[_VendoredDir, ...]
    vendored_file_count: int
    vendored_bytes: int
    editor_dirs: tuple[_VendoredDir, ...]
    truncated: bool


@dataclass(frozen=True)
class _FileAnalysis:
    lines: int
    max_depth: int
    function_lines: int
    function_name: str | None
    todo: int
    fixme: int
    hack: int
    xxx: int
    debug_prints: int
    commented_code: int
    complete: bool
    """The read reached the end of the file, so `lines` is the file's length."""

    structural_complete: bool
    """The structural cap was not reached, so depth and length cover it all."""

    function_detector_ran: bool
    """A detector exists for this language, so zero means zero."""


@dataclass
class _ReadState:
    """How much of one file reached the analysis. Written by the reader."""

    complete: bool = False
    """The byte stream was drained, so every line of the file was counted."""

    truncated_line: bool = False
    """A line ran past MAX_LINE_CHARS and its tail was dropped."""


@dataclass
class _LanguageTally:
    """One language's running totals while the scan walks the file list."""

    name: str
    file_count: int = 0
    line_count: int = 0
    max_indent_depth: int = 0
    max_indent_path: str | None = None
    largest_file_lines: int = 0
    largest_file_path: str | None = None
    longest_function_lines: int = 0
    longest_function_name: str | None = None
    longest_function_path: str | None = None
    function_detector_ran: bool = False


@dataclass(frozen=True)
class _ScanResult:
    palate: PalateMetrics
    abandonment: AbandonmentMetrics
    lines_by_language: Mapping[str, int]
    truncated: bool
    lines_complete: bool
    truncated_files: int
    structural_scan_complete: bool
    function_detector_files: int
    attributed_files: int


def collect(path: Path, *, budget_seconds: float = 10.0) -> RepoMetrics:
    """Measure a directory. Raises TastingError only for an unreadable path."""
    budget = _Budget(budget_seconds)
    resolved = _resolve(path)
    dropped: list[DroppedAnalyzer] = []

    walk = _walk(resolved, budget)
    if walk.truncated:
        dropped.append(DroppedAnalyzer(name="tree", reason="exceeded time budget"))

    records = walk.files
    rel_paths = frozenset(record.rel for record in records)
    by_rel = {record.rel: record for record in records}

    # Both filters are needed. The git set drops ignored build output, and the
    # vendored prune already applied in _walk drops node_modules in the repos
    # that never told git to ignore it.
    project = _project_index(resolved, budget)
    inventory = "filesystem" if project is None else "git"
    if project is None and (resolved / ".git").exists():
        dropped.append(DroppedAnalyzer(name="inventory", reason="git unavailable"))
    source_records = tuple(
        record
        for record in records
        if _is_source(record) and (project is None or record.rel in project)
    )

    nose = _nose(resolved, records, walk.directories)
    structure = _structure(resolved, records)
    sediment = _sediment(resolved, walk, records, budget)
    git, git_truncated = _git(resolved, budget)
    if git_truncated:
        dropped.append(DroppedAnalyzer(name="git", reason="exceeded time budget"))

    scan = _scan(
        resolved,
        source_records,
        budget,
        len(records) + walk.vendored_file_count,
        inventory,
    )
    if scan.truncated:
        dropped.append(DroppedAnalyzer(name="abandonment", reason="exceeded time budget"))
        dropped.append(DroppedAnalyzer(name="palate", reason="exceeded time budget"))

    terroir = _terroir(resolved, source_records, scan.lines_by_language, rel_paths, by_rel)
    # A walk that stopped early leaves files nobody counted, which is the
    # same gap as a file nobody finished reading, arriving one level up.
    walked_all = not walk.truncated
    coverage = Coverage(
        lines_complete=scan.lines_complete and walked_all,
        truncated_files=scan.truncated_files,
        structural_scan_complete=scan.structural_scan_complete and walked_all,
        function_detector_files=scan.function_detector_files,
        attributed_files=scan.attributed_files,
        source_files=scan.palate.source_file_count,
        history_complete=git.is_repo and git.has_commits and not git.shallow,
        authorship_measured=git.author_count > 0,
        dependencies_measured=bool(structure.manifests),
    )

    is_empty = scan.palate.source_file_count == 0 and not git.has_commits
    return RepoMetrics(
        path=str(resolved),
        name=resolved.name if resolved.name else resolved.as_posix(),
        is_git_repo=git.is_repo,
        is_empty=is_empty,
        git=git,
        terroir=terroir,
        nose=nose,
        palate=scan.palate,
        coverage=coverage,
        structure=structure,
        abandonment=scan.abandonment,
        sediment=sediment,
        dropped=tuple(sorted(set(dropped), key=lambda item: (item.name, item.reason))),
    )


def _resolve(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise TastingError(f"cannot resolve the path {path}") from exc
    try:
        exists = resolved.exists()
    except OSError as exc:
        raise TastingError(f"cannot read the path {resolved}") from exc
    if not exists:
        raise TastingError(f"no such path: {resolved}")
    try:
        is_directory = resolved.is_dir()
    except OSError as exc:
        raise TastingError(f"cannot read the path {resolved}") from exc
    if not is_directory:
        raise TastingError(f"not a directory: {resolved}")
    try:
        with os.scandir(resolved) as entries:
            for _ in entries:
                break
    except OSError as exc:
        raise TastingError(f"cannot read the directory {resolved}") from exc
    return resolved


# Documents, data and binaries. Anything not listed here and not in
# LANGUAGE_BY_EXTENSION is still measured as source, so a language the tool has
# never heard of gets tasted rather than skipped.
NON_CODE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".adoc", ".markdown", ".md", ".odt", ".pdf", ".rst", ".rtf", ".txt",
        ".cfg", ".conf", ".csv", ".ini", ".json", ".jsonl", ".lock", ".log",
        ".map", ".plist", ".properties", ".sum", ".toml", ".tsv", ".xml",
        ".yaml", ".yml",
        ".avif", ".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg",
        ".tif", ".tiff", ".webp",
        ".aac", ".avi", ".flac", ".mkv", ".mov", ".mp3", ".mp4", ".ogg",
        ".wav", ".webm",
        ".eot", ".otf", ".ttf", ".woff", ".woff2",
        ".7z", ".bz2", ".gz", ".jar", ".rar", ".tar", ".war", ".whl", ".xz",
        ".zip", ".egg",
        ".a", ".bin", ".class", ".db", ".dll", ".dylib", ".exe", ".o", ".obj",
        ".pdb", ".pyc", ".pyd", ".pyo", ".so", ".sqlite", ".sqlite3", ".wasm",
        ".crt", ".der", ".key", ".p12", ".pem",
        # Vector, CAD and page-description formats. These are text or partly
        # text, so a binary sniff does not catch them, and their coordinate
        # payloads are deeply indented. Left in, an Illustrator logo wins the
        # nesting-depth finding outright.
        ".ai", ".eps", ".ps", ".dxf", ".stl", ".obj", ".gltf", ".step", ".stp",
        ".iges", ".igs", ".fbx", ".blend", ".sketch", ".fig", ".psd", ".xcf",
        # Generated or transcribed text that nobody authored as code.
        ".snap", ".patch", ".diff", ".po", ".pot", ".mo", ".srt", ".vtt",
        ".ics", ".rtfd", ".dat",
    }
)

# A secret-looking file inside one of these is a test fixture. Shipping an
# expired certificate is how an HTTPS test suite is written, and calling it a
# leak is both wrong and the kind of wrong that gets the tool ignored.
_FIXTURE_DIRS: Final[frozenset[str]] = frozenset(
    {
        "test",
        "tests",
        "testdata",
        "test_data",
        "testing",
        "__tests__",
        "fixture",
        "fixtures",
        "spec",
        "specs",
        "example",
        "examples",
        "sample",
        "samples",
        "mock",
        "mocks",
        "demo",
        "demos",
        "e2e",
        "integration",
        "conformance",
        "golden",
        "testcases",
    }
)


def _in_fixture_path(rel: str) -> bool:
    parts = rel.split("/")[:-1]
    return any(part.lower() in _FIXTURE_DIRS for part in parts)


def _is_source(record: _FileRecord) -> bool:
    """Recognised code, or an unrecognised extension that is not plainly data.

    Universality is the point: a language nobody has taught the tool still gets
    measured for size, nesting and markers. Only documents, data and binaries
    are set aside, and an extensionless file is left alone because that is
    where LICENSE and CHANGELOG live.
    """
    if record.language is not None:
        return True
    if not record.ext or record.ext in NON_CODE_EXTENSIONS:
        return False
    return True


def _language_for(name: str, ext: str) -> str | None:
    named = LANGUAGE_BY_FILENAME.get(name)
    if named is not None:
        return named
    if name.startswith("Dockerfile"):
        return "Dockerfile"
    if name.startswith("Makefile"):
        return "Makefile"
    return LANGUAGE_BY_EXTENSION.get(ext)


def _walk(root: Path, budget: _Budget) -> _WalkResult:
    files: list[_FileRecord] = []
    directories: list[str] = []
    vendored: list[_VendoredDir] = []
    editor_dirs: list[_VendoredDir] = []
    vendored_files = 0
    vendored_bytes = 0
    truncated = False
    queue: deque[tuple[Path, str]] = deque([(root, "")])
    seen = 0

    while queue:
        current, rel = queue.popleft()
        if budget.over(_WALK_FRACTION):
            truncated = True
            break
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen % 1024 == 0 and budget.over(_WALK_FRACTION):
                truncated = True
                queue.clear()
                break
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            try:
                if entry.is_symlink():
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if entry.name in _SILENT_DIRS:
                    continue
                if entry.name in VENDORED_DIRS:
                    count, size = _count_tree(Path(entry.path), budget)
                    vendored.append(
                        _VendoredDir(rel=child_rel, file_count=count, size_bytes=size)
                    )
                    vendored_files += count
                    vendored_bytes += size
                    continue
                directories.append(child_rel)
                if entry.name in _EDITOR_DIRS:
                    # Pruned like a vendored directory. Editor state is
                    # reported as sediment, and descending would also count it
                    # as the author's source.
                    count, size = _count_tree(Path(entry.path), budget)
                    editor_dirs.append(
                        _VendoredDir(rel=child_rel, file_count=count, size_bytes=size)
                    )
                    continue
                queue.append((Path(entry.path), child_rel))
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            files.append(
                _FileRecord(
                    rel=child_rel,
                    name=entry.name,
                    ext=ext,
                    size=size,
                    depth=child_rel.count("/"),
                    language=_language_for(entry.name, ext),
                )
            )

    return _WalkResult(
        files=tuple(sorted(files, key=lambda record: record.rel)),
        directories=tuple(sorted(directories)),
        vendored=tuple(sorted(vendored, key=lambda item: item.rel)),
        vendored_file_count=vendored_files,
        vendored_bytes=vendored_bytes,
        editor_dirs=tuple(sorted(editor_dirs, key=lambda item: item.rel)),
        truncated=truncated,
    )


def _count_tree(root: Path, budget: _Budget) -> tuple[int, int]:
    count = 0
    size = 0
    seen = 0
    queue: deque[Path] = deque([root])
    while queue:
        current = queue.popleft()
        try:
            with os.scandir(current) as iterator:
                for entry in iterator:
                    seen += 1
                    if seen % 2048 == 0 and budget.over(_WALK_FRACTION):
                        return (count, size)
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            queue.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        count += 1
                        size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return (count, size)


def _read_text(path: Path, limit: int = MAX_READ_BYTES) -> str | None:
    """Read the head of a file as text, or report None for binary and unreadable."""
    try:
        with path.open("rb") as handle:
            head = handle.read(min(limit, BINARY_SNIFF_BYTES))
            if b"\x00" in head:
                return None
            rest = handle.read(limit - len(head)) if limit > len(head) else b""
    except OSError:
        return None
    return (head + rest).decode("utf-8", errors="replace")


def _decoded(chunks: Iterable[bytes]) -> Iterator[str]:
    """Decode a byte stream as UTF-8, replacing what is not.

    Incremental, so a character straddling a chunk boundary decodes as the
    character it is rather than as two replacements.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    for chunk in chunks:
        text = decoder.decode(chunk)
        if text:
            yield text
    tail = decoder.decode(b"", True)
    if tail:
        yield tail


def _split_lines(chunks: Iterable[str], state: _ReadState) -> Iterator[str]:
    """Split a text stream into lines exactly as str.splitlines() would.

    The last piece of every chunk is held back, because the chunk boundary
    may sit inside a line, and a carriage return at the end of one chunk may
    turn out to be the first half of a line break in the next.

    Beyond MAX_LINE_CHARS the rest of an unbroken line is dropped rather than
    accumulated, which is what keeps a minified bundle from being held whole
    in memory. The line is still counted once, so the count stays exact, and
    the state records that some text went unread so nothing downstream claims
    to have seen the whole file.
    """
    carry = ""
    skipping = False
    for chunk in chunks:
        pieces = (carry + chunk).splitlines(keepends=True)
        if not pieces:
            continue
        carry = pieces.pop()
        for piece in pieces:
            if skipping:
                skipping = False
                continue
            yield piece.rstrip(_LINE_BREAKS)
        if len(carry) > MAX_LINE_CHARS and carry.rstrip(_LINE_BREAKS) == carry:
            state.truncated_line = True
            if not skipping:
                yield carry[:MAX_LINE_CHARS]
                skipping = True
            carry = ""
    if carry and not skipping:
        yield carry.rstrip(_LINE_BREAKS)


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(BINARY_SNIFF_BYTES)
    except OSError:
        return False
    return b"\x00" in head


def _stream_count(path: Path, needle: str, limit: int = LOCKFILE_SCAN_BYTES) -> int:
    if not needle:
        return 0
    total = 0
    overlap = ""
    read = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            while read < limit:
                chunk = handle.read(65536)
                if not chunk:
                    break
                read += len(chunk)
                window = overlap + chunk
                total += window.count(needle)
                overlap = window[-(len(needle) - 1) :] if len(needle) > 1 else ""
    except OSError:
        return total
    return total


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} byte" if size == 1 else f"{size} bytes"
    kilobytes = size / 1024.0
    if kilobytes < 1024.0:
        return f"{kilobytes:.1f} KB"
    megabytes = kilobytes / 1024.0
    if megabytes < 1024.0:
        return f"{megabytes:.1f} MB"
    return f"{megabytes / 1024.0:.1f} GB"


def _file_word(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def _to_path(root: Path, rel: str) -> Path:
    return root.joinpath(*rel.split("/"))


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["LC_ALL"] = "C"
    return env


def _run_git(root: Path, args: Sequence[str], timeout: float) -> tuple[int, str]:
    if timeout <= 0.0:
        return (-1, "")
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return (-1, "")
    return (completed.returncode, completed.stdout)


def _empty_git(is_repo: bool) -> GitMetrics:
    return GitMetrics(
        is_repo=is_repo,
        has_commits=False,
        shallow=False,
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


_FIX_RE: Final[re.Pattern[str]] = re.compile(r"\bfix(e[sd])?\b", re.IGNORECASE)


def _git(root: Path, budget: _Budget) -> tuple[GitMetrics, bool]:
    dot_git = root / ".git"
    # The repository must be rooted at the path we were handed. git rev-parse
    # walks up to a parent, so asking it first means tasting a subdirectory
    # reports the enclosing project's history, which is somebody else's
    # repository and was never offered for tasting.
    if not _exists(dot_git):
        return (_empty_git(False), False)
    if shutil.which("git") is None:
        return (_empty_git(True), False)

    timeout = min(GIT_CALL_TIMEOUT, max(0.5, budget.remaining()))
    code, output = _run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout)
    if code != 0 or output.strip() != "true":
        return (_empty_git(True), False)

    shallow = _exists(dot_git / "shallow")
    if not shallow:
        code, output = _run_git(root, ["rev-parse", "--is-shallow-repository"], timeout)
        shallow = code == 0 and output.strip() == "true"

    return _git_log(root, budget, is_repo=True, shallow=shallow)


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _git_log(
    root: Path, budget: _Budget, *, is_repo: bool, shallow: bool
) -> tuple[GitMetrics, bool]:
    commit_count = 0
    fix_count = 0
    authors: Counter[str] = Counter()
    days: set[int] = set()
    first_date: str | None = None
    last_date: str | None = None
    head_subject: str | None = None
    truncated = False

    try:
        process = subprocess.Popen(
            [
                "git",
                "log",
                "--no-color",
                "--date=short",
                "--pretty=format:%ad\x1f%an\x1f%s",
            ],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_env(),
        )
    except (OSError, ValueError):
        return (_empty_git(is_repo), False)

    stream = process.stdout
    if stream is None:
        _terminate(process)
        return (_empty_git(is_repo), False)

    # The in-loop check below only runs when a line arrives. A git that stalls
    # would otherwise read past the deadline forever, so the deadline also gets
    # enforced from a timer that closes the pipe by killing the process.
    killed = False

    def kill_on_deadline() -> None:
        nonlocal killed
        killed = True
        try:
            process.kill()
        except OSError:
            pass

    watchdog = threading.Timer(
        max(0.5, budget.remaining_before(_GIT_FRACTION)), kill_on_deadline
    )
    watchdog.daemon = True
    watchdog.start()

    try:
        for index, line in enumerate(stream):
            if index % 256 == 0 and budget.over(_GIT_FRACTION):
                truncated = True
                break
            parts = line.rstrip("\n").split("\x1f", 2)
            if len(parts) != 3:
                continue
            stamp, author, subject = parts
            if len(stamp) != 10 or stamp[4] != "-" or stamp[7] != "-":
                continue
            commit_count += 1
            if head_subject is None:
                head_subject = subject
            if _FIX_RE.search(subject):
                fix_count += 1
            authors[author] += 1
            ordinal = _ordinal_of(stamp)
            if ordinal is not None:
                days.add(ordinal)
            if first_date is None or stamp < first_date:
                first_date = stamp
            if last_date is None or stamp > last_date:
                last_date = stamp
    except (OSError, ValueError):
        pass
    finally:
        watchdog.cancel()
        _terminate(process)

    if killed:
        truncated = True

    if commit_count == 0:
        return (_empty_git(is_repo), truncated)

    gap_days, gap_start, gap_end = _longest_gap(days)
    top_author, top_commits = _top_author(authors)
    last_ordinal = _ordinal_of(last_date) if last_date is not None else None
    since = 0
    if last_ordinal is not None:
        since = max(0, date.today().toordinal() - last_ordinal)

    metrics = GitMetrics(
        is_repo=is_repo,
        has_commits=True,
        shallow=shallow,
        first_commit_date=first_date,
        last_commit_date=last_date,
        first_commit_year=int(first_date[:4]) if first_date else None,
        last_commit_year=int(last_date[:4]) if last_date else None,
        commit_count=commit_count,
        fix_commit_count=fix_count,
        fix_ratio=fix_count / commit_count,
        longest_gap_days=gap_days,
        longest_gap_start=gap_start,
        longest_gap_end=gap_end,
        days_since_last_commit=since,
        author_count=len(authors),
        top_author_name=top_author,
        top_author_commits=top_commits,
        top_author_share=top_commits / commit_count,
        last_commit_subject=head_subject,
    )
    return (metrics, truncated)


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.stdout is not None:
        try:
            process.stdout.close()
        except OSError:
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=GIT_CALL_TIMEOUT)
    except subprocess.SubprocessError:
        pass


def _ordinal_of(stamp: str) -> int | None:
    try:
        return date(int(stamp[0:4]), int(stamp[5:7]), int(stamp[8:10])).toordinal()
    except ValueError:
        return None


def _longest_gap(days: set[int]) -> tuple[int, str | None, str | None]:
    if len(days) < 2:
        return (0, None, None)
    ordered = sorted(days)
    best = 0
    start = ordered[0]
    end = ordered[0]
    for previous, current in zip(ordered, ordered[1:]):
        gap = current - previous
        if gap > best:
            best = gap
            start = previous
            end = current
    if best <= 0:
        return (0, None, None)
    return (best, date.fromordinal(start).isoformat(), date.fromordinal(end).isoformat())


def _top_author(authors: Counter[str]) -> tuple[str | None, int]:
    if not authors:
        return (None, 0)
    best_name = min(authors, key=lambda name: (-authors[name], name))
    return (best_name, authors[best_name])


def _nose(root: Path, records: Sequence[_FileRecord], directories: Sequence[str]) -> NoseMetrics:
    root_files = [record for record in records if record.depth == 0]

    readme = _first_match(root_files, lambda name: name.lower().startswith("readme"))
    readme_lines = 0
    readme_bytes = 0
    if readme is not None:
        readme_bytes = readme.size
        text = _read_text(_to_path(root, readme.rel))
        if text is not None:
            readme_lines = len(text.splitlines())

    license_record = _first_match(
        root_files,
        lambda name: name.lower().startswith(("license", "licence", "copying", "unlicense")),
    )
    license_name: str | None = None
    if license_record is not None:
        license_name = _license_name(_to_path(root, license_record.rel))

    gitignore = _first_match(root_files, lambda name: name == ".gitignore")
    gitignore_rules = 0
    if gitignore is not None:
        text = _read_text(_to_path(root, gitignore.rel))
        if text is not None:
            gitignore_rules = sum(
                1
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )

    rel_paths = frozenset(record.rel for record in records)
    has_contributing = any(
        record.name.lower().startswith("contributing")
        for record in records
        if record.depth <= 1
    )
    has_ci = any(name in rel_paths for name in _CI_FILES) or any(
        record.rel.startswith(_CI_PREFIXES) for record in records
    )
    # A directory named tests is not a test suite until something is inside
    # it. An empty one is the cheapest thing an author can make, and it used
    # to be enough: it passed a gate that is supposed to cost real work, and
    # emptying a test directory left the answer unchanged.
    test_prefixes = tuple(
        f"{directory}/"
        for directory in directories
        if directory.rsplit("/", 1)[-1].lower() in _TEST_DIR_NAMES
    )
    has_test_dir = bool(test_prefixes) and any(
        record.rel.startswith(test_prefixes) for record in records
    )
    has_tests = has_test_dir or any(_TEST_FILE_RE.match(record.name) for record in records)

    return NoseMetrics(
        readme_path=readme.rel if readme is not None else None,
        readme_lines=readme_lines,
        readme_bytes=readme_bytes,
        license_path=license_record.rel if license_record is not None else None,
        license_name=license_name,
        gitignore_path=gitignore.rel if gitignore is not None else None,
        gitignore_rules=gitignore_rules,
        has_contributing=has_contributing,
        has_ci=has_ci,
        has_tests=has_tests,
    )


def _first_match(
    records: Sequence[_FileRecord], predicate: Callable[[str], bool]
) -> _FileRecord | None:
    for record in sorted(records, key=lambda item: item.rel):
        if predicate(record.name):
            return record
    return None


def _license_name(path: Path) -> str:
    text = _read_text(path)
    if text is None:
        return "Unknown"
    upper = " ".join(text.upper().split())
    for name, needles in _LICENSE_SIGNATURES:
        if all(needle in upper for needle in needles):
            return name
    if "BSD" in upper or "REDISTRIBUTION AND USE IN SOURCE" in upper:
        return "BSD-3-Clause" if "NEITHER THE NAME" in upper else "BSD-2-Clause"
    return "Unknown"


def _structure(root: Path, records: Sequence[_FileRecord]) -> StructureMetrics:
    candidates = [
        record
        for record in records
        if record.name in _MANIFEST_ECOSYSTEMS and record.depth <= MANIFEST_MAX_DEPTH
    ]
    candidates.sort(key=lambda record: record.rel)
    manifests: list[DependencyManifest] = []
    for record in candidates[:MANIFEST_LIMIT]:
        manifest = _read_manifest(root, record)
        if manifest is not None:
            manifests.append(manifest)

    total = sum(manifest.declared_count for manifest in manifests)
    ecosystems = tuple(sorted({manifest.ecosystem for manifest in manifests}))
    return StructureMetrics(
        manifests=tuple(sorted(manifests, key=lambda item: item.manifest_path)),
        total_declared=total,
        undeclared=not manifests,
        ecosystems=ecosystems,
    )


def _read_manifest(root: Path, record: _FileRecord) -> DependencyManifest | None:
    ecosystem = _MANIFEST_ECOSYSTEMS.get(record.name)
    if ecosystem is None:
        return None
    path = _to_path(root, record.rel)
    text = _read_text(path, MAX_READ_BYTES)
    if text is None:
        text = ""
    if record.name == "package.json":
        declared, dev = _count_package_json(text)
    elif record.name == "requirements.txt":
        declared, dev = (_count_requirements(text), 0)
    elif record.name == "pyproject.toml":
        declared, dev = _count_pyproject(text)
    elif record.name == "go.mod":
        declared, dev = (_count_go_mod(text), 0)
    else:
        declared, dev = _count_cargo(text)

    directory = record.rel.rsplit("/", 1)[0] if "/" in record.rel else ""
    lock_rel, lock_path = _find_lockfile(root, directory, record.name)
    locked = 0
    if lock_rel is not None and lock_path is not None:
        locked = _count_lockfile(lock_path, lock_path.name)

    drift, reason = _drift(path, lock_path, declared, locked)
    return DependencyManifest(
        ecosystem=ecosystem,
        manifest_path=record.rel,
        declared_count=declared,
        dev_count=dev,
        lockfile_path=lock_rel,
        locked_count=locked,
        drift=drift,
        drift_reason=reason,
    )


def _find_lockfile(root: Path, directory: str, manifest_name: str) -> tuple[str | None, Path | None]:
    for candidate in _LOCKFILES_BY_MANIFEST.get(manifest_name, ()):
        rel = f"{directory}/{candidate}" if directory else candidate
        path = _to_path(root, rel)
        try:
            if path.is_file():
                return (rel, path)
        except OSError:
            continue
    return (None, None)


def _count_lockfile(path: Path, name: str) -> int:
    marker = _LOCK_MARKERS.get(name)
    if marker is None:
        return 0
    if name in {"package-lock.json", "npm-shrinkwrap.json"}:
        try:
            small = path.stat().st_size <= MAX_READ_BYTES
        except OSError:
            small = False
        if small:
            text = _read_text(path)
            if text is not None:
                data = _json_object(text)
                packages = data.get("packages")
                if isinstance(packages, dict) and packages:
                    return max(0, len(packages) - 1)
                dependencies = data.get("dependencies")
                if isinstance(dependencies, dict):
                    return len(dependencies)
    if name == "requirements.lock":
        text = _read_text(path)
        return _count_requirements(text) if text is not None else 0
    return _stream_count(path, marker)


def _drift(
    manifest_path: Path, lock_path: Path | None, declared: int, locked: int
) -> tuple[bool, str | None]:
    if lock_path is None:
        # Nothing declared is nothing to lock, and that is not drift.
        return (declared > 0, "no lockfile" if declared > 0 else None)
    try:
        manifest_mtime = manifest_path.stat().st_mtime
        lock_mtime = lock_path.stat().st_mtime
    except OSError:
        return (False, None)
    if lock_mtime < manifest_mtime:
        return (True, "lockfile is older than manifest")
    if declared > 0 and locked < declared:
        return (True, "counts disagree")
    return (False, None)


def _json_object(text: str) -> Mapping[str, object]:
    try:
        data: object = json.loads(text)
    except (ValueError, RecursionError):
        return {}
    if isinstance(data, dict):
        return {str(key): value for key, value in data.items()}
    return {}


def _toml_object(text: str) -> Mapping[str, object]:
    try:
        data: object = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError, RecursionError):
        return {}
    if isinstance(data, dict):
        return {str(key): value for key, value in data.items()}
    return {}


def _mapping_at(data: Mapping[str, object], *keys: str) -> Mapping[str, object]:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    if isinstance(current, dict):
        return {str(inner): value for inner, value in current.items()}
    return {}


def _sequence_at(data: Mapping[str, object], *keys: str) -> tuple[str, ...]:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return ()
        current = current.get(key)
    if isinstance(current, list):
        return tuple(str(item) for item in current)
    return ()


def _count_package_json(text: str) -> tuple[int, int]:
    data = _json_object(text)
    declared = len(_mapping_at(data, "dependencies"))
    declared += len(_mapping_at(data, "peerDependencies"))
    declared += len(_mapping_at(data, "optionalDependencies"))
    return (declared, len(_mapping_at(data, "devDependencies")))


def _count_requirements(text: str) -> int:
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        count += 1
    return count


def _count_pyproject(text: str) -> tuple[int, int]:
    data = _toml_object(text)
    declared = len(_sequence_at(data, "project", "dependencies"))
    dev = 0
    for group in _mapping_at(data, "project", "optional-dependencies").values():
        if isinstance(group, list):
            dev += len(group)
    for group in _mapping_at(data, "dependency-groups").values():
        if isinstance(group, list):
            dev += len(group)
    poetry = _mapping_at(data, "tool", "poetry", "dependencies")
    declared += len([key for key in poetry if key != "python"])
    dev += len(_mapping_at(data, "tool", "poetry", "dev-dependencies"))
    for group_name in _mapping_at(data, "tool", "poetry", "group"):
        dev += len(_mapping_at(data, "tool", "poetry", "group", group_name, "dependencies"))
    return (declared, dev)


_GO_REQUIRE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*([\w.\-/~]+\.[\w.\-/~]+)\s+v\S+")


def _count_go_mod(text: str) -> int:
    count = 0
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if in_block:
            if line.startswith(")"):
                in_block = False
                continue
            if "// indirect" in line:
                continue
            if _GO_REQUIRE_RE.match(line):
                count += 1
            continue
        if line.startswith("require ("):
            in_block = True
            continue
        if line.startswith("require ") and "// indirect" not in line:
            if _GO_REQUIRE_RE.match(line[len("require ") :]):
                count += 1
    return count


def _count_cargo(text: str) -> tuple[int, int]:
    data = _toml_object(text)
    declared = len(_mapping_at(data, "dependencies"))
    dev = len(_mapping_at(data, "dev-dependencies")) + len(_mapping_at(data, "build-dependencies"))
    for target in _mapping_at(data, "target"):
        declared += len(_mapping_at(data, "target", target, "dependencies"))
        dev += len(_mapping_at(data, "target", target, "dev-dependencies"))
    return (declared, dev)


def _terroir(
    root: Path,
    source_records: Sequence[_FileRecord],
    lines_by_language: Mapping[str, int],
    rel_paths: frozenset[str],
    by_rel: Mapping[str, _FileRecord],
) -> TerroirMetrics:
    counts: Counter[str] = Counter()
    for record in source_records:
        if record.language is not None:
            counts[record.language] += 1
    total = sum(counts.values())
    languages = tuple(
        LanguageShare(
            name=name,
            file_count=count,
            line_count=lines_by_language.get(name, 0),
            share=count / total if total else 0.0,
        )
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    primary = languages[0].name if languages else None
    frameworks = _frameworks(root, rel_paths, by_rel)
    return TerroirMetrics(languages=languages, primary_language=primary, frameworks=frameworks)


def _frameworks(
    root: Path, rel_paths: frozenset[str], by_rel: Mapping[str, _FileRecord]
) -> tuple[str, ...]:
    found: set[str] = set()

    for marker, label in _MARKER_FILE_FRAMEWORKS.items():
        if marker in rel_paths:
            found.add(label)
    if any(rel.endswith(".tf") for rel in rel_paths):
        found.add("Terraform")

    package_json = by_rel.get("package.json")
    if package_json is not None:
        text = _read_text(_to_path(root, package_json.rel))
        if text is not None:
            data = _json_object(text)
            names: set[str] = set()
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                names.update(_mapping_at(data, section))
            found.update(
                _JS_FRAMEWORKS[name] for name in sorted(names) if name in _JS_FRAMEWORKS
            )

    for rel in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile"):
        record = by_rel.get(rel)
        if record is None:
            continue
        text = _read_text(_to_path(root, record.rel))
        if text is None:
            continue
        names = set(_PY_NAME_RE.findall(text.lower()))
        found.update(
            _PY_FRAMEWORKS[name] for name in sorted(names) if name in _PY_FRAMEWORKS
        )

    go_mod = by_rel.get("go.mod")
    if go_mod is not None:
        text = _read_text(_to_path(root, go_mod.rel))
        if text is not None:
            for name, label in _GO_FRAMEWORKS.items():
                if name in text:
                    found.add(label)

    cargo = by_rel.get("Cargo.toml")
    if cargo is not None:
        text = _read_text(_to_path(root, cargo.rel))
        if text is not None:
            data = _toml_object(text)
            names = set(_mapping_at(data, "dependencies"))
            names.update(_mapping_at(data, "dev-dependencies"))
            found.update(
                _RUST_FRAMEWORKS[name] for name in sorted(names) if name in _RUST_FRAMEWORKS
            )

    for filename, signatures in _TEXT_FRAMEWORK_SIGNATURES.items():
        record = by_rel.get(filename)
        if record is None:
            continue
        text = _read_text(_to_path(root, record.rel))
        if text is None:
            continue
        lowered = text.lower()
        for needle, label in signatures:
            if needle.lower() in lowered:
                found.add(label)

    return tuple(sorted(found))


def _sample(
    records: Sequence[_FileRecord], limit: int
) -> tuple[tuple[_FileRecord, ...], bool]:
    ordered = sorted(records, key=lambda record: record.rel)
    if len(ordered) <= limit or limit <= 0:
        return (tuple(ordered), False)

    groups: dict[str, list[_FileRecord]] = {}
    for record in ordered:
        groups.setdefault(record.ext, []).append(record)
    keys = sorted(groups)
    total = len(ordered)

    if len(keys) >= limit:
        chosen = sorted(keys, key=lambda key: (-len(groups[key]), key))[:limit]
        quotas = {key: 1 for key in chosen}
    else:
        quotas = {key: max(1, (limit * len(groups[key])) // total) for key in keys}
        overflow = sum(quotas.values()) - limit
        while overflow > 0:
            reducible = sorted(
                (key for key in keys if quotas[key] > 1),
                key=lambda key: (-quotas[key], key),
            )
            if not reducible:
                break
            for key in reducible:
                if overflow <= 0:
                    break
                quotas[key] -= 1
                overflow -= 1
        leftover = limit - sum(quotas.values())
        for key in sorted(keys, key=lambda key: (-len(groups[key]), key)):
            if leftover <= 0:
                break
            room = len(groups[key]) - quotas[key]
            if room > 0:
                take = min(room, leftover)
                quotas[key] += take
                leftover -= take

    picked: list[_FileRecord] = []
    for key in keys:
        quota = quotas.get(key, 0)
        if quota <= 0:
            continue
        group = groups[key]
        if quota >= len(group):
            picked.extend(group)
            continue
        step = len(group) / quota
        picked.extend(group[int(index * step)] for index in range(quota))

    return (tuple(sorted(picked, key=lambda record: record.rel)), True)


def _scan(
    root: Path,
    source_records: Sequence[_FileRecord],
    budget: _Budget,
    total_files: int,
    inventory: str,
) -> _ScanResult:
    """Read the sampled source files once and derive palate and abandonment together.

    Size, nesting, function length and markers all come from this one population,
    so the numbers can be compared with each other. An unrecognised extension is
    part of that population: a marker in a language nobody has taught the tool
    still counts.
    """
    selected, sampled = _sample(source_records, SOURCE_SAMPLE_LIMIT)

    total_lines = 0
    scanned = 0
    largest_path: str | None = None
    largest_lines = 0
    deepest_path: str | None = None
    deepest = 0
    function_lines = 0
    function_name: str | None = None
    function_path: str | None = None
    todo = fixme = hack = xxx = 0
    debug_prints = 0
    commented_code = 0
    worst_path: str | None = None
    worst_count = 0
    tallies: dict[str, _LanguageTally] = {}
    truncated_files = 0
    detector_files = 0
    structural_complete = True
    truncated = False

    for index, record in enumerate(selected):
        if index % 32 == 0 and budget.expired():
            truncated = True
            break
        analysis = _analyse_file(_to_path(root, record.rel), record.language, budget)
        if analysis is None:
            continue
        scanned += 1
        if not analysis.complete:
            truncated_files += 1
        if not analysis.structural_complete:
            structural_complete = False
        if analysis.function_detector_ran:
            detector_files += 1
        total_lines += analysis.lines
        if analysis.lines > largest_lines:
            largest_lines = analysis.lines
            largest_path = record.rel
        if analysis.max_depth > deepest:
            deepest = analysis.max_depth
            deepest_path = record.rel
        if analysis.function_lines > function_lines:
            function_lines = analysis.function_lines
            function_name = analysis.function_name
            function_path = record.rel
        todo += analysis.todo
        fixme += analysis.fixme
        hack += analysis.hack
        xxx += analysis.xxx
        debug_prints += analysis.debug_prints
        commented_code += analysis.commented_code
        markers = analysis.todo + analysis.fixme + analysis.hack + analysis.xxx
        if markers > worst_count:
            worst_count = markers
            worst_path = record.rel
        _tally(tallies, record, analysis)

    source_count = len(source_records)
    attributed = sum(1 for record in source_records if record.language is not None)
    marker_total = todo + fixme + hack + xxx
    per_kloc = marker_total / (total_lines / 1000.0) if total_lines else 0.0
    # Files nobody opened are as absent as files that were cut short, and the
    # barrel sample skips them by design rather than by accident.
    lines_complete = truncated_files == 0 and not sampled and not truncated

    palate = PalateMetrics(
        source_file_count=source_count,
        total_file_count=total_files,
        total_lines=total_lines,
        # Averaged over the files actually read. Dividing by the full source
        # count would understate the average by the sampling ratio the moment
        # the barrel sample kicks in.
        average_lines=total_lines / scanned if scanned else 0.0,
        largest_file_path=largest_path,
        largest_file_lines=largest_lines,
        max_indent_depth=deepest,
        max_indent_path=deepest_path,
        longest_function_lines=function_lines,
        longest_function_name=function_name,
        longest_function_path=function_path,
        sampled=sampled,
        scanned_file_count=scanned,
        inventory=inventory,
        by_language=_language_palates(tallies),
    )
    abandonment = AbandonmentMetrics(
        todo=todo,
        fixme=fixme,
        hack=hack,
        xxx=xxx,
        total=marker_total,
        per_kloc=per_kloc,
        worst_file_path=worst_path,
        worst_file_count=worst_count,
        debug_print_count=debug_prints,
        commented_out_code_lines=commented_code,
    )
    return _ScanResult(
        palate=palate,
        abandonment=abandonment,
        lines_by_language={
            name: tally.line_count for name, tally in tallies.items() if name
        },
        truncated=truncated,
        lines_complete=lines_complete,
        truncated_files=truncated_files,
        structural_scan_complete=structural_complete and lines_complete,
        function_detector_files=detector_files,
        attributed_files=attributed,
    )


def _tally(
    tallies: dict[str, _LanguageTally], record: _FileRecord, analysis: _FileAnalysis
) -> None:
    """Fold one file into its language's running totals.

    Unattributed files go into a bucket of their own rather than being
    dropped, because a repository can be nothing but unattributed files and
    that fact is the finding.
    """
    name = record.language or ""
    tally = tallies.get(name)
    if tally is None:
        tally = _LanguageTally(name=name)
        tallies[name] = tally
    tally.file_count += 1
    tally.line_count += analysis.lines
    if analysis.function_detector_ran:
        tally.function_detector_ran = True
    if analysis.lines > tally.largest_file_lines:
        tally.largest_file_lines = analysis.lines
        tally.largest_file_path = record.rel
    if analysis.max_depth > tally.max_indent_depth:
        tally.max_indent_depth = analysis.max_depth
        tally.max_indent_path = record.rel
    if analysis.function_lines > tally.longest_function_lines:
        tally.longest_function_lines = analysis.function_lines
        tally.longest_function_name = analysis.function_name
        tally.longest_function_path = record.rel


def _language_palates(
    tallies: Mapping[str, _LanguageTally]
) -> tuple[LanguagePalate, ...]:
    return tuple(
        LanguagePalate(
            name=tally.name,
            file_count=tally.file_count,
            line_count=tally.line_count,
            max_indent_depth=tally.max_indent_depth,
            max_indent_path=tally.max_indent_path,
            largest_file_lines=tally.largest_file_lines,
            largest_file_path=tally.largest_file_path,
            longest_function_lines=tally.longest_function_lines,
            longest_function_name=tally.longest_function_name,
            longest_function_path=tally.longest_function_path,
            function_detector_ran=tally.function_detector_ran,
        )
        for tally in sorted(
            tallies.values(), key=lambda item: (-item.file_count, item.name)
        )
    )


def _comment_tokens_for(language: str | None) -> tuple[str, ...]:
    if language is None:
        return _ALL_COMMENT_TOKENS
    return _COMMENT_TOKENS_BY_LANGUAGE.get(language, _ALL_COMMENT_TOKENS)


def _opener_is_real(line: str, index: int, token: str) -> bool:
    if token not in _AMBIGUOUS_TOKENS:
        return True
    if not line[:index].strip():
        return True
    after = line[index + len(token) : index + len(token) + 1]
    return after == "" or after.isspace()


def _find_opener(line: str, pos: int, tokens: Sequence[str]) -> tuple[int, str] | None:
    best_index = -1
    best_token = ""
    for token in tokens:
        index = line.find(token, pos)
        while index >= 0 and not _opener_is_real(line, index, token):
            index = line.find(token, index + 1)
        if index < 0:
            continue
        better = best_index < 0 or index < best_index
        longer = index == best_index and len(token) > len(best_token)
        if better or longer:
            best_index = index
            best_token = token
    if best_index < 0:
        return None
    return (best_index, best_token)


def _split_line(
    line: str, terminator: str | None, tokens: Sequence[str]
) -> tuple[str, str, str | None]:
    """Split one line into its code half and its comment half."""
    code: list[str] = []
    comment: list[str] = []
    pos = 0
    length = len(line)
    while pos < length:
        if terminator is not None:
            index = line.find(terminator, pos)
            if index < 0:
                comment.append(line[pos:])
                break
            comment.append(line[pos:index])
            pos = index + len(terminator)
            terminator = None
            continue
        opener = _find_opener(line, pos, tokens)
        if opener is None:
            code.append(line[pos:])
            break
        start, token = opener
        code.append(line[pos:start])
        if token == "/*":
            terminator = "*/"
            pos = start + len(token)
            continue
        if token == _MARKUP_OPEN:
            terminator = _MARKUP_CLOSE
            pos = start + len(token)
            continue
        comment.append(line[start + len(token) :])
        break
    return ("".join(code), "".join(comment), terminator)


def _looks_like_code(comment: str) -> bool:
    stripped = comment.strip()
    if len(stripped) < 3 or len(stripped.split()) > 12:
        return False
    if stripped[0] in "*-=|+>":
        return False
    return _CODE_SHAPE_RE.search(stripped) is not None


def _analyse_file(
    path: Path, language: str | None, budget: _Budget
) -> _FileAnalysis | None:
    """Stream one file, or report None for binary and unreadable.

    The file is read to its end, in chunks, so the line and marker counts
    describe the file rather than its first 64 KiB. Only the structural
    analysis is capped, and _FileAnalysis says when that cap was reached.
    """
    state = _ReadState()
    try:
        with path.open("rb") as handle:
            head = handle.read(BINARY_SNIFF_BYTES)
            if b"\x00" in head:
                return None

            def chunks() -> Iterator[bytes]:
                yield head
                while True:
                    block = handle.read(STREAM_CHUNK_BYTES)
                    if not block:
                        break
                    yield block
                    # Only consulted once a whole chunk has been read, so a
                    # file that fits inside the sniff window is never called
                    # truncated by a budget that had already expired.
                    if budget.expired():
                        return
                state.complete = True

            return _analyse_lines(
                _split_lines(_decoded(chunks()), state), language, state
            )
    except OSError:
        return None


def _analyse_lines(
    lines: Iterable[str], language: str | None, state: _ReadState
) -> _FileAnalysis:
    """Count one file's lines and markers, and analyse the head of it.

    Markers, debug prints and commented out code are counted on every line.
    Indentation depth and function length need every line held at once and
    cost accordingly, so they see the first STRUCTURAL_SCAN_CHARS characters
    and the result records whether that was all of them.
    """
    tokens = _comment_tokens_for(language)
    family = _FUNCTION_FAMILY.get(language or "", "")
    code_lines: list[str] = []
    scans: list[tuple[int, int]] = []
    retained = 0
    structural_complete = True
    terminator: str | None = None
    count = 0
    todo = fixme = hack = xxx = 0
    debug_prints = 0
    commented_code = 0

    for line in lines:
        count += 1
        code, comment, terminator = _split_line(line, terminator, tokens)
        if comment:
            for marker in _MARKER_RE.findall(comment):
                if marker == "TODO":
                    todo += 1
                elif marker == "FIXME":
                    fixme += 1
                elif marker == "HACK":
                    hack += 1
                else:
                    xxx += 1
            if _looks_like_code(comment):
                commented_code += 1
        if code:
            debug_prints += len(_DEBUG_PRINT_RE.findall(code))
        if retained < STRUCTURAL_SCAN_CHARS:
            code_lines.append(code)
            scans.append(_delta_scan(code))
            # The terminator the split removed is worth one character. The
            # cap is a budget, not a measurement, so an approximation of the
            # original file offset is what it needs.
            retained += len(line) + 1
        else:
            structural_complete = False

    depth = _indent_depth(code_lines, scans)
    function_lines, function_name = _longest_function(code_lines, scans, family)

    return _FileAnalysis(
        lines=count,
        max_depth=depth,
        function_lines=function_lines,
        function_name=function_name,
        todo=todo,
        fixme=fixme,
        hack=hack,
        xxx=xxx,
        debug_prints=debug_prints,
        commented_code=commented_code,
        complete=state.complete,
        structural_complete=(
            structural_complete and state.complete and not state.truncated_line
        ),
        function_detector_ran=bool(family),
    )


def _indent_depth(code_lines: Sequence[str], scans: Sequence[tuple[int, int]]) -> int:
    indents: list[int] = []
    pending = 0
    for code, scan in zip(code_lines, scans):
        opened = pending
        pending = max(0, pending + scan[1])
        expanded = code.expandtabs(4)
        stripped = expanded.strip()
        # A line continued from an unclosed bracket is aligned, not nested.
        if not stripped or stripped[0] in ")]}," or opened > 0:
            continue
        indents.append(len(expanded) - len(expanded.lstrip(" ")))
    if not indents:
        return 0
    deltas: Counter[int] = Counter()
    for previous, current in zip(indents, indents[1:]):
        if current > previous:
            deltas[current - previous] += 1
    unit = 4
    if deltas:
        unit = min(deltas, key=lambda size: (-deltas[size], size))
    unit = max(2, unit)
    return max(indent // unit for indent in indents)


def _longest_function(
    code_lines: Sequence[str], scans: Sequence[tuple[int, int]], family: str
) -> tuple[int, str | None]:
    if family == "python":
        return _longest_indent_function(code_lines, _PY_DEF_RE, "def ")
    if family == "ruby":
        return _longest_ruby_function(code_lines)
    if family == "brace":
        return _longest_brace_function(code_lines, scans)
    return (0, None)


def _longest_indent_function(
    code_lines: Sequence[str], pattern: re.Pattern[str], hint: str
) -> tuple[int, str | None]:
    best = 0
    best_name: str | None = None
    count = len(code_lines)
    for index, code in enumerate(code_lines):
        if hint not in code:
            continue
        expanded = code.expandtabs(4)
        match = pattern.match(expanded)
        if match is None:
            continue
        indent = len(match.group(1))
        end = count
        for cursor in range(index + 1, count):
            candidate = code_lines[cursor].expandtabs(4)
            if not candidate.strip():
                continue
            if len(candidate) - len(candidate.lstrip(" ")) <= indent:
                end = cursor
                break
        length = end - index
        if length > best:
            best = length
            best_name = match.group(2)
    return (best, best_name)


def _longest_ruby_function(code_lines: Sequence[str]) -> tuple[int, str | None]:
    best = 0
    best_name: str | None = None
    count = len(code_lines)
    for index, code in enumerate(code_lines):
        if "def " not in code:
            continue
        expanded = code.expandtabs(4)
        match = _RUBY_DEF_RE.match(expanded)
        if match is None:
            continue
        indent = len(match.group(1))
        end = count
        for cursor in range(index + 1, count):
            candidate = code_lines[cursor].expandtabs(4)
            stripped = candidate.strip()
            if stripped != "end":
                continue
            if len(candidate) - len(candidate.lstrip(" ")) == indent:
                end = cursor + 1
                break
        length = end - index
        if length > best:
            best = length
            best_name = match.group(2)
    return (best, best_name)


def _signature_name(code: str) -> str | None:
    stripped = code.strip()
    if not stripped or "(" not in stripped or stripped.endswith(";"):
        return None
    if stripped.startswith(("*", "@", ".", "}", ")")):
        return None
    leading = _LEADING_WORD_RE.match(stripped)
    if leading is not None and leading.group(0) in _CONTROL_WORDS:
        return None
    if stripped.startswith("func"):
        go_match = _GO_FUNC_RE.match(stripped)
        if go_match is not None:
            return go_match.group(1) or "anonymous"
    rust_match = _RUST_FN_RE.search(stripped)
    if rust_match is not None:
        return rust_match.group(1)
    js_match = _JS_FUNCTION_RE.search(stripped)
    if js_match is not None:
        return js_match.group(1) or "anonymous"
    arrow_match = _ARROW_FUNC_RE.match(stripped)
    if arrow_match is not None:
        return arrow_match.group(1)
    if not stripped.endswith(("{", ")")) and "{" not in stripped:
        return None
    for match in _NAME_CALL_RE.finditer(stripped):
        name = match.group(1)
        if name in _CONTROL_WORDS:
            continue
        if match.start() > 0 and stripped[match.start() - 1] == ".":
            continue
        return name
    return None


def _delta_scan(code: str) -> tuple[int, int]:
    """Count unbalanced braces and unbalanced round or square brackets."""
    braces = 0
    brackets = 0
    quote: str | None = None
    index = 0
    length = len(code)
    while index < length:
        char = code[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        elif char in "([":
            brackets += 1
        elif char in ")]":
            brackets -= 1
        index += 1
    return (braces, brackets)


def _longest_brace_function(
    code_lines: Sequence[str], scans: Sequence[tuple[int, int]]
) -> tuple[int, str | None]:
    count = len(code_lines)
    deltas = [scan[0] for scan in scans]
    best = 0
    best_name: str | None = None
    for index, code in enumerate(code_lines):
        if "(" not in code:
            continue
        name = _signature_name(code)
        if name is None:
            continue
        open_index = index
        brace_at = code.find("{")
        if brace_at < 0:
            open_index = -1
            for cursor in range(index + 1, min(index + 3, count)):
                candidate = code_lines[cursor].strip()
                if not candidate:
                    continue
                if candidate.startswith("{"):
                    open_index = cursor
                    brace_at = code_lines[cursor].find("{")
                break
            if open_index < 0:
                continue
        running = _delta_scan(code_lines[open_index][brace_at:])[0]
        if running <= 0:
            continue
        end = count - 1
        for cursor in range(open_index + 1, count):
            running += deltas[cursor]
            if running <= 0:
                end = cursor
                break
        length = end - index + 1
        if length > best:
            best = length
            best_name = name
    return (best, best_name)


def _is_secret_name(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith(_SECRET_SAFE_SUFFIXES):
        return False
    if name in _SECRET_NAMES or lowered in _SECRET_NAMES:
        return True
    if lowered.startswith(".env"):
        return True
    # prod.env and secrets.env are as committed as .env is, and the safe
    # suffixes above still let .env.example through untouched.
    if lowered.endswith(".env"):
        return True
    return lowered.endswith(_SECRET_SUFFIXES)


def _tracked_index(root: Path, budget: _Budget) -> frozenset[str] | None:
    """Every path git is tracking, or None when git cannot answer.

    Sediment is about what was committed, not about what happens to be sitting
    in the working directory. A local virtualenv is not a sin. A committed one
    is.
    """
    if shutil.which("git") is None or not (root / ".git").exists():
        return None
    timeout = min(GIT_CALL_TIMEOUT, max(0.5, budget.remaining()))
    # Without core.quotePath=false git escapes any path holding a non-ASCII
    # byte, and those paths then never match the ones the walk recorded.
    code, output = _run_git(root, ["-c", "core.quotePath=false", "ls-files"], timeout)
    if code != 0:
        return None
    return frozenset(line for line in output.splitlines() if line)


def _project_index(root: Path, budget: _Budget) -> frozenset[str] | None:
    """Every path git considers part of the project, or None when git cannot say.

    Deliberately not the same question as _tracked_index above. Sediment asks
    what was committed, so an uncommitted local virtualenv is not a sin. The
    file inventory asks what the author wrote, and generated output that git
    has been told to ignore is not the author's code however much of it there
    is on disk.

    --cached and --others together also cover a repository mid-change, where a
    new file is real work that has simply not been committed yet.
    """
    if shutil.which("git") is None or not (root / ".git").exists():
        return None
    timeout = min(GIT_CALL_TIMEOUT, max(0.5, budget.remaining()))
    # -z keeps paths raw, so non-ASCII names need no unquoting and a newline in
    # a filename cannot split one path into two.
    code, output = _run_git(
        root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], timeout
    )
    if code != 0:
        return None
    return frozenset(path for path in output.split("\0") if path)


def _tracked_under(index: frozenset[str], rel: str) -> int:
    prefix = f"{rel}/"
    return sum(1 for path in index if path.startswith(prefix))


def _sediment(
    root: Path, walk: _WalkResult, records: Sequence[_FileRecord], budget: _Budget
) -> SedimentMetrics:
    items: list[SedimentItem] = []
    index = _tracked_index(root, budget)

    def committed(rel: str) -> bool:
        return index is None or rel in index

    vendored_files = 0
    vendored_dirs = 0
    for entry in walk.vendored:
        count = (
            entry.file_count if index is None else _tracked_under(index, entry.rel)
        )
        if count <= 0:
            continue
        vendored_files += count
        vendored_dirs += 1
        items.append(
            SedimentItem(
                kind="vendored",
                path=entry.rel,
                detail=_file_word(count),
                size_bytes=entry.size_bytes,
                file_count=count,
            )
        )

    for entry in walk.editor_dirs:
        count = (
            entry.file_count if index is None else _tracked_under(index, entry.rel)
        )
        if count <= 0:
            continue
        items.append(
            SedimentItem(
                kind="editor",
                path=entry.rel,
                detail=_file_word(count),
                size_bytes=entry.size_bytes,
                file_count=count,
            )
        )

    os_cruft = 0
    for record in records:
        if not committed(record.rel):
            continue
        if record.name in _OS_CRUFT_NAMES or record.name.startswith("._"):
            os_cruft += 1
            items.append(
                SedimentItem(
                    kind="os_cruft",
                    path=record.rel,
                    detail=_human_size(record.size),
                    size_bytes=record.size,
                    file_count=1,
                )
            )
        elif record.name.endswith(_EDITOR_SUFFIXES) or record.name.endswith("~"):
            items.append(
                SedimentItem(
                    kind="editor",
                    path=record.rel,
                    detail=_human_size(record.size),
                    size_bytes=record.size,
                    file_count=1,
                )
            )

    secrets = tuple(
        record.rel
        for record in records
        if _is_secret_name(record.name)
        and committed(record.rel)
        and not _in_fixture_path(record.rel)
    )
    sizes = {record.rel: record.size for record in records}
    for rel in sorted(secrets):
        items.append(
            SedimentItem(
                kind="secret",
                path=rel,
                detail=_human_size(sizes.get(rel, 0)),
                size_bytes=sizes.get(rel, 0),
                file_count=1,
            )
        )

    large_binaries = 0
    largest_path: str | None = None
    largest_bytes = 0
    for record in sorted(records, key=lambda item: (-item.size, item.rel)):
        if record.size < BINARY_CHECK_BYTES:
            break
        if budget.expired():
            break
        if not committed(record.rel):
            continue
        if not _looks_binary(_to_path(root, record.rel)):
            continue
        if record.size > largest_bytes:
            largest_bytes = record.size
            largest_path = record.rel
        if record.size > LARGE_BINARY_BYTES:
            large_binaries += 1
            items.append(
                SedimentItem(
                    kind="large_binary",
                    path=record.rel,
                    detail=_human_size(record.size),
                    size_bytes=record.size,
                    file_count=1,
                )
            )

    return SedimentMetrics(
        items=tuple(sorted(items, key=lambda item: (-item.size_bytes, item.path))),
        vendored_file_count=vendored_files,
        vendored_dir_count=vendored_dirs,
        secret_file_count=len(secrets),
        os_cruft_count=os_cruft,
        large_binary_count=large_binaries,
        largest_binary_path=largest_path,
        largest_binary_bytes=largest_bytes,
    )
