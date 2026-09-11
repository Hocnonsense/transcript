"""Execute documents, compare archives, or export recorded content to HTML."""

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
        "--diff",
        dest="diff",
        action="store_true",
        help="create missing archives; fail on differences",
    )
    group_diff.add_argument(
        "--overwrite",
        dest="diff",
        action="store_false",
        help="force to write or overwrite .snd file",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="export HTML after a successful archive step; .snd alone is read directly",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path; .html selects HTML export, .snd selects the archive name;"
        " other names receive the mode's suffix",
    )
    parser.set_defaults(diff=None)
    return parser


def main(argv: list[str] | None = None):
    parser = get_parser()
    args = parser.parse_args(argv)
    path: Path = args.file.resolve()
    if path.suffix not in (".py", ".snd"):
        parser.error("input must end in .py or .snd")
    make_html = args.html
    if args.output is not None:
        target: Path = args.output.resolve()
        if target.suffix == ".html":
            make_html = True
            target = target.with_suffix(".snd")
        elif target.suffix != ".snd":
            target = target.with_suffix(target.suffix + ".snd")
    else:
        target = path.with_suffix(".snd")
    # Plain archive export is offline; explicit execution flags still apply.
    if not (make_html and path.suffix == ".snd" and args.diff is None):
        if args.diff is None:
            diff = path == target
        else:
            diff = args.diff and not (make_html and not target.exists())
            # to make HTML, force create the snd file, diff make no sense
        ret = main_file(path, target, diff)
        path = target
    else:
        ret = 0
    if make_html and ret == 0:
        ret = html_file(path, target.with_suffix(".html"))
    sys.exit(ret)


def html_file(path: Path, target: Path):
    from .html import render as render_html

    try:
        source = path.read_text(encoding="utf-8-sig")
        document = parse(source, str(path))
        write(target, render_html(document, title=path.stem))
    except Exception as error:
        print(f"snakedone: {error}", file=sys.stderr)
        return 2
    return 0


def main_file(path: Path, target: Path, diff: bool = False):
    source = path.read_text(encoding="utf-8-sig")
    try:
        document = parse(source, str(path))
        candidate = render(document, execute(document, path))
    except Exception as e:
        print(f"snakedone: {e}", file=sys.stderr)
        return 2

    if not target.exists():
        previous = ""
        if not diff:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
    else:
        previous = target.read_text(encoding="utf-8")
    updated = candidate != previous
    if diff:
        sys.stdout.writelines(
            difflib.unified_diff(
                previous.splitlines(keepends=True),
                candidate.splitlines(keepends=True),
                fromfile=str(target),
                tofile=f"{target} (generated)",
            )
        )
        return int(updated)
    elif updated:
        write(target, candidate)
    else:
        target.touch()
    return 0
