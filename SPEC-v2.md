# code-sommelier v2, build spec

> A score that means something, prose that cannot repeat itself, and a cellar
> book of public repositories. Still no AI at runtime. Still no em-dashes.

## What changes, and why

v1 works. It measures honestly, it tastes any directory, it ships green. Two of
its founding decisions are now reversed on purpose, and a third problem was
found while planning the reversal.

**The score was useless by design.** v1 said so: everything lands between 87 and
94, "the one place the tool is permitted to be useless on purpose." That was a
good joke exactly once. A leaderboard cannot be built on it.

**The prose was a flat list.** 45 finding keys, 140 sentences, one drawn per
finding. It reads as baked because it is baked.

**The tool states false things with total confidence.** Nobody asked about this.
It is the one that matters most, because it is the one that ends the project.

### The measurements behind those three claims

Every measurement in this document comes from the ten public repositories
pinned in `tests/corpus_manifest.json`, each fixed at a commit. Tasted with v1:

| repo | score | files | attributed | lines | depth | largest | tests | commits |
|---|---|---|---|---|---|---|---|---|
| antirez/kilo | 89 | 2 | 2 | 1,315 | 6 | 1,308 | no | 20 |
| github/gitignore | 93 | 309 | 0 | 8,850 | 0 | 705 | yes | 4,217 |
| golang/example | 92 | 55 | 46 | 3,943 | 5 | 283 | yes | 76 |
| jashkenas/underscore | 89 | 356 | 355 | 176,589 | 9 | 4,811 | yes | 2,892 |
| kelseyhightower/envconfig | 90 | 9 | 8 | 1,658 | 6 | 864 | yes | 132 |
| pallets/itsdangerous | 92 | 19 | 18 | 1,783 | 5 | 404 | yes | 677 |
| psf/requests | 91 | 58 | 48 | 12,828 | 7 | 3,094 | yes | 6,490 |
| rbenv/rbenv | 94 | 30 | 6 | 2,219 | 5 | 164 | yes | 855 |
| sharkdp/fd | 90 | 32 | 31 | 9,191 | 7 | 2,878 | yes | 2,005 |
| sindresorhus/slugify | 91 | 4 | 4 | 689 | 4 | 286 | no | 71 |

The `attributed` column is how many of those source files any language
detector could actually read, which is the number the v1 score ignored. The
inputs span 246 times in size. The scores span five points, standard
deviation 1.58. The ordering is worse than the spread:

> **The two highest scores belong to the two repositories the tool could barely
> read.** `rbenv/rbenv` takes the top score of 94 with 6 of its 30 files
> attributed to any language. `github/gitignore` takes 93 with **zero of 309**,
> because it contains no program at all. `antirez/kilo`, a hand-written text
> editor in 1,300 lines of C that people read specifically to learn from,
> scores 89.

That is not a scale with a calibration problem. It is a scale that rewards
being illegible, because every unmeasured dimension silently scored as clean.
The same defect pays out through a second door: `git clone --depth 1` on
`pallets/itsdangerous` scores 93 where the full clone scores 92. Withholding
information is the single most reliable way to raise a v1 score, and that is
the whole argument for Part 1.

On the prose, the numbers are worse than they look:

- One fixed finding set can produce 10,847,773,692 distinct cards.
- A reader can ever see 140 sentences, across every repository, forever.
- One card shows up to 20 of them, so a single card is 14.3 percent of the
  entire corpus.
- Across those ten repositories, **24 percent of printed sentences repeat**, and
  the repeats are the memorable ones. "Age is not the same as improvement" and
  "Old, and not in the way that adds value" each appear on four cards out of
  ten.

## Non-negotiables

Carried over from v1, unchanged:

1. **Measurement and comedy never share a file.** A joke in `collect.py` fails
   review.
2. **No AI at runtime.** No model, no API call, no network in the CLI.
3. **No em-dashes.** Enforced by a test that fails the build.
4. **Zero runtime dependencies in the CLI.** Python 3.11 or newer, stdlib only.
5. **Deterministic output.** Same repository, same tasting, forever.

New, and equally binding:

6. **No confident falsehood.** A detector that cannot demonstrate its precision
   does not get to speak in prose. It may still print a number.
7. **No named humans in published output.** The critique is aimed at code.
8. **Perceived variety is a measured property, not an aspiration.** It has a
   threshold and the build fails below it.
9. **The tool tastes the path it is given and nothing else.** It never walks a
   parent, never enumerates sibling directories, never discovers repositories on
   the machine it is running on. `sommelier taste PATH` reads under `PATH`.
