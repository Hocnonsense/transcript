"""Execute documents, compare archives, or export recorded content to HTML."""

import argparse
import difflib
import subprocess
import sys
from pathlib import Path

from .document import parse
from .snd import write


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
    if not make_html:
        diff = path == target if args.diff is None else args.diff
        ret = py2snd(path, target, diff)

    # Plain archive export is offline; explicit execution flags still apply.
    else:
        ret = 0
        if path.suffix != ".snd" or args.diff is not None:
            ret = py2snd_subprocess(args, target)
            path = target
        if not ret:
            ret = snd2html(path, target.with_suffix(".html"))
    sys.exit(ret)


def py2snd(path: Path, target: Path, diff: bool = False):
    source = path.read_text(encoding="utf-8-sig")
    try:
        document = parse(source, str(path))
        candidate = document.render_snd(*document.execute(path))
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


def py2snd_subprocess(args, target: Path):
    if args.diff and not target.exists():
        diff = []  # HTML export needs an archive to read.
    else:
        diff = {True: ["--diff"], False: ["--overwrite"], None: []}[args.diff]
    try:
        ret = subprocess.run(
            [
                sys.executable,
                "-c",
                "from snakedone.cli import main; main()",
                args.file,
                *diff,
                "-o",
                str(target),
            ],
            check=False,
        ).returncode
    except OSError as error:
        print(f"snakedone: {error}", file=sys.stderr)
        ret = 2
    if ret < 0:
        ret = 128 - ret
    return ret


def snd2html(path: Path, target: Path):
    source = path.read_text(encoding="utf-8-sig")
    try:
        document = parse(source, str(path))
        candidate = document.render_html(title=path.stem)
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target, candidate)
    except Exception as error:
        print(f"snakedone: {error}", file=sys.stderr)
        return 2
    return 0
