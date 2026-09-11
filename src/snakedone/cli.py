"""The sole public command: snakedone FILE [--diff | --overwrite]."""

import argparse
import difflib
import sys
from pathlib import Path

from .execute import execute
from .parse import parse
from .snd import render, write


def get_parser():
    parser = argparse.ArgumentParser(prog="snakedone")
    parser.add_argument("file", type=Path, help="Python source (.py) or archive (.snd)")
    group_diff = parser.add_mutually_exclusive_group()
    group_diff.add_argument(
        "--diff", dest="diff", action="store_true", help="compare without writing"
    )
    group_diff.add_argument(
        "--overwrite",
        dest="diff",
        action="store_false",
        help="force to write or overwrite .snd file",
    )
    parser.set_defaults(diff=None)
    return parser


def main(argv: list[str] | None = None):
    parser = get_parser()
    args = parser.parse_args(argv)
    path: Path = args.file.resolve()
    if path.suffix not in (".py", ".snd"):
        parser.error("input must end in .py or .snd")
    target = path.with_suffix(".snd")
    if args.diff is None and path == target:
        diff = True
    else:
        diff = args.diff or False
    ret = main_file(path, target, diff)
    if ret != 0:
        sys.exit(ret)


def main_file(path: Path, target: Path, diff: bool = False):
    source = path.read_text(encoding="utf-8-sig")
    try:
        document = parse(source, str(path))
        candidate = render(document, execute(document, path))
    except Exception as e:
        print(f"snakedone: {e}", file=sys.stderr)
        return 2

    if diff:
        previous = target.read_text(encoding="utf-8")
        sys.stdout.writelines(
            difflib.unified_diff(
                previous.splitlines(keepends=True),
                candidate.splitlines(keepends=True),
                fromfile=str(target),
                tofile=f"{target} (generated)",
            )
        )
        return 1 if previous != candidate else 0
    else:
        write(target, candidate)
    return 0