10. **Development and calibration use public repositories only.** Every
    repository named in this document, in any test, in any snapshot, in any
    corpus and on the leaderboard is public and pinned by commit in
    `tests/corpus_manifest.json` or the roster. The maintainer's own
    repositories are never measured, never scored, never seeded, never used as
    evidence, and never eligible for the leaderboard. This is not a default to
    be overridden by a flag.

## Part 1: the score

### The one idea worth stealing from wine

Parker's 100-point scale defines its bands asymmetrically. The 80s are defined
by an **absence**: "no noticeable flaws." The 90s are defined by a **presence**:
"exceptional complexity and character." Crossing 90 is a change in kind, not a
change in degree.

That is the whole design:

> **You cannot reach 90 by not being bad.**

Below 90 the tool runs a deduction system, which is what the UC Davis 20-point
card actually is underneath: roughly twelve of its twenty points are awarded for
the absence of defects rather than the presence of quality. Deduction systems
are excellent at separating flawed from sound and hopeless at separating good
from great, which is precisely why Parker's scale exists alongside it.

At 90 and above, the tool switches to positive evidence. A repository enters the
90s by satisfying a stated conjunction of conditions, all of which cost the
author real effort: tests that exist and run, a lockfile that agrees with the
manifest, documentation past a length floor, commit hygiene, more than one
contributor or an explicit statement that this is a single-author project.

### Bands are gates, percentiles only order within a band

A pure percentile score would make 90 mean "better than 90 percent of
repositories." That is definitionally not a change in kind, and it destroys
every rhetorical asset the band structure buys. So:

- **Gates decide the band.** Predicates, published, checkable.
- **Percentile orders within the band.** It breaks ties. It is labelled as
  tie-breaking and never as measurement.

### The bands

Non-uniform widths, narrower at the top, so scarcity is a property of the
geometry rather than of the tool's mood.

| Band | Width | Meaning |
|---|---|---|
| 96 to 100 | 5 | Exemplary. Every gate, plus evidence of sustained care. |
| 90 to 95 | 6 | Outstanding. All positive gates met. |
| 80 to 89 | 10 | Sound. No serious defect, no demonstrated craft either. |
| 70 to 79 | 10 | Average. Working, with noticeable deficiencies. |
| 60 to 69 | 10 | Below average. Several defects, or one severe one. |
| 50 to 59 | 10 | Unacceptable. |
| no score | | Nothing to taste. Stated as a refusal, with a reason. |

A repository with no source files returns **no score** and says why. It does not
return 91. A repository that is a collection of templates rather than a program
is scored as what it is, or refused, rather than being ranked above a text
editor.

Cicchetti, Showalter and Tyrer (1985) found seven ordinal categories to be
functionally interchangeable with a hundred. The integer is a presentation
format the genre demands. The band is the measurement, and the card publishes
the indistinguishability interval so the number is not read for more precision
than it has.

### Rules that keep the score honest

- **Score only over measured dimensions, then renormalise, and print the
  denominator.** v1 computes `94 - penalties`, so a shallow clone or a missing
  git binary removes findings and *raises* the score. On a leaderboard that is a
  gaming vector: withholding information is neither faking nor doing the work,
  and it currently pays.
- **Per-language bands.** Indentation depth means one thing in Python, less in
  Go, and nothing in minified JavaScript. v1 already concedes this for exactly
  one metric, by hand, in `BANDS["dependency_counts"]`. Generalise it, and
  refuse to score a structural metric for a language not in the table.
- **Balance is two-sided.** The WSET tasting card scores every axis for
  deficiency and for excess: austere and thin at one end, cloying and sticky at
  the other. Most v1 metrics band one direction only. Zero TODOs is as
  suspicious as forty. Zero dependencies is austere, three hundred is cloying.
  This is better judgement and it doubles the available material.
- **Calibration is a versioned artefact.** `sommelier/calibration/v1.json`
  ships in the wheel as package data. Every score is reported as `(score, calibration_version,
  metric_schema_version)`. Recalibration publishes a new version. A published
  score is never mutated in place, and the leaderboard renders a hard break in
  the series rather than a smooth line across incompatible units.

## Part 2: the prose

### The governing law

SCIgen, the MIT paper generator, produces roughly 2 to the power 8,900 of choice
entropy per paper. Anyone who reads two SCIgen papers recognises them instantly
as the same paper. The reason is measurable: its `SCI_BUZZWORD_NOUN` symbol has
twelve alternatives and is drawn nineteen times per paper, giving about 66
percent overlap between two independent outputs.

