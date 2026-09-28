"""Generate the Snakefile rule fragment for a declared document rule."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from snakemake.exceptions import WorkflowError

from .serialize import _entry, _literal


def make_snakemake_rule(rule, conda_path: Path | None = None, TAB="    "):
    """Return the Snakefile rule text for this declaration."""
    name = rule._name
    if "document" in rule._input:
        raise WorkflowError("input.document is preserved in the rule declaration")
    inputs = [*rule._input._raw_items()]
    if rule._filename is not None:
        document = rule._filename
        inputs.append(("document", document))
        if not name:
            name = _rule_name(Path(document).stem)
    if name:
        lines = [f"rule {name}:"]
    else:
        lines = ["rule:"]
    lines.extend(_block("input", inputs, TAB))
    lines.extend(_block("output", rule._output._raw_items(), TAB))
    lines.extend(_block("log", rule._log._raw_items(), TAB))
    lines.extend(_block("params", rule._params._raw_items(), TAB))
    if rule._threads is not None:
        lines.append(f"{TAB}threads: {rule._threads}")
    lines.extend(_block("resources", rule._resources.items(), TAB))
    if conda_path is not None:
        lines.append(f"{TAB}conda:")
        lines.append(f"{TAB}{TAB}{_literal(str(conda_path))}")
    wildcards = " ".join(
        f"--wildcards {item}={{wildcards.{item}:q}}"
        for item in sorted(rule.wildcard_names())
    )
    parts = ["snakedone", "{input.document:q}"]
    target_document = rule.smk_target_document
    if target_document is not None:
        kind, _ = target_document
        parts.extend(("-o", f"{{{kind}.document:q}}"))
    if wildcards:
        parts.append(wildcards)
    lines.append(f"{TAB}shell:")
    lines.append(f"{TAB}{TAB}{_literal(' '.join(parts))}")
    return "\n".join(lines) + "\n"


def _rule_name(name: str):
    """Replace characters that Snakemake does not accept in a rule name."""
    if re.search(r"[A-Za-z0-9_]", name) is None:
        return "snakedone_document"
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    return "_" + name if name[0].isdigit() else name


def _block(keyword: str, entries: Iterable[tuple], TAB="    "):
    entries = iter(entries)
    for k, v in entries:
        break
    else:
        return
    yield f"{TAB}{keyword}:"
    tab2 = TAB * 2
    yield f"{tab2}{_entry(k, v)}"
    for k, v in entries:
        yield f"{tab2}{_entry(k, v)}"
