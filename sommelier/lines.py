"""The cellar.

Every template string in code-sommelier lives in this file and nowhere else.
Nothing here measures anything. Nothing here decides anything. This module is
material, and the only module permitted to have an opinion.

House rules for anyone adding a line:

1. Every line cites a number. If the metric cannot be printed beside the
   sentence, the sentence does not go in.
2. Placeholders are str.format style and may only name facts that judge.py
   guarantees for that key. KEY_FACTS in judge.py is the list. A test enforces
   this, so a line cannot cite a number that was never measured.
3. The read-aloud bar. Say it once. If it needs explaining, or a second run at
   it, it does not enter the cellar.
4. No exclamation marks, no emoji, no em-dashes. A test fails the build.
5. The material is the repository. No outside analogies, no cultural
   references, nothing that leaves the tree being tasted.
6. Total conviction. The sommelier does not think the file is too long.
7. The ceiling of available praise is "Adequate."

Every key needs at least three lines. Fewer than three and the tasting starts
repeating itself, which is worse than saying less.
"""

from __future__ import annotations

from typing import Final

CELLAR: Final[dict[str, tuple[str, ...]]] = {
    # ----------------------------------------------------------------- label
    "label.identity": (
        "{name}. {language}. {source_file_count} source files out of "
        "{file_count} on disk, and {total_lines} lines between them.",
        "{name}, written in {language}, across {source_file_count} files. That "
        "is the last neutral sentence in this tasting.",
        "{name}. {language}, {source_file_count} files, {total_lines} lines. It "
        "exists, which is the strongest thing that can be said for it so far.",
        "This is {name}. It is {language}. There are {source_file_count} source "
        "files, and every one of them was somebody's idea.",
    ),
    "label.vendored": (
        "{vendored_files} of the {total_files} files here are vendored, which is "
        "{vendored_share} percent of the repository. The sommelier will pretend "
        "not to have seen that.",
        "There are {dirs_phrase} of vendored code committed to this repository, "
        "carrying {vendored_files} files that nobody in this building wrote.",
        "{vendored_files} committed vendored files, {vendored_share} percent of "
        "everything here. That is not a repository, it is a warehouse with a "
        "git remote.",
        "{vendored_share} percent of this repository was downloaded rather than "
        "written. {vendored_files} files of it, committed, pushed, and left.",
    ),
    "label.secrets": (
        "{secret_files} environment files are committed. {path} is in the "
        "history, and history is forever.",
        "There is a tracked {path}. The sommelier has decided not to read it, "
        "which is more restraint than the internet will show.",
        "{secret_files} secrets files, tracked, versioned, and backed up with "
        "admirable diligence to every clone that has ever been made. {path} "
        "among them.",
    ),
    "label.os_cruft": (
        "{cruft_files} files here were written by the operating system rather "
        "than by a developer, {path} among them, and they were committed anyway.",
        "{cruft_files} pieces of desktop cruft are under version control. "
        "Someone's file browser has been contributing to this project.",
        "{cruft_files} operating system droppings in the tree, including "
        "{path}. Even the filesystem wanted credit.",
    ),
    "label.large_binary": (
        "{binary_count} binaries over five megabytes are committed, the largest "
        "being {largest_path} at {largest_mb} MB. Git will remember it for the "
        "rest of its life.",
        "{largest_path} weighs {largest_mb} MB and lives in the history "
        "permanently. Every clone downloads it. Every clone always will.",
        "{binary_count} files over five megabytes have been committed, "
        "{largest_path} the heaviest at {largest_mb} MB. Cloning this is not a "
        "download, it is a delivery.",
    ),
    "label.polyglot": (
        "{language_count} languages share this tree: {languages}. They do not "
        "agree on indentation and they never will.",
        "{languages}. That is {language_count} languages, of which {primary} "
        "leads on {primary_share} percent, and nobody here has read the "
        "conventions for more than two.",
        "{language_count} languages in one repository: {languages}. {primary} "
        "holds {primary_share} percent, and not one of them is finished.",
    ),
    "label.monoculture": (
        "{share} percent of this is {language}, across {file_count} files. "
        "Commitment, of a sort.",
        "{share} percent {language}. There is no second opinion anywhere in "
        "this tree.",
        "One language, {language}, at {share} percent of {file_count} files. "
        "Whatever happens next is entirely its fault.",
    ),
    # --------------------------------------------------------------- vintage
    "vintage.declared": (
        "{first_year}. The first commit landed on {first_date} and the last on "
        "{last_date}, {years} years apart, across {commits_phrase}.",
        "{first_year} to {last_year}. {years} years, {commits_phrase}. "
        "The arithmetic is not flattering.",
        "Laid down in {first_year}, last disturbed on {last_date}. "
        "{commits_phrase} stand between those two dates.",
        "{first_year}. A vintage of {years} years and {commits_phrase}, "
        "and the sommelier has tasted every one of them.",
    ),
    "vintage.no_history": (
        "There is no repository here. {name} holds {file_count} files of entirely "
        "unknown provenance.",
        "This has never been committed. {name} is not a vintage, it is a puddle.",
        "{name} has no git directory. Not one of its {file_count} files has a "
        "date, an author, or a reason.",
    ),
    "vintage.empty": (
        "{name} has a repository and not one commit. The glass is poured and "
        "the bottle was empty.",
        "A git repository containing no commits. {name} has been prepared for a "
        "history it has not begun, and {file_count} files are waiting.",
        "{name}. Initialised, never committed, {file_count} files on disk. "
        "Somebody meant to start.",
    ),
    "vintage.shallow": (
        "This is a shallow clone. {commit_count} commits are visible and the "
        "rest have been withheld, which the sommelier will take personally.",
        "{commit_count} commits, and the history is truncated. Judgement will "
        "proceed on what was served.",
        "A shallow clone. {commit_count} commits shown. The sommelier can only "
        "taste what reached the glass.",
    ),
    "vintage.aged": (
        "{years} years in the cellar since {first_year}. Age is not the same as "
        "improvement.",
        "First committed on {first_date}, {years} years ago, and {commits_phrase} "
        "have followed. Old, and not in the way that adds value.",
        "{years} years old. {first_year} was a long time ago, and this has been "
        "here for all of it.",
    ),
    "vintage.recent": (
        "{days} days old, first committed on {first_date}. Too young to have "
        "made its mistakes yet.",
        "Bottled {days} days ago, {commits_phrase} in. Everything is "
        "still ahead of it, including the regret.",
        "{first_date}, and only {days} days of it. The sommelier will return "
        "when it has aged into something arguable.",
    ),
    # ------------------------------------------------------------------ nose
    "nose.documented": (
        "A README of {readme_lines} lines and a {license_name} licence. Adequate.",
        "{license_name}, and {readme_lines} lines in {readme_path}. The "
        "paperwork is in order, which is the highest compliment available.",
        "The nose is clean. {readme_lines} lines of README, licensed "
        "{license_name}, and nothing to complain about, which is itself "
        "suspicious.",
    ),
    "nose.no_readme": (
        "There is no README. {source_files} source files, {total_lines} lines, "
        "and not one sentence explaining why.",
        "No README. The reader is expected to deduce {total_lines} lines of "
        "intent from first principles.",
        "{source_files} files, zero lines of README. The authors of {name} knew "
        "what it did, and that was evidently enough for them.",
    ),
    "nose.thin_readme": (
        "{readme_path} runs to {readme_lines} lines. It is less a document than "
        "a gesture.",
        "{readme_lines} lines of README, {readme_bytes} bytes in total. "
        "Somebody started, and then something more interesting happened.",
        "A {readme_lines} line README. It answers no question that anyone has "
        "ever had.",
    ),
    "nose.no_license": (
        "No licence file. Legally, {name} belongs to nobody and may be used by "
        "nobody, which is a bold distribution strategy.",
        "There is no licence. Anyone who copies {name} is guessing, and so is "
        "anyone who does not.",
        "No LICENSE file anywhere. {name} is public and unusable at the same "
        "time.",
    ),
    "nose.no_gitignore": (
        "There is no .gitignore. The sommelier would like a moment. A "
        ".gitignore is four lines of text. It takes ninety seconds to write, it "
        "has taken ninety seconds to write for twenty years, and its absence "
        "means every build artefact, every editor backup and every local secret "
        "among the {total_files} files in {name} has been offered to the "
        "repository, and the repository has accepted. This is the finding the "
        "sommelier will think about tonight.",
        "{name} has no .gitignore of any kind, not even a copied one. Everything "
        "it has ever produced by accident is a candidate for the permanent "
        "record, and across {total_files} files the record has been keeping.",
        "{name} has no .gitignore file. Every temporary thing among its "
        "{total_files} files is one careless git add away from being permanent. "
        "The sommelier has seen the consequences of this and would rather not "
        "discuss them.",
    ),
    "nose.no_tests": (
        "No tests. {source_files} source files, {total_lines} lines, all of "
        "them correct by assertion.",
        "There is no test suite. The {source_files} files here have never been "
        "asked to prove anything.",
        "No tests anywhere. Confidence in {total_lines} lines is being "
        "sustained by memory alone.",
    ),
    "nose.debug_prints": (
        "{debug_prints} debug print statements survive across {source_files} "
        "source files. A faint whiff of console output in production code. It "
        "lingers.",
        "{debug_prints} stray print statements remain. Somewhere a log file is "
        "filling up with somebody's afternoon.",
        "There are {debug_prints} debugging prints left across {source_files} "
        "files. They were temporary. They are now load bearing.",
    ),
    "abandonment.suspiciously_clean": (
        "Not one TODO across {total_lines} lines. Either this is finished, or "
        "nobody has been honest in writing.",
        "{total_lines} lines in {source_files} files and zero markers. A clean "
        "nose. Suspiciously clean.",
        "Not a single marker of any kind across {total_lines} lines. The "
        "sommelier does not believe it, and cannot prove otherwise.",
    ),
    "abandonment.notes": (
        "Notes of abandonment: {total} markers, {per_kloc} per thousand lines, "
        "with {worst_path} carrying {worst_count} on its own.",
        "{todo} TODOs, {fixme} FIXMEs, {hack} HACKs and {xxx} XXXs, running at "
        "{per_kloc} per thousand lines. Present, but within the range of "
        "ordinary human intention.",
        "{total} markers left in the source. {worst_path} accounts for "
        "{worst_count} of them, which makes it the confession.",
    ),
    "abandonment.aggressive": (
        "Aggressive notes of abandonment. {total} markers at {per_kloc} per "
        "thousand lines, and {worst_path} alone holds {worst_count}.",
        "{per_kloc} markers per thousand lines. That is not a list of tasks, it "
        "is a diary.",
        "{total} unresolved markers, {todo} of them TODOs. {worst_path} has "
        "{worst_count} and has clearly been asking for help for some time.",
        "The abandonment is on the nose immediately: {total} markers, "
        "{per_kloc} per thousand lines. Every one was written by somebody who "
        "intended to come back.",
    ),
    # ---------------------------------------------------------------- palate
    "palate.body": (
        "{source_files} files averaging {average_lines} lines. The largest, "
        "{largest_path}, runs to {largest_lines}. Nesting reaches depth {depth}.",
        "Body: {source_files} files, {average_lines} lines on average, peaking "
        "at {largest_lines} lines in {largest_path}.",
        "Average length {average_lines} lines across {source_files} files, with "
        "{largest_path} at {largest_lines} and nesting down to depth {depth}.",
    ),
    "palate.empty": (
        "There are no source files. {total_files} objects on disk in {name} and "
        "not one of them is code.",
        "Nothing to taste. {total_files} files, zero of them source.",
        "The palate is empty. {name} has {total_files} files, none containing "
        "code the sommelier recognises as an attempt.",
    ),
    "palate.full_bodied": (
        "Full bodied. {path} runs to {lines} lines against an average of "
        "{average_lines}, which is long, but survivable.",
        "{path} at {lines} lines. Full bodied, heavy on the finish, and nobody "
        "has volunteered to split it.",
        "The largest file, {path}, is {lines} lines. Full bodied. It will be "
        "read once, by its author, and never again.",
    ),
    "palate.cry_for_help": (
        "{path} runs to {lines} lines, which is not a module, it is a cry for "
        "help.",
        "One file, {path}, contains {lines} lines against an average of "
        "{average_lines}. Nobody decided this. It accumulated.",
        "{lines} lines in {path}. Somewhere in the middle of it a decision was "
        "made that nobody remembers and everybody depends on.",
        "The body is enormous. {path} is {lines} lines long and it has never "
        "once been opened with confidence.",
    ),
    "palate.deep_nesting": (
        "Nesting reaches depth {depth} in {path}. Down there, conditions are "
        "difficult.",
        "Depth {depth} in {path}. Somewhere down there is an else branch that "
        "has never seen daylight.",
        "{path} nests to depth {depth}. By that level the code has stopped "
        "describing what it does and started describing how it got there.",
    ),
    "palate.abyssal": (
        "Nesting reaches depth {depth} in {path}. That is not control flow, "
        "that is sediment.",
        "Depth {depth} in {path}. At that indentation the line has more leading "
        "whitespace than meaning.",
        "{path} nests {depth} levels deep. Nothing at that depth has been "
        "understood by two people at the same time.",
    ),
    "palate.long_function": (
        "The longest function, {name} in {path}, runs to {lines} lines. It does "
        "not do one thing.",
        "{name} is {lines} lines long. It was one thing once, in {path}, some "
        "years ago.",
        "{lines} lines in a single function, {name}. It has an argument list, a "
        "personality, and no exit.",
    ),
    "palate.sampled": (
        "A barrel sample: {scanned} files read of {total}. The sommelier does "
        "not drink the whole cellar to price it.",
        "{total} source files is more than anyone should taste. {scanned} were "
        "sampled evenly, and the numbers are honest about it.",
        "Sampled, not exhaustive: {scanned} of {total} files. The findings "
        "hold. The precision does not.",
    ),
    # ------------------------------------------------------------- structure
    "structure.declared": (
        "{declared} declared {ecosystem} dependencies in {manifest_path}. "
        "Restrained, for what it is.",
        "Structure is sound. {declared} dependencies and {dev} development "
        "dependencies declared in {manifest_path}.",
        "{declared} {ecosystem} dependencies in {manifest_path}. Adequate. That "
        "is the whole of the praise.",
    ),
    "structure.undeclared": (
        "The dependencies are undeclared. {source_files} files in {name} import "
        "whatever was on the machine that day.",
        "No manifest of any kind. Whatever these {source_files} files need, "
        "they need it in secret.",
        "Undeclared. There is no manifest in {name}, so there is no answer to "
        "the question of what {source_files} files require in order to run.",
    ),
    "structure.tannic": (
        "Tannic. {declared} declared {ecosystem} dependencies against a "
        "threshold of {threshold}, not one of which will ever be removed.",
        "{declared} dependencies for one {ecosystem} project. Tannic, drying, "
        "and difficult to install twice the same way.",
        "{declared} {ecosystem} dependencies declared in {manifest_path}. "
        "Tannic. Every one is a decision somebody else gets to make later.",
    ),
    "structure.opaque": (
        "{declared} {ecosystem} dependencies, past the {threshold} at which the "
        "sommelier stops counting. Nobody on this project can name half of them.",
        "Opaque. {declared} declared dependencies and {dev} more for "
        "development. The tree beneath them has never been read by anyone alive.",
        "{declared} dependencies in {manifest_path}. Opaque, impenetrable, and "
        "installed in full every time anyone new joins the project.",
    ),
    "structure.no_lockfile": (
        "{manifest_path} declares {declared} dependencies and there is no "
        "lockfile. Every install is a fresh guess.",
        "{declared} {ecosystem} dependencies, unlocked. Two people installing "
        "this on the same day will not get the same project.",
        "No lockfile anywhere, against {declared} declared in "
        "{manifest_path}. The versions are whatever the registry felt like "
        "that morning.",
    ),
    "structure.drift": (
        "The lockfile disagrees with the manifest. {manifest_path} declares "
        "{declared}, {lockfile_path} holds {locked}. That is brave.",
        "{manifest_path} and {lockfile_path} do not agree: {reason}. Two "
        "sources of truth, which is one more than the maximum.",
        "Drift between manifest and lockfile. {reason}. Every install is a "
        "slightly different project.",
    ),
    # ---------------------------------------------------------------- finish
    "finish.history": (
        "{commits_phrase}, of which {fix_commits} are titled fix. It ends on "
        "{last_date} with {subject}.",
        "{commits_phrase} from {authors_phrase}. {fix_percent} percent say fix. "
        "The last one, on {last_date}, says {subject}.",
        "Long finish: {commits_phrase} ending {last_date}. The final word "
        "on the matter is {subject}.",
    ),
    "finish.no_history": (
        "No history. The code claims to have always existed.",
        "There is no git history at all. {name} has no finish, because it has "
        "no beginning.",
        "There is nothing in the log to read. {name} and its {file_count} files "
        "arrived fully formed and unexplained.",
    ),
    "finish.void": (
        "{name} has a repository and no commits. The finish is short, because "
        "there is nothing to finish.",
        "Zero commits. The tasting of {name} ends here, on the void, which at "
        "least is clean.",
        "No commits in {name}, though {file_count} files are waiting. Nothing "
        "has happened yet, and the sommelier finds that restful.",
    ),
    "finish.fix_ratio": (
        "{commits_phrase}. {fix_commits} of them titled fix. It is not fixed.",
        "{fix_percent} percent of the {commits_phrase} here say fix, and the "
        "count is still rising.",
        "{fixes_phrase} of {commits_phrase} are fixes. {fix_percent} "
        "percent. At some point that stops being maintenance and starts being "
        "the shape of the thing.",
    ),
    "finish.the_silence": (
        "Then the silence. {gap_days} days between {gap_start} and {gap_end}, "
        "during which nobody came back.",
        "There is a gap of {gap_days} days, {gap_start} to {gap_end}. Something "
        "happened, and it was not development.",
        "{gap_days} days of silence, {gap_start} to {gap_end}. The longest "
        "thing in this history is the pause.",
    ),
    "finish.single_estate": (
        "A single estate wine. {author} is responsible for {share} percent of "
        "{commit_count} commits, out of {author_count} names in the log.",
        "{author} wrote {author_commits} of {commit_count} commits, {share} "
        "percent. The bus factor is one. Everyone knows what that means and "
        "nobody has done anything about it.",
        "Single estate. Of {author_count} authors, {author} produced {share} "
        "percent of the work, which is either devotion or nobody else was "
        "allowed.",
    ),
    "finish.abrupt": (
        "It ends abruptly on {last_date}. The final commit says {subject}. It "
        "did not.",
        "The last commit, on {last_date}, is titled {subject}. That is where "
        "everyone stopped.",
        "The finish is abrupt. {subject}, on {last_date}, and then nothing.",
    ),
    "finish.dormant": (
        "Nothing has been committed for {days} days. The last was {last_date}. "
        "This is not a project, it is a preserve.",
        "{days} days since the last commit on {last_date}, which is {years} "
        "years. Whatever this was going to be, it has finished being it.",
        "Dormant. {years} years since {last_date}. The repository is not "
        "abandoned, it is resting, and it has been resting for {days} days.",
    ),
}

# The score is the one place the tool is useless on purpose, and says so.
VERDICTS: Final[tuple[str, ...]] = (
    "{score} points. Everything scores between 87 and 94 points. The notes are "
    "where the truth lives.",
    "{score} points. The number is a formality. Read the notes again.",
    "{score} points, because wine scoring is compressed and the sommelier "
    "respects tradition. The notes are not compressed.",
    "{score} points. The score has never told anyone anything, and it is not "
    "starting today.",
)

PAIRINGS: Final[tuple[str, ...]] = (
    "Pairs well with a strong drink and a rewrite.",
    "Pairs with a long weekend and no interruptions.",
    "Pairs with a fresh branch and lowered expectations.",
    "Pairs with a second opinion, which the sommelier does not offer.",
    "Pairs with silence, and a very slow read of the largest file.",
    "Pairs with coffee, and the courage to open the longest function.",
    "Decant into smaller files and revisit in a year.",
)

# Shown when an analyzer was dropped. Plain, because a footnote is not a joke.
FOOTNOTE_DROPPED: Final[str] = "{name} was dropped from the card: {reason}."
