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
from .snd import write

if TYPE_CHECKING:
    from ._rule import Rule


def get_parser():
    parser = argparse.ArgumentParser(prog="snakedone")
    parser.add_argument(
        "file", type=Path, help="Python source (.py), archive (.snd), or report (.html)"
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
        help="force to write or overwrite .snd file",
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
        "--snakefile",
        type=Path,
        help="overwrite/create the file with the document's rule",
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


def _parse_wildcards(values, parser: argparse.ArgumentParser):
    result: dict[str, str] = {}
    for item in values or ():
        key, separator, value = item.partition("=")
        if not separator or not key:
            parser.error(f"--wildcards expects KEY=VALUE, got {item!r}")
        result[key] = value
    return result


def html2snd(html: Path, snd: Path | None = None):
    """Handle an exported ``.html`` input by extracting its embedded archive."""
    try:
        source = extract_html(html.read_text(encoding="utf-8-sig"))
    except Exception:
        traceback.print_exc()
        return 2
    snd = snd or html.with_suffix(".snd")
    if snd.suffix != ".snd":
        snd = snd.with_suffix(".snd")
    snd.parent.mkdir(parents=True, exist_ok=True)
    write(snd, source)
    return 0


def main(argv: list[str] | None = None):
    parser = get_parser()
    args = parser.parse_args(argv)
    path: Path = args.file.resolve()
    if path.suffix not in (".py", ".snd", ".html"):
        parser.error("input must end in .py, .snd or .html")
    output: Path | None = args.output
    if output is not None and output.suffix not in (".snd", ".html"):
        output = output.with_suffix(output.suffix + ".snd")
    target = None if output is None else output.resolve()
    if path.suffix == ".html":
        sys.exit(html2snd(path, target))
    output_html = output is not None and output.suffix == ".html"
    # force_html and only_snd MAY both False if output is None, but never both True.
    force_html = args.html or output_html
    only_snd = args.no_html or (output is not None and not output_html)
    if path.suffix == ".snd" and force_html and args.diff is None:
        # The archive already exists; only the HTML needs rendering.
        ret, snd, is_html, executed = 0, path, True, False
    else:
        wildcards = _parse_wildcards(args.wildcards, parser)
        ret, snd, is_html = py2snd(path, output, args.diff, wildcards, force_html)
        executed = True
    if not ret and snd is not None:
        if not only_snd and (force_html or is_html):
            html_target = (
                snd.with_suffix(".html")
                if target is None
                else target.with_suffix(".html")
            )
            if executed:
                ret = fresh_snd2html(snd, html_target)
            else:
                ret = snd2html(snd, html_target)
        if not ret and args.snakefile:
            ret = write_smk(snd, args.snakefile, args.file)
    sys.exit(ret)


def write_smk(snd: Path, smk: Path, document_src: Path):
    """Write a Snakefile rule for ``document`` into ``target``.

    The rule is read statically from ``archive``'s canonical block; ``document``
    is the source the rule's ``input.document`` and name are derived from.
    """
    from ._rule import Rule

    source = snd.read_text(encoding="utf-8-sig")
    try:
        job = Rule.from_snd(source, document_src)
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
        return resolved.with_suffix(".snd"), True
    return resolved, False


def py2snd(
    path: Path,
    output: Path | None,
    diff: bool | None = None,
    wildcards: dict[str, str] | None = None,
    create_missing: bool = False,
):
    """Execute the document, resolve the archive target, and write the archive.

    Returns ``(status, archive, is_html)`` where *is_html* says whether the
    effective target was an ``.html`` document.
    """
    source = path.read_text(encoding="utf-8-sig")
    try:
        document = parse(source, str(path))
        blocks, outputs, job = document.execute(path, wildcards)
        if output is not None:
            if job is not None:
                job.smk_target_document = str(output)
            target = output.resolve().with_suffix(".snd")
            html = output.suffix == ".html"
        else:
            found = get_document(job)
            if found is None:
                target, html = path.with_suffix(".snd"), False
            else:
                target, html = found
        candidate = document.render_snd(blocks, outputs, job)
    except Exception:
        traceback.print_exc()
        return 2, None, False
    if create_missing and not target.exists():
        diff = False  # HTML export needs an archive to read.
    elif diff is None:
        diff = path == target

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
        return int(updated), target, html
    elif updated:
        write(target, candidate)
    else:
        target.touch()
    return 0, target, html


def snd2html(snd: Path, html: Path):
    source = snd.read_text(encoding="utf-8-sig")
    previous_cache = set_cache({})
    try:
        document = parse(source, str(snd))
        candidate = document.render_html(title=snd.stem)
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        set_cache(previous_cache)
    html.parent.mkdir(parents=True, exist_ok=True)
    write(html, candidate)
    return 0


def fresh_snd2html(snd: Path, html: Path):
    """Render HTML from an archive in a fresh process.

    The document already ran in this process; a child keeps its side effects
    (``os.chdir``, ``sys.modules``, ...) away from the HTML renderer.
    """
    command = [
        sys.executable,
        "-c",
        "from snakedone.cli import main; main()",
        str(snd),
        "-o",
        str(html),
    ]
    try:
        ret = subprocess.run(command, check=False).returncode
    except OSError:
        traceback.print_exc()
        return 2
    return 128 - ret if ret < 0 else ret