> **Perceived variety is set by the worst symbol's uses-per-card divided by its
> cardinality. It has almost nothing to do with the size of the space.**

v1 has the same disease in a simpler form. Adding templates to a flat list
raises the ceiling and does not touch the floor.

### Three layers, in order

**Content plan** (`plan.py`, new). Findings are grouped, facts are deduplicated
across findings, and the number of surviving propositions decides sentence
shape: one clause, a coordinated sentence, or a main plus a subordinate. This
layer exists because v1 renders every finding in ignorance of its neighbours,
and the output shows it:

```
2026. The first commit landed on 2026-08-12 and the last on 2026-08-12,
0.0 years apart, across 16 commits. 2 days old, first committed on 2026-08-12.
```

The same date three times in two sentences. On a larger repository, adjacent
sentences report "15.5 years" and "15 years" and contradict each other on
rounding. That is a factual self-contradiction produced purely by architecture,
and no amount of new material fixes it.

**Grammar** (`grammar.py`, new). A context-free grammar replaces the flat list.

- Symbols are delimited, `#like_this#`. SCIgen matches bare rule names against
  the output text, which silently corrupts the grammar the moment a rule name
  occurs as ordinary English. That fragility is not worth inheriting.
- Measured facts bind as **single-alternative rules injected before expansion**.
  This is exactly how SCIgen keeps one system name consistent across thirty
  mentions, and here it preserves the v1 guarantee that every line cites a real
  number.
- Optionality is a **weighted empty alternative**, so the density of any device
  is a tunable number rather than a code branch.
- **The cardinality law is enforced**: for every symbol, cardinality must be at
  least k times its expected uses per card. A symbol drawn three times a card
  needs far more alternatives than one drawn once.
- Memorable tokens are sampled **without replacement** within a card.

**Realisation** (`voice.py`, rewritten). Seeded per repository, as before.

### The register

The target is not the gag. From the research, the funniest line in the most
famous restaurant demolition of the last twenty years is:

> Why did the toasted marshmallow taste like fish?

Short, flat, two concrete nouns, no joke in it. That is reachable by a grammar.
Punchlines are not.

### Banned constructions

Ted Gioia's four named failure modes of the scathing review describe the v1
cellar almost exactly, so this list is a description of what to remove rather
than a theory about what might go wrong:

1. **Prose inflation.** Reaching for extremity by default.
2. **The vindictive thesaurus entry.** "dry" becoming "desiccated."
3. **Mock simile as the default setting.** Every minor fault compared to a
   catastrophe.
4. **Joke structure displacing analysis.** Setup, punchline, setup, punchline,
   until the laughs crowd out the finding.

Added to those, the constructions that mark text as machine written: the
tricolon, forced antithesis as a default move, empty intensifiers, and the
punchline that explains itself.

### Rule 5, amended

v1 said: the material is the code, no outside analogies, nothing that leaves the
repository. That rule is why the prose stays honest and also why it reads flat,
since it removes the cheapest source of specificity while leaving the template
structure that causes the flatness untouched.

Amended: **one outside referent per card, never in a sentence containing a
number.** Metric sentences stay literal and checkable. The single licensed
referent buys specificity without the tool becoming a simile machine.

### Repetition is a build gate

Two different failures, two different tests.

- **Cross-card sameness.** Generate cards across a fixture corpus, measure
  pairwise Jaccard overlap of content words, distinct-n, and constant-token
  fraction. Fail the build above threshold. This is what turns "guarantee no
  repetition" into an enforced invariant instead of a hope.
- **Intra-card tells.** A lint pass over generated output for the banned
  constructions above, living beside the existing dash and emoji gates.

## Part 3: truthfulness

Two defects of this kind were found and fixed while writing this spec: Adobe
Illustrator files counted as source, so the nesting-depth finding on
`psf/requests` was attributed to a 2.1 MB logo; and the expired certificates of
an HTTPS test suite were reported as committed secrets. Both were false, both
were stated with total conviction, and both are gone.

The category is not closed. Three defects of the same kind are open, and they
are worse than the two that are fixed:

1. **The 64 KiB read cap truncates line counts silently.** `collect.py` reads
   every file to a cap and then reports the resulting count as the file's
   length. `psf/requests` `tests/test_requests.py` is 3,094 lines and is
   reported as 1,850, a 40 percent undercount, on the metric the card calls the
   largest file. Three of the ten pinned repositories have a wrong
   `largest_file_lines`, and **the evidence table at the top of this document
   prints the truncated numbers**. Line and marker counts must be streamed over
   the whole file. The structural analysis may keep a cap, and must then record
   a coverage gap rather than report a number as if it were complete.
