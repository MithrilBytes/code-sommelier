"""The style gate.

These tests fail the build. They enforce the house rules that no reviewer
should have to enforce by hand: no long dashes, no emoji, no exclamation
marks in the voice, no third party imports, and a cellar that can only cite
numbers the judge actually provides.
"""

from __future__ import annotations

import ast
import importlib
import re
import shutil
import subprocess
import sys
import unittest
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from string import Formatter
from types import ModuleType
from unittest import mock

from tests import fixtures

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


def refusals() -> Mapping[str, Sequence[str]]:
    templates: Mapping[str, Sequence[str]] = load_module("sommelier.lines").REFUSALS
    return templates


def refusal_codes() -> tuple[str, ...]:
    codes: Sequence[str] = load_module("sommelier.judge").REFUSALS
    return tuple(codes)


def refusal_facts() -> Mapping[str, Sequence[str]]:
    facts: Mapping[str, Sequence[str]] = load_module("sommelier.judge").REFUSAL_FACTS
    return facts


def verdicts() -> Sequence[str]:
    templates: Sequence[str] = load_module("sommelier.lines").VERDICTS
    return templates


# What a verdict line is allowed to name, and what it must name. The band and
# the denominator are not decoration: a number printed without the count of
# dimensions behind it is the thing the score rewrite exists to remove.
VERDICT_FACTS = frozenset({"score", "band", "scored", "total"})


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


# A measurement that counts part of something, and the word that has to be
# in the sentence that prints it. A subset stated without its qualifier is
# read as the whole: "45 commits came before it" put the count of commits
# titled fix where a reader takes the length of the history, on a card whose
# only defence is that its numbers are checkable.
#
# Both entries are counts of commits printed in the same noun as the count of
# all commits, which is what makes the confusion invisible. Other subsets are
# qualified by the grammar of the line that carries them, since a reader who
# meets "{author} wrote {author_commits} of {commit_count} commits" is told
# whose they are by the sentence itself. Adding to this table is a decision
# about a specific line and is meant to be made one line at a time.
#
# The check reads the prose around the placeholder, not the placeholder,
# because the fact is named `fixes_phrase` and would otherwise vouch for
# itself.
QUALIFIED_MEASUREMENTS: Mapping[str, str] = {
    "git.fix_commit_count": "fix",
    "git.fix_ratio": "fix",
}

# A phrase that asserts something the tool measured separately, and the fact
# it depends on. "Nobody came back" is true of the inside of a gap and false
# of the gap itself, which ended on a commit the tool can name: a form that
# does not name gap_end may not claim the silence was never broken.
GROUNDED_PHRASES: tuple[tuple[str, str, str], ...] = (
    ("finish.the_silence", "came back", "gap_end"),
)

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _sentences(template: str) -> list[str]:
    return re.split(r"(?<=\.)\s+", template)


def measurements_by_key() -> Mapping[str, Mapping[str, str]]:
    """Which measurement each fact name carries, per key, as judge binds it.

    Read off real findings rather than a table, because the binding only
    happens at the call site: `fixes_phrase` is `git.fix_commit_count` because
    _judge_finish says so, and nothing upstream of that records it.
    """
    judge = load_module("sommelier.judge").judge
    from tests.test_judge import spread

    from tests.test_plan import whole_number_averages

    found: dict[str, dict[str, str]] = {}
    for _name, metrics in spread() + whole_number_averages():
        for finding in judge(metrics).findings:
            carried = found.setdefault(finding.key, {})
            for name, fact in finding.facts.items():
                carried.setdefault(name, fact.measurement)
    return found


class TruthfulnessTests(unittest.TestCase):
    """Two ways a line can be false while citing a real number.

    Every template already cites a measured fact, which test_templates_only_
    cite_facts_that_exist proves. Neither of these was caught by that: the
    number was real and the sentence around it was wrong about what it was.
    """

    def test_a_part_is_never_printed_as_though_it_were_the_whole(self) -> None:
        carried = measurements_by_key()
        offences: list[str] = []
        for key, templates in sorted(cellar().items()):
            names = carried.get(key)
            if names is None:
                continue
            for index, template in enumerate(templates):
                for name in sorted(placeholders(template)):
                    word = QUALIFIED_MEASUREMENTS.get(names.get(name, ""))
                    if word is None:
                        continue
                    for sentence in _sentences(template):
                        if f"{{{name}}}" not in sentence:
                            continue
                        prose = _PLACEHOLDER.sub(" ", sentence).lower()
                        if word not in prose:
                            offences.append(
                                f"{key}[{index}] prints {names[name]} in a "
                                f"sentence that never says {word}: {sentence}"
                            )
        self.assertEqual(
            [],
            sorted(offences),
            "a count of part of something is read as the whole unless the "
            "sentence says which part:\n" + "\n".join(sorted(offences)),
        )

    def test_a_claim_names_the_fact_it_rests_on(self) -> None:
        templates = cellar()
        offences: list[str] = []
        for key, phrase, required in GROUNDED_PHRASES:
            for index, template in enumerate(templates.get(key, ())):
                if phrase in template and f"{{{required}}}" not in template:
                    offences.append(
                        f"{key}[{index}] says {phrase!r} without naming "
                        f"{required}: {template}"
                    )
        self.assertEqual(
            [],
            sorted(offences),
            "a line may not assert what the fact beside it contradicts:\n"
            + "\n".join(sorted(offences)),
        )


