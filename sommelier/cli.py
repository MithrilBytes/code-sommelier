"""The front door.

Argument parsing and exit codes. Nothing else belongs in this file.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sommelier.collect import collect
from sommelier.judge import judge
from sommelier.plan import compose
from sommelier.render import render_card, render_json, render_sober
from sommelier.voice import pour

CANNOT_TASTE = "I cannot taste what has not been poured."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sommelier",
        description="Real static analysis, delivered as tasting notes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    taste = subparsers.add_parser("taste", help="taste a repository")
    taste.add_argument(
        "path", nargs="?", default=".", help="path to the repository (default: .)"
    )
    output = taste.add_mutually_exclusive_group()
    output.add_argument(
        "--json", action="store_true", help="emit full metrics as JSON, no jokes"
    )
    output.add_argument(
        "--sober", action="store_true", help="print the plain metrics table"
    )
    taste.add_argument(
        "--seed", type=int, default=None, help="override the seeded line selection"
    )
    return parser


def _taste(path_argument: str, *, as_json: bool, sober: bool, seed: int | None) -> int:
    path = Path(path_argument)
    metrics = collect(path)
    judgement = judge(metrics)

    if as_json:
        output = render_json(metrics, judgement)
    elif sober:
        output = render_sober(metrics, judgement)
    else:
        output = render_card(pour(compose(metrics, judgement), seed=seed))

    print(output)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _taste(
            args.path, as_json=args.json, sober=args.sober, seed=args.seed
        )
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 1
    except Exception:
        # No traceback ever reaches the user. The sommelier does not explain
        # himself in a stack trace.
        print(CANNOT_TASTE, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
