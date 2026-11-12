"""Execute documents, compare archives, or export recorded content to HTML."""

import argparse
import difflib
import subprocess
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from .document import parse
from .html import extract as extract_html
from .renderers.label import set_cache
from .review.load import read_source, review_block
from .tmd import write

if TYPE_CHECKING:
    from ._rule.core import Rule

ARCHIVE_SUFFIX = ".tmd.py"


def is_tmd(path: Path):
    """Return whether *path* names an archive (``.tmd.py``)."""
    return path.name.endswith(ARCHIVE_SUFFIX)


def tmd_path(path: Path):
    """Return the archive path for a source, report, or archive *path*."""
    if is_tmd(path):
        return path
    return path.with_suffix(ARCHIVE_SUFFIX)


def tmd_stem(path: Path):
    """The logical stem of an archive: ``demo.tmd.py`` -> ``demo``."""
    if is_tmd(path):
        return path.name[: -len(ARCHIVE_SUFFIX)]
    return path.stem


def output_path(path: Path):
    """Return the archive name for an explicit ``-o`` argument.

    A ``.py`` name is the source form of an archive, so ``-o demo.py`` names
    ``demo.tmd.py`` rather than ``demo.py.tmd.py``. Other names receive the
    archive suffix; an ``.html`` name is left alone because it selects a report.
    """
    if path.suffix == ".html":
        return path
    if is_tmd(path):
        return path
    if path.suffix == ".py":
        return path.with_suffix(ARCHIVE_SUFFIX)
    return path.with_name(path.name + ARCHIVE_SUFFIX)


def html_path(path: Path):
    """Return the report path for an archive (``demo.tmd.py`` -> ``demo.html``)."""
    return path.with_name(tmd_stem(path) + ".html")


def get_parser():
    parser = argparse.ArgumentParser(prog="transcript")
    parser.add_argument(
        "file",
        type=Path,
        help="Python source (.py), archive (.tmd.py), or report (.html)",
    )
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
        help="force to write or overwrite .tmd.py file",
    )
    group_html = parser.add_mutually_exclusive_group()
    group_html.add_argument(
        "--html",
        action="store_true",
        help="force HTML export after a successful archive step",
    )
    group_html.add_argument(
        "--no-html",
        action="store_true",
        help="write only the archive, ignoring a declared .html document",
    )
    parser.add_argument(
        "--wildcards",
        nargs="+",
        metavar="KEY=VALUE",
        help="wildcard value for a declared pattern; may be repeated",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        help="reviewed .tmd.py or .html whose annotations are transferred to the"
        " generated archive; defaults to an existing target .tmd.py",
    )
    parser.add_argument(
        "--snakefile",
        type=Path,
        help="overwrite/create the file with the document's rule",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path; .html selects HTML export, .tmd.py selects the archive name;"
        " other names receive the mode's suffix",
    )
    parser.set_defaults(diff=None)
    return parser


def _parse_wildcards(values, parser: argparse.ArgumentParser):
    result: dict[str, str] = {}
    for item in values or ():
        key, separator, value = item.partition("=")
        if not separator or not key:
            parser.error(f"--wildcards expects KEY=VALUE, got {item!r}")
        result[key] = value
    return result


def html2tmd(html: Path, tmd: Path | None = None, diff: bool | None = None):
    """Handle an exported ``.html`` input by extracting its embedded archive."""
    try:
        source = extract_html(html.read_text(encoding="utf-8-sig"))
    except Exception:
        traceback.print_exc()
        return 2
    tmd = tmd_path(tmd or html)
    return check_exist(tmd, source, diff, tmd.exists())


def main(argv: list[str] | None = None):
    parser = get_parser()
    args = parser.parse_args(argv)
    path: Path = args.file.resolve()
    if path.suffix not in (".py", ".html"):
        parser.error("input must end in .py or .html")
    output: Path | None = args.output
    if output is not None:
        output = output_path(output)
    target = None if output is None else output.resolve()
    if path.suffix == ".html":
        if args.previous is not None:
            parser.error("--previous does not apply to a .html input")
        sys.exit(html2tmd(path, target, args.diff))
    output_html = output is not None and output.suffix == ".html"
    # --no-html always wins.  An archive-only -o suppresses export unless
    # --html explicitly asks for it; force_html and only_tmd are never both
    # true except when -o names the report but --no-html was given.
    force_html = args.html or output_html
    only_tmd = args.no_html or (
        output is not None and not output_html and not args.html
    )
    if is_tmd(path) and force_html and args.diff is None:
        if args.previous is not None:
            parser.error(
                "--previous needs the archive to be regenerated;"
                " use --overwrite (or --diff) together with --html"
            )
        # The archive already exists; only the HTML needs rendering.
        ret, tmd, is_html, executed = 0, path, True, False
    else:
        wildcards = _parse_wildcards(args.wildcards, parser)
        previous = None if args.previous is None else args.previous.resolve()
        ret = py2tmd(path, output, wildcards, previous)
        if isinstance(ret, tuple):
            tmd, candidate, is_html = ret
            ret = check_exist(tmd, candidate, args.diff, path == tmd, force_html)
        executed = True
    if not ret and tmd is not None:
        if not only_tmd and (force_html or is_html):
            html_target = html_path(tmd if target is None else target)
            if executed:
                ret = fresh_tmd2html(tmd, html_target)
            else:
                ret = tmd2html(tmd, html_target)
        if not ret and args.snakefile:
            ret = write_smk(tmd, args.snakefile, args.file)
    sys.exit(ret)