class RefusalTests(unittest.TestCase):
    """A refusal is a line the reader sees, so it lives under the same rules."""

    def test_every_refusal_code_has_at_least_three_templates(self) -> None:
        templates = refusals()
        thin = sorted(
            f"{code} has {len(templates.get(code, ()))}"
            for code in refusal_codes()
            if len(templates.get(code, ())) < 3
        )
        self.assertEqual(
            [],
            thin,
            "every refusal code needs at least three lines:\n" + "\n".join(thin),
        )

    def test_the_cellar_holds_no_unreachable_refusals(self) -> None:
        emittable = set(refusal_codes())
        stranded = sorted(code for code in refusals() if code not in emittable)
        self.assertEqual(
            [],
            stranded,
            "the cellar holds refusals judge can never emit:\n" + "\n".join(stranded),
        )

    def test_refusal_templates_only_cite_facts_that_exist(self) -> None:
        facts = refusal_facts()
        offences: list[str] = []
        for code, templates in sorted(refusals().items()):
            available = set(facts.get(code, ()))
            for index, template in enumerate(templates):
                for name in sorted(placeholders(template)):
                    if name not in available:
                        offences.append(f"{code}[{index}] cites unknown fact {name}")
        self.assertEqual(
            [],
            offences,
            "refusal lines may only cite facts their code provides:\n"
            + "\n".join(offences),
        )


class VerdictTests(unittest.TestCase):
    """The verdict names the band and the denominator, on every line."""

    def test_every_verdict_states_the_band_and_the_denominator(self) -> None:
        offences: list[str] = []
        for index, template in enumerate(verdicts()):
            used = placeholders(template)
            missing = sorted(VERDICT_FACTS - used)
            extra = sorted(used - VERDICT_FACTS)
            if missing:
                offences.append(f"VERDICTS[{index}] omits {', '.join(missing)}")
            if extra:
                offences.append(f"VERDICTS[{index}] cites unknown {', '.join(extra)}")
        self.assertEqual(
            [],
            offences,
            "a score is never printed without its denominator:\n"
            + "\n".join(offences),
        )


# Data flows one way: collect, judge, plan, voice, render. lines.py is
# material and sits under all of it. cli.py is the front door and stands
# outside the chain, since assembling the pipeline is the whole of its job.
LAYERS: tuple[str, ...] = (
    "lines",
    "collect",
    "judge",
    "plan",
    "voice",
    "render",
)


class LayerTests(unittest.TestCase):
    """The direction of the arrows, enforced rather than described.

    voice.py used to reach past judge into collect for a repository name, an
    empty flag and a list of dropped analyzers. Three fields, and a backwards
    edge that would have set hard the moment anything else needed one.
    """

    def test_no_module_imports_a_later_layer(self) -> None:
        rank = {name: index for index, name in enumerate(LAYERS)}
        offences: list[str] = []
        for name in LAYERS:
            path = PACKAGE_DIR / f"{name}.py"
            self.assertTrue(path.is_file(), f"{relative(path)} is missing")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and not node.level:
                    parts = (node.module or "").split(".")
                elif isinstance(node, ast.Import):
                    parts = node.names[0].name.split(".")
                else:
                    continue
                if len(parts) != 2 or parts[0] != "sommelier":
                    continue
                if rank.get(parts[1], -1) >= rank[name]:
                    offences.append(
                        f"{relative(path)}:{node.lineno} imports {parts[1]}, "
                        f"which is not upstream of {name}"
                    )
        self.assertEqual(
            [],
            sorted(offences),
            "data flows one way, " + ", ".join(LAYERS[1:]) + ":\n"
            + "\n".join(sorted(offences)),
        )

    def test_voice_never_reads_a_measurement(self) -> None:
        """Realisation is handed a plan, and cannot go back for the metrics."""
        source = (PACKAGE_DIR / "voice.py").read_text(encoding="utf-8")
        self.assertNotIn("collect", source)


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


