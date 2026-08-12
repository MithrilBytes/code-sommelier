# code-sommelier

Point it at a git repository and it measures repo age, file sizes, complexity
proxies, dependency health, commit history and hygiene problems. It then
presents those findings as a wine tasting card, delivered with rather more
confidence than the situation warrants. Every line on the card is generated
from one of those measurements, and `--sober` prints the measurements instead.

## The card

```
CODE SOMMELIER                                   tasting no. 97

The label    This is todo-app. It is JavaScript. There are 3 source files, and
             every one of them was somebody's idea. There is a tracked .env.
             The sommelier has decided not to read it, which is more restraint
             than the internet will show. 12 of the 20 files here are vendored,
             which is 60 percent of the repository. The sommelier will pretend
             not to have seen that.
Vintage      2019. A vintage of 0.8 years and 3 commits, and the sommelier has
             tasted every one of them. 7 years old. 2019 was a long time ago,
             and this has been here for all of it.
Nose         todo-app has no .gitignore of any kind, not even a copied one.
             Everything it has ever produced by accident is a candidate for the
             permanent record, and across 20 files the record has been keeping.
             36 unresolved markers, 30 of them TODOs. src/legacy.js has 20 and
             has clearly been asking for help for some time. There is no
             README. 3 source files, 955 lines, and not one sentence explaining
             why.
Palate       Body: 3 files, 318.3 lines on average, peaking at 900 lines in
             src/legacy.js. The body is enormous. src/legacy.js is 900 lines
             long and it has never once been opened with confidence.
Structure    package.json declares 5 dependencies and there is no lockfile.
             Every install is a fresh guess.
Finish       3 commits from 1 author. 33 percent say fix. The last one, on
             2019-11-03, says fix login again. Nothing has been committed for
             2,474 days. The last was 2019-11-03. This is not a project, it is
             a preserve. 3 commits. 1 of them titled fix. It is not fixed.
Verdict      87 points, because wine scoring is compressed and the sommelier
             respects tradition. The notes are not compressed.
Pairing      Decant into smaller files and revisit in a year.
```

## Install

```bash
pipx install git+https://github.com/MithrilBytes/code-sommelier
```

## Use

```bash
sommelier taste ./some-repo
```

`taste` is the only verb. Three flags change what comes out:

| Flag | Effect |
|---|---|
| `--json` | full metrics, machine readable, no jokes |
| `--sober` | the plain metrics table, for the humourless |
| `--seed N` | override the seeded selection, for anyone demanding a second opinion |

Line selection is seeded on the repository name, so the same repository always
receives the same tasting. Pass `--seed` to force a different selection.

Exit code 0 covers any completed tasting, including bare directories and
repositories with no commits. Exit code 1 means the path could not be read, and
prints a single line saying so. Failures are never reported as a traceback.

## What it measures

| Course | Metric |
|---|---|
| The label | languages, frameworks, file counts, committed sediment |
| Vintage | first and last commit dates, age, shallow clones |
| Nose | README, LICENSE and `.gitignore` presence and quality, TODO density, debug prints |
| Palate | file count, largest file, average length, maximum nesting depth, longest function |
| Structure | dependency counts per ecosystem, manifest against lockfile |
| Finish | commit count, fix ratio, longest silence, bus factor |

Complexity is measured by proxy: maximum indentation depth, and function length
found by per language regex. Real cyclomatic complexity would require a parser
for each language, which would mean taking on dependencies. Both numbers are
labelled as proxies wherever they appear, and `--sober` prints them raw.

The tool completes on any directory of code, whatever language it is written in
and whatever condition it has been left in. Absent input is treated as a finding
rather than an error, so a repository lacking a README, a dependency manifest, a
recognised language or a git history still produces a full card and exits 0.

## Design rules

1. Measurement and comedy never share a file. `collect.py` returns data,
   `judge.py` applies thresholds, `voice.py` turns findings into lines, and
   every template string lives in `lines.py`. Anything written for effect
   belongs in `lines.py` and is rejected in review anywhere else.
2. Zero runtime dependencies. Python 3.11 or newer, standard library only.
3. Em-dashes and en-dashes are banned throughout the repository, covering code,
   comments, documentation and generated output. `tests/test_style.py` fails
   the build on either character.
4. Deterministic output, seeded on the repository name.
5. Every threshold lives in the `BANDS` table in `judge.py` and nowhere else.

## Develop

```bash
python -m unittest discover -s tests -t .
```

The suite uses `unittest` from the standard library, so the zero dependency
rule applies to the tests as well. Type checking is the second gate:

```bash
mypy --strict sommelier tests
```

## Contributing

New tasting lines are the most useful contribution. Each one must:

- cite a metric, using only the facts its finding key provides in
  `judge.KEY_FACTS`. A line that cannot print its number beside the sentence
  gets cut.
- read correctly when spoken once. Anything needing a second pass to parse
  stays out of the cellar.
- survive `tests/test_style.py`, which rejects em-dashes, en-dashes, emoji,
  exclamation marks, and any template citing a number that was never measured.

The register is documented at the top of `lines.py`. The short version is that
the sommelier states everything as fact, stays inside the repository he is
tasting, and rates the best code he has ever seen as "Adequate."

Every finding key needs at least three lines so that a course does not repeat
itself between runs. Where the material is thin, drop the key instead of
lowering the bar.

### Commit and pull request titles

Use a subject line on its own, with no body, footer or trailer. Write it in the
imperative, in lower case, at 50 characters or fewer, covering one logical
change. Allowed prefixes: `add`, `fix`, `rm`, `docs`, `test`, `perf`.

```
add commit gap detection
fix vintage on shallow clones
rm unused nesting scanner
test em-dash ban
```

## Licence

MIT.