def write_smk(tmd: Path, smk: Path, document_src: Path):
    """Write a Snakefile rule for ``document`` into ``target``.

    The rule is read statically from ``archive``'s canonical block; ``document``
    is the source the rule's ``input.document`` and name are derived from.
    """
    from ._rule.core import Rule

    source = tmd.read_text(encoding="utf-8-sig")
    try:
        job = Rule.from_tmd(source, document_src)
    except Exception:
        traceback.print_exc()
        return 2
    directory = smk.parent
    directory.mkdir(parents=True, exist_ok=True)
    env = job._conda
    if env:
        conda_path = directory / f"{smk.stem}.conda.yaml"
        conda_path.write_text(env.to_yaml(), encoding="utf-8")
    else:
        conda_path = None
    smk.write_text(job.make_snakemake_rule(conda_path), encoding="utf-8")
    return 0


def get_document(job: Rule | None):
    """Resolve the declared document to ``(archive, is_html)``, if any."""
    if job is None:
        return None
    found = job.smk_target_document
    if found is None:
        return None
    _, pattern = found
    resolved = Path(job.resolve(pattern))
    if resolved.suffix == ".html":
        return tmd_path(resolved), True
    return resolved, False


def check_previous(path: Path):
    """Raise when an explicit ``--previous`` no longer matches its body hash.

    A reviewed archive records the hash of its own body in the review marker.
    When the body was edited behind the block's back, its coordinates cannot be
    trusted, so an explicit ``--previous`` refuses to transfer instead of
    silently dropping the annotations.  A ``.html`` previous is rebuilt from its
    islands and never carries a stale hash.
    """
    source = read_source(path)
    if source is not None and source.stale:
        raise ValueError(
            f"{path}: the review block hash does not match its archive body"
            " (edited behind transcript's back?); refusing to transfer annotations"
        )


def py2tmd(
    path: Path,
    output: Path | None,
    wildcards: dict[str, str] | None = None,
    previous: Path | None = None,
):
    """Execute the document, resolve the archive target, and write the archive.

    Returns ``(status, archive, is_html)`` where *is_html* says whether the
    effective target was an ``.html`` document.  The review block is carried
    over explicitly (see :func:`review_block`): ``--previous`` first, else the
    document's own block, else an existing target archive.
    """
    source = path.read_text(encoding="utf-8-sig")
    if previous is not None:
        try:
            check_previous(previous)
        except Exception as error:
            print(f"transcript: {error}", file=sys.stderr)
            return 2
    try:
        document = parse(source, str(path))
        blocks, outputs, job = document.execute(path, wildcards)
        if output is not None:
            if job is not None:
                job.smk_target_document = str(output)
            target = tmd_path(output.resolve())
            html = output.suffix == ".html"
        else:
            found = get_document(job)
            if found is None:
                target, html = tmd_path(path), False
            else:
                target, html = found
        candidate = document.render_tmd(blocks, outputs, job)
        block = review_block(document, target, previous, candidate)
        if block:
            candidate = candidate.rstrip("\n") + "\n\n" + block + "\n"
    except Exception:
        traceback.print_exc()
        return 2
    return target, candidate, html


def check_exist(
    target: Path,
    candidate: str,
    diff: bool | None = None,
    default_diff=True,
    create_missing=False,
):
    if create_missing and not target.exists():
        diff = False  # HTML export needs an archive to read.
    elif diff is None:
        diff = default_diff
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
        return 1 if updated else 0
    elif updated:
        write(target, candidate)
    return 0


def tmd2html(tmd: Path, html: Path):
    source = tmd.read_text(encoding="utf-8-sig")
    previous_cache = set_cache({})
    try:
        document = parse(source, str(tmd))
        candidate = document.render_html(title=tmd_stem(tmd))
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        set_cache(previous_cache)
    html.parent.mkdir(parents=True, exist_ok=True)
    write(html, candidate)
    return 0


def fresh_tmd2html(tmd: Path, html: Path):
    """Render HTML from an archive in a fresh process.

    The document already ran in this process; a child keeps its side effects
    (``os.chdir``, ``sys.modules``, ...) away from the HTML renderer.
    """
    command = [
        sys.executable,
        "-c",
        "from transcript.cli import main; main()",
        str(tmd),
        "-o",
        str(html),
    ]
    try:
        ret = subprocess.run(command, check=False).returncode
    except OSError:
        traceback.print_exc()
        return 2
    return 128 - ret if ret < 0 else ret