class VersionFloorTests(unittest.TestCase):
    """The package must import on the oldest Python it claims to support.

    Python 3.12 relaxed the dataclass mutable-default rule that 3.11 enforces,
    so a mappingproxy default imports fine on a 3.13 laptop and raises
    ValueError at import time on 3.11. That shipped, and only the CI matrix
    caught it. This test applies 3.11's rule on whatever version runs it.
    """

    def test_no_dataclass_default_that_python_311_rejects(self) -> None:
        import dataclasses
        import importlib
        import pkgutil

        import sommelier

        offences: list[str] = []
        for module in pkgutil.iter_modules(sommelier.__path__):
            loaded = importlib.import_module(f"sommelier.{module.name}")
            for name in dir(loaded):
                obj = getattr(loaded, name)
                if not (dataclasses.is_dataclass(obj) and isinstance(obj, type)):
                    continue
                for item in dataclasses.fields(obj):
                    if item.default is dataclasses.MISSING:
                        continue
                    if item.default.__class__.__hash__ is None:
                        offences.append(
                            f"{module.name}.{obj.__name__}.{item.name} defaults to "
                            f"{type(item.default).__name__}, which 3.11 rejects; "
                            f"use field(default_factory=...)"
                        )
        self.assertEqual([], offences, "\n".join(offences))

    def test_the_declared_floor_matches_the_ci_matrix(self) -> None:
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        if not workflow.is_file():
            self.skipTest("no ci workflow")
        declared = re.search(r'requires-python\s*=\s*"[><=]*(\d+\.\d+)"', pyproject)
        self.assertIsNotNone(declared, "pyproject must declare requires-python")
        assert declared is not None
        self.assertIn(
            f'"{declared.group(1)}"',
            workflow.read_text(encoding="utf-8"),
            "the declared minimum Python is not in the CI matrix, so it is "
            "never actually executed",
        )


# Network-capable and model-serving roots. The package importing any of these
# would be the first step toward a runtime that phones somewhere.
NETWORK_ROOTS = frozenset(
    {
        "socket", "ssl", "urllib", "http", "ftplib", "smtplib", "poplib",
        "imaplib", "telnetlib", "xmlrpc", "asyncio", "webbrowser", "requests",
        "httpx", "aiohttp", "urllib3",
    }
)
MODEL_ROOTS = frozenset(
    {
        "anthropic", "openai", "cohere", "mistralai", "ollama", "replicate",
        "groq", "transformers", "torch", "langchain", "llama_cpp", "tiktoken",
        "huggingface_hub", "google",
    }
)


class NoIntelligenceTests(unittest.TestCase):
    """No AI at runtime, and nothing that could reach one.

    The package already may not import anything outside the standard library,
    but the standard library can open a socket perfectly well. These pin the
    stronger claim: the shipped tool cannot phone anywhere, and the only
    binary it is able to execute is git.
    """

    def _import_roots(self) -> set[str]:
        roots: set[str] = set()
        for path in sorted(PACKAGE_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    roots.add((node.module or "").split(".")[0])
        return roots

    def test_the_package_imports_nothing_that_can_reach_a_network(self) -> None:
        found = sorted(self._import_roots() & NETWORK_ROOTS)
        self.assertEqual([], found, f"network-capable imports: {found}")

    def test_the_package_imports_no_model_library(self) -> None:
        found = sorted(self._import_roots() & MODEL_ROOTS)
        self.assertEqual([], found, f"model libraries: {found}")

    def test_the_only_binary_it_can_execute_is_git(self) -> None:
        spawn = {
            "run", "Popen", "call", "check_output", "check_call", "system",
            "popen", "execv", "execve", "spawnv",
        }
        offences: list[str] = []
        for path in sorted(PACKAGE_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", None
                )
                if name not in spawn:
                    continue
                where = f"{relative(path)}:{node.lineno}"
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        offences.append(f"{where} passes shell=")
                if not node.args:
                    offences.append(f"{where} spawns with no literal argv")
                    continue
                argv = node.args[0]
                if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
                    offences.append(f"{where} argv is not a literal sequence")
                    continue
                first = argv.elts[0]
                if not (isinstance(first, ast.Constant) and first.value == "git"):
                    offences.append(f"{where} argv[0] is not the literal 'git'")
        self.assertEqual([], offences, "\n".join(offences))

    def test_a_full_tasting_completes_with_every_socket_severed(self) -> None:
        """The claim, proved by removing the capability rather than auditing it."""
        import socket

        from sommelier.collect import collect
        from sommelier.judge import judge
        from sommelier.plan import compose
        from sommelier.render import render_card, render_json, render_sober
        from sommelier.voice import pour

        def severed(*args: object, **kwargs: object) -> None:
            raise AssertionError("the tool attempted a network call")

        with (
            mock.patch.object(socket, "socket", severed),
            mock.patch.object(socket, "create_connection", severed),
            mock.patch.object(socket, "getaddrinfo", severed),
        ):
            with fixtures.Fixture("severed") as fixture:
                fixtures.write_tree(
                    fixture.path,
                    {"a.py": "def f():\n    return 1\n", "README.md": "# severed\n"},
                )
                metrics = collect(fixture.path)
                judgement = judge(metrics)
                card = render_card(pour(compose(metrics, judgement)))
                render_json(metrics, judgement)
                render_sober(metrics, judgement)
        self.assertTrue(card.splitlines())


if __name__ == "__main__":
    unittest.main()