2. **Not measured is encoded as zero.** `longest_function_lines == 0` means
   either that the longest function is short or that no detector exists for that
   language, and 52 of the 78 known languages have no detector. Nothing in the
   model distinguishes the two, so judge cannot tell a clean result from an
   absent one.
3. **Language coverage is unrecorded.** `github/gitignore` reports 309 source
   files with zero of them attributed to any language, and `rbenv/rbenv` takes
   the corpus top score of 94 on a repository where 6 files of 30 were
   recognised. A score computed from metrics that were never really measured is
   the same failure as the shallow-clone one below, arriving by a different
   road.

Requirements:

- A **labelled validation set** of public repositories with expected findings.
- A **published per-detector precision figure**.
- **Below the precision floor, a detector may print a number in `--sober` and
  may not appear in prose.** Conviction is the voice's entire charm and it is
  only charming when the underlying claim is true.
- **A detector must be able to say "not measured" and have judge respect it.**
  Today a shallow clone scores *higher*: measured on `pallets/itsdangerous`, a
  full clone scores 92 and `git clone --depth 1` scores 93, with nothing
  dropped and nothing flagged. Withholding information currently pays.

## Part 4: the cellar book

A public leaderboard of rated repositories.

| Decision | Choice |
|---|---|
| Inclusion | Opt-in, plus a seeded set of large well-known public projects |
| Excluded, permanently | Any repository owned by this project's maintainer |
| Liveness | Scheduled static rebuild, GitHub Actions to Pages |
| Dependencies | Still stdlib only |
| Named humans | Never |
| Low scores | Published, with a documented removal path |

**Calibration corpus and leaderboard are separate things.** An opt-in board
publishes a self-selected distribution, which is the Wine Enthusiast pathology:
that publication refuses to print anything below 80, so its published
distribution is not the real one. So the tool calibrates against a large sampled
corpus that is **never published per repository**, publishes only that corpus's
aggregate distribution and control points, and ranks opt-in named repositories
against that honest anonymous denominator. OpenSSF Scorecard already runs this
shape at roughly a million repositories.

**Budget.** The binding constraint is the Actions `GITHUB_TOKEN` at 1,000 REST
requests per hour per repository. Repository metadata batches through GraphQL,
where 100 repositories of scalar fields costs a single point.

**Conduct.** The rule from restaurant criticism is punch up, not down. A
hobbyist's 200-line first project is the family trattoria, and a scathing
automated review of it is not criticism. Opt-in handles consent; the seeded set
is restricted to projects large enough that public critique is ordinary fair
comment.

## Architecture

```
sommelier/
  cli.py          argparse, exit codes, nothing else
  collect.py      metrics only, pure functions           (mostly unchanged)
  judge.py        gates, bands, subscores                (rewritten)
  calibration/    versioned quantile tables, package data (new)
  plan.py         content planning and aggregation       (new)
  grammar.py      CFG expansion, fact binding            (new)
  lines.py        the cellar, now grammar rather than list
  voice.py        realisation, seeded                    (rewritten)
  render.py       card, json, sober                      (extended)
cellar/           leaderboard build, static site         (new)
```

The calibration tables live **inside** the package. A repo-root sibling of
`sommelier/` cannot be shipped as package data under any setuptools
configuration, and the CLI must be able to read them from an installed wheel
via `importlib.resources`.

Data flows one way: collect, judge, plan, voice, render.

## Testing

Everything in v1 stays, plus:

- `test_truth.py`: the labelled validation set and the precision floor.
- `test_variety.py`: cross-card sameness thresholds and the cardinality law.
- `test_style.py` gains the banned-construction lint.
- `test_score.py`: band gates at every edge, renormalisation with missing
  dimensions, and the invariant that removing a measurement can never raise a
  score.

## Build order

1. **Truth.** Part 3. Nothing is safe to publish before this.
2. **Score.** Part 1.
3. **Content plan.** The layer that removes the contradictions.
4. **Grammar.** Then the variety gates.
5. **Cellar book.** Only once the rest is green.

## Definition of done

A stranger runs it on their own repository. The number is defensible enough that
they argue with it rather than dismiss it. The notes are specific enough that
they wince at one true thing. They read a second card, on a different
repository, and it does not sound like the first one.

The build fails if anyone commits an em-dash. The build also now fails if the
prose starts repeating itself, and if a detector starts lying. All three matter
equally.
