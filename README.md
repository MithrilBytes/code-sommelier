# code-sommelier

**Real static analysis, read back as tasting notes by a critic who has seen
things.**

> **Work in progress.** The tool runs, is tested, and does what the sections
> below describe. It is not finished. The scoring model, the tasting material
> and the output are all still moving, so numbers and wording will change
> between commits. See [Status](#status) for what is built and what is not.

Point `sommelier` at a git repository and it measures age, file sizes, nesting
depth, dependency health, commit history, and everything that got committed by
accident. It reads those findings back as a wine tasting card, with total
conviction and a number at the end.

Every sentence on the card is generated from a measurement, and no sentence
survives that cannot print the number behind it. `--sober` prints the numbers
and keeps its opinions to itself.

The score took the longest to get right. It runs to 100 across six bands, and
**you cannot reach 90 by not being bad**: below 90 the tool deducts for defects,
and at 90 every gate has to be met at once. A repository it cannot read is
refused a number rather than handed a flattering one. A repository that hides
its history scores lower for hiding it.

## The card

```
CODE SOMMELIER                                   tasting no. 86

The label    todo-app. JavaScript, 3 files, 955 lines. It exists, which is the
             strongest thing that can be said for it so far. 1 secrets files,
             tracked, versioned, and backed up with admirable diligence to
             every clone that has ever been made. .env among them. 12 of the 20
             files here are vendored, which is 60 percent of the repository.
             The sommelier will pretend not to have seen that.
Vintage      2019 to 2019, 3 commits. The arithmetic is not flattering. 7.6
             years old. Age is not the same as improvement.
Nose         todo-app has no .gitignore of any kind, not even a copied one.
             Everything it has ever produced by accident is a candidate for the
             permanent record, and across 20 files the record has been keeping.
             37.7 markers per thousand lines. That is not a list of tasks, it
             is a diary. No README. The reader is expected to deduce 955 lines
             of intent from first principles.
Palate       3 files, 955 lines, nesting to depth 2. One file, src/legacy.js,
             contains 900 lines against an average of 318.3. Nobody decided
             this. It accumulated.
Structure    5 javascript dependencies, unlocked. Two people installing this on
             the same day will not get the same project.
Finish       The last word on the matter is fix login again. Nothing has been
             committed for 2,479 days. The last was 2019-11-03. This is not a
             project, it is a preserve. 33 percent of the history says fix, 1
             of 3 commits. At some point that stops being maintenance and
             starts being the shape of the thing.
Verdict      8 of 8 dimensions were measured. They give 60 points. Below
             average.
Pairing      Pairs with a second opinion, which the sommelier does not offer.
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

The file inventory comes from `git ls-files --cached --others
--exclude-standard`, so gitignored build output is left out of the body,
largest file, nesting depth and marker density, while work that is written but
not yet committed is counted. Vendored directories are pruned separately, which
catches a `node_modules` in a repository that never told git to ignore it. The
sediment course is a different question and keeps its own committed-only view,
because an uncommitted local virtualenv is untidy rather than a sin. `--sober`
and `--json` report which inventory was used, and the card says so in a footnote
whenever git could not answer and the counts fell back to a filesystem walk.

The tool completes on any directory of code, whatever language it is written in
and whatever condition it has been left in. Absent input is treated as a finding
rather than an error, so a repository lacking a README, a dependency manifest, a
recognised language or a git history still produces a full card and exits 0.

## The score

The number is on a hundred point scale with six bands, narrower at the top.

| Band | Meaning |
|---|---|
| 96 to 100 | Exemplary. Every gate, plus evidence of sustained care. |
| 90 to 95 | Outstanding. All positive gates met. |
| 80 to 89 | Sound. No serious defect, no demonstrated craft either. |
| 70 to 79 | Average. Working, with noticeable deficiencies. |
| 60 to 69 | Below average. Several defects, or one severe one. |
| 50 to 59 | Unacceptable. |
| no score | Nothing to taste. Stated as a refusal, with a reason. |

**You cannot reach 90 by not being bad.** Below 90 the tool runs a deduction
system. At 90 and above it switches to positive evidence: a repository enters
the band by meeting every gate at once, and each gate costs the author real
effort. Tests that exist. A README past a length floor and a licence beside it.
A `.gitignore`, no committed secrets, no operating system cruft. A manifest
with a lockfile against every dependency it declares. Complete history, more
than one author, and a commit cadence that has not gone dormant. Missing any
one of them caps the repository at 89, however clean the rest of it is.

The score is computed over eight dimensions: documentation, hygiene, testing,
structure, body, markers, history and authorship. **A dimension whose inputs
were never measured is dropped from the denominator**, and the denominator is
printed beside the number on the card and in `--sober`. Every dropped dimension
also adds a fixed weight to the deduction, and every gate fails when its
evidence is absent rather than passing by default. Together those two rules
make the score monotone in the information available: withholding a measurement
can lower a score and can never raise one. A shallow clone scores at or below
the full clone, which under the previous formula it did not.

An analyzer that stopped at the time budget counts as a measurement that did
not happen, not as a measurement that found nothing. Its dimensions leave the
denominator and the gates that read it fail, so a run too short to reach the
committed key cannot report a clean tree, and a log read that stopped after the
recent commits cannot report a lively project. A walk that never finished is
refused a number rather than given one.

A repository the tool cannot read is refused rather than ranked. No source
files, or fewer than half the source files attributable to any language, and
the card prints the reason and no number. A tree of `.gitignore` templates is
not scored above a text editor.

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

## Status

Work in progress, roughly a third of the way through the v2 specification in
[SPEC-v2.md](SPEC-v2.md). Everything documented above is implemented and under
test. What follows is not.

**Built and working**

- Measurement, with an explicit record of what could not be measured.
- The scoring model: gates, six bands, refusal for repositories nothing can
  read, and renormalisation over measured dimensions.
- The content-planning layer that stops a course repeating itself.
- 333 tests, `mypy --strict`, and CI across Python 3.11, 3.12 and 3.13.

**Not built yet**

- **The grammar engine.** Tasting lines are still drawn from a flat list, so
  roughly a fifth of the sentences printed across ten repositories also appear
  on another repository's card. This is the largest remaining piece of work.
- **The precision floor.** No detector publishes a precision figure yet, and
  nothing stops a low-confidence detector speaking in prose rather than only
  printing a number.
- **Calibration.** Scores order within a band by deduction, not against a
  reference population, so there is no percentile behind the number.
- **The leaderboard.** Not started.

**Known gaps in what is built**

- Eleven findings across the ten pinned repositories are measured and judged
  and then never said, because a finding reserves every fact it might cite
  before anything knows which sentence it will actually print.
- The attribution floor that decides whether a repository can be scored at all
  is a round number rather than a calibrated one.
- The dependency gate tests whether a lockfile exists, not whether it agrees
  with the manifest.

**A note on the material.** The house rule for this project is that every
tasting line is written by a person who meant it. The lines currently in
`lines.py` were not, and are placeholder material pending a rewrite. The claims
the tool makes about itself at runtime are narrower and are enforced by tests:
no model, no network, and the only binary it can execute is git.

## Licence

MIT.
