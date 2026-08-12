# code-sommelier

Point it at a git repository and it performs genuine static analysis: repo age,
file sizes, complexity proxies, dependency health, commit history, hygiene sins.
It then reads the findings back to you as a wine tasting card, with total
conviction and no mercy. The comedy is the delivery mechanism, and every joke
can cite the number it came from.

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
Nose         No .gitignore. Not a short one, not a wrong one, not a copied one.
             None. Everything todo-app has ever produced by accident is a
             candidate for the permanent record, and across 20 files the record
             has been keeping. 36 unresolved markers, 30 of them TODOs.
             src/legacy.js has 20 and has clearly been asking for help for some
             time. There is no README. 3 source files, 955 lines, and not one
             sentence explaining why.
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
receives the same tasting. A professional does not revise his verdict when
asked twice.

Exit code is 0 for any completed tasting, however damning, including bare
directories and repositories with no commits. Exit code 1 means the path could
not be read, and says so in one line. No traceback ever reaches you.

## What it measures

| Course | Metric |
|---|---|
| The label | languages, frameworks, file counts, committed sediment |
| Vintage | first and last commit dates, age, shallow clones |
| Nose | README, LICENSE and `.gitignore` presence and quality, TODO density, debug prints |
| Palate | file count, largest file, average length, maximum nesting depth, longest function |
| Structure | dependency counts per ecosystem, manifest against lockfile |
| Finish | commit count, fix ratio, longest silence, bus factor |

Complexity is measured by proxy: maximum indentation depth and function length
by per language regex. Proper cyclomatic analysis needs parsers, parsers need
dependencies, and dependencies are banned. The proxies are honest about being
proxies, and `--sober` prints them raw.

Every glass gets tasted. The tool completes on any directory of code, in any
language, in any state of neglect. A missing README, a missing manifest, an
unrecognised language, no git history at all: each absence is a finding, never
an error.

## Design rules

1. Measurement and comedy never share a file. `collect.py` returns data,
   `judge.py` applies thresholds, `voice.py` turns findings into lines, and
   every template string lives in `lines.py`. A joke in an analyzer fails
   review.
2. Zero runtime dependencies. Python 3.11 or newer, standard library only.
3. No em-dashes. Not in output, not in docs, not in comments. A unit test
   fails the build. The sommelier does not pause for breath.
4. Deterministic output, seeded on the repository name.
5. Every threshold lives in the `BANDS` table in `judge.py` and nowhere else.

## Develop

```bash
python -m unittest discover -s tests -t .
```

The suite uses `unittest` from the standard library, so the zero dependency
promise holds all the way into the tests. Type checking is the other gate:

```bash
mypy --strict sommelier tests
```

## Contributing

New tasting lines are welcome, and are the most useful thing you can add.
Each one must:

- cite a metric, using only the facts its finding key provides in
  `judge.KEY_FACTS`. If the number cannot be printed beside the sentence, the
  sentence is cut.
- pass the read-aloud bar. Say it once. If it needs explaining, or a second run
  at it, it does not enter the cellar.
- survive `tests/test_style.py`, which bans em-dashes, en-dashes, emoji and
  exclamation marks, and refuses any template citing a number that was never
  measured.

Keep to the register: total conviction, no hedging, no outside analogies, and
nothing that leaves the repository being tasted. The ceiling of available
praise is "Adequate."

Every finding key needs at least three lines. If the cellar runs thin, ship
fewer keys rather than weaker lines.

### Commit and pull request titles

Subject line only. No bodies, no footers, no trailers. Imperative, lower case,
50 characters or fewer. One logical change per commit. Allowed prefixes: `add`,
`fix`, `rm`, `docs`, `test`, `perf`.

```
add commit gap detection
fix vintage on shallow clones
rm unused nesting scanner
test em-dash ban
```

## Licence

MIT.
