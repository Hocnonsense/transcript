snakedone
=========

`snakedone` turns a Python file into a document that records the output of its report blocks into an archive (`.snd`) and exports it as a standalone HTML report with Markdown docstrings.

## Installation

Requires Python ≥3.11.
Install from the repository root:

```bash
python -m pip install -e .
# Optional HTML renderer:
python -m pip install -e '.[html]'
# Optional extras (each includes the HTML renderer):
python -m pip install -e '.[datavzrd]'   # interactive Datavzrd tables
python -m pip install -e '.[vegalite]'   # Vega-Lite charts
python -m pip install -e '.[snakemake]'  # Snakemake rule declarations
```

Install pandas or polars separately for the DataFrames used by your document.

## Usage

```bash
snakedone examples/demo.py                 # create or replace the archive
snakedone examples/demo.py --diff          # compare against the archive
snakedone examples/demo.snd                # execute the archive and compare
snakedone examples/demo.snd --overwrite    # execute and update in place
```

In brief, use `-o` / `--output` to choose another destination. `--diff` never updates an existing archive; `--overwrite` updates the resolved target.
`.py` files are never modified, and an archived `.snd` can be used in place of the original `.py`.

The [demo](examples/demo.py) reads the adjacent `data.json` and records text, a DataFrame table, RGB data, and images.

### Archive generation and comparison

With the default output path (no `-o` and no rule-declared [document redirection](#output-redirection)):

| Mode          | `.py` input                          | `.snd` input           |
| ------------- | ------------------------------------ | ---------------------- |
| `--diff`      | Compare against the sibling `.snd`   | Compare against itself |
| Default       | Create or replace the sibling `.snd` | Compare against itself |
| `--overwrite` | Create or replace the sibling `.snd` | Update in place        |

`--diff` executes the input, prints a unified diff when recorded outputs differ, and is mutually exclusive with `--overwrite`.

Without `-o` / `--output` given, execution writes the target when it differs from the input path and compares when they are the same.
A document whose rule declares `output.document` or `log.document` uses that target instead whenever the input executes, so a re-executed `.snd` can write a different target than the input archive.

### HTML export

```bash
snakedone examples/demo.snd --html                # export stored results without executing
snakedone examples/demo.py --html                 # execute, write report.snd, export report.html
snakedone examples/demo.py -o report.html         # an .html output path also selects export
snakedone examples/demo.py --diff -o report.html  # create/compare before exporting
```

`--html` or an `.html` output suffix selects HTML export; `--no-html` forces archive-only and ignores a declared `.html` document.
With neither flag, HTML is exported when the effective target is `.html`, that is an `.html` output path or a `.html` document [declared by a rule](#output-redirection).
A `.snd` input with neither `--diff` nor `--overwrite` is read directly; all other combinations execute the input first and export only after successful archive generation or comparison.
In HTML mode, `--diff` creates a missing target archive instead of comparing against empty text; differences in an existing archive prevent export.

`-o` / `--output` determines both the archive and report names.
An `.html` or `.snd` suffix selects their shared basename; other names receive the appropriate suffix.
For a rule-declared document, `-o` is reconciled with the recorded target as described in [Output redirection](#output-redirection).

See [HTML reports](#html-reports) for rendering details.

### Exit codes

- `0`: succeeded.
- `1`: comparison found differences, or an uncaught archive file I/O error occurred, such as a missing input file.
- `2`: invalid arguments, document parsing or execution errors, or HTML input/output or rendering errors.

## Document syntax

### Conventions

Write a report block at module level using either entry point:

```python
value = 7

if "snakedone":
    """
    # Analysis
    """
    value
```

- `if "snakedone":` is always true, so the file runs with plain Python and needs no dependency.
- `with snakedone.report:` runs a real context manager and requires `import snakedone`.

The two entries are equivalent and may be mixed in one document.
A top-level `with` is a report block when its context manager is the `report` imported from `snakedone`; any alias works.

Inside a block:

- The first docstring is the block's Markdown; a block may consist of Markdown alone.
- A non-string expression statement runs and echoes its value like a REPL (`repr`, or a rich output for recorded values), including an f-string.
- Any other statement (assignment, `import`, `for`, `if`, `try`, …) runs normally; its stdout is collected as one unit, so a loop prints all of its output into a single slot.
- The stdout of each statement is written to a docstring directly below it on every run.

### Example

Save the following as `analysis.py`:

```python
value = 7

if "snakedone":
    """
    # Analysis
    """
    value
    value = "updated"
    value
    for number in [1, 2]:
        print(number)
```

Running `snakedone analysis.py` produces this complete `analysis.snd`:

```python
value = 7

if "snakedone":
    """
    # Analysis
    """
    value
    """
    7
    """
    value = "updated"
    value
    """
    'updated'
    """
    for number in [1, 2]:
        print(number)
    """
    1
    2
    """
```

## Execution semantics

snakedone captures each top-level statement's output and writes it back into the block's output docstrings.
Running the file with plain Python executes the blocks but does not echo bare expressions or update docstrings.
Unhandled execution errors prevent archive writes, leaving an existing archive intact.

## HTML reports

Reports follow source order, alternating script code and report blocks.
Markdown docstrings are rendered as Markdown, including headings, lists, links, fenced code, and tables.
Script code starts collapsed and occupies no height in the document flow.

CSV and other text outputs retain their original formatting.
Use `image()` or `bitmap()` for embedded bitmap data, and Markdown image links render as online images.
Text, images, and explicitly selected rich outputs appear in their recorded order within the same output section.
Rendering reads the archive without executing Python.

Wrap generated Markdown in `Markdown` when an expression's value should be rendered as document Markdown instead of plain text:

```python
from snakedone import Markdown

if "snakedone":
    Markdown("## Generated result\n\n- first\n- second")
```

### Bitmap images

Use `bitmap()` to snapshot a PNG, JPEG, GIF, or WebP path, bytes, or binary IO object into the archive:

```python
from snakedone import bitmap

if "snakedone":
    bitmap("result.png", alt="Simulation result")
```

`image()` accepts all of the same static bitmap sources, and additionally accepts a Matplotlib `Figure`, `Axes`, artist, or the artist list returned by `plt.plot()`.

```python
import matplotlib.pyplot as plt

from snakedone import image

plot = plt.plot([0, 1, 2], [0, 1, 0])

if "snakedone":
    image(plot, alt="A line plot")
```

### Datavzrd tables

Wrap a pandas or polars `DataFrame` to render it as an interactive [Datavzrd](https://datavzrd.github.io/) table in the HTML report:

```python
import pandas as pd

from snakedone import datavzrd

frame = pd.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})

if "snakedone":
    """
    ## Interactive table
    """
    datavzrd(frame, {"views": {"results": {"dataset": "data"}}})
```

`datavzrd(frame, config)` records a snapshot of the data as CSV plus the Datavzrd configuration in the archive.
`config` may be a mapping or a YAML filename, resolved against the current working directory; when omitted, a single table view named `results` is created.
Every view must use the managed dataset `data`; snakedone supplies the data path itself, so no intermediate files are kept.
A single-view configuration opens that table directly instead of Datavzrd's overview page; multiple views show the overview unless `default-view` selects one.

To configure column plots, save this as `table.yaml` next to your document and use `datavzrd(frame, "table.yaml")`:

```yaml
views:
  results:
    dataset: data
    render-table:
      columns:
        score:
          plot:
            bars:
              scale: linear
              domain: [0, 1]
```

The [pandas and polars example](examples/datavzrd_demo.py) uses a shared [YAML configuration](examples/datavzrd.yaml) with column bars, a heatmap, and two views of the same dataset.
HTML export runs the `datavzrd` executable once per distinct recorded snapshot and embeds the generated report into the single HTML file, so sorting, filtering, paging, and built-in plots keep working offline.
If configuration validation or rendering fails, HTML export reports an error and preserves any existing HTML file.

### Vega-Lite charts

Wrap a [Vega-Lite](https://vega.github.io/vega-lite/) chart from [Altair](https://altair-viz.github.io/) with `vegalite()` to record its specification and data:

```python
import altair as alt
import pandas as pd

frame = pd.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})
chart = (
    alt.Chart(frame)
    .mark_bar()
    .encode(
        x="sample:N",
        y="score:Q",
        tooltip=["sample:N", "score:Q"],
    )
)

if "snakedone":
    """
    ## Altair chart
    """
    vegalite(chart)
```

snakedone snapshots the chart's Vega-Lite specification and data, so the archive does not depend on the original DataFrame.

HTML export inlines a static SVG preview with `vl-convert`, so the report stays a single offline file.
Online, the preview is upgraded to an interactive chart by default; pass `offline=True` to keep a pure static SVG.

Alternatively, `vegalite(config, data=None)` accepts a custom Vega-Lite configuration and optional pandas or polars data. See the [custom configuration and data example](examples/vegalite_demo.py).

### Labelled outputs

Wrap a value or a rich output with `label(value, id, caption="")` to give it a stable document anchor and an optional caption:

```python
from snakedone import Markdown, label

measurements = {"sample": "A", "score": 0.8, "passed": True}

if "snakedone":
    """
    See the [measurements](#table.1) and the
    [quality decision](#sample-a-decision).
    """
    label(Markdown("## Decision\n\nSample A passed."), "sample-a-decision")
    label(datavzrd(measurements, config), "table.1", "table.1 Sample A measurements")
```

`id` must be a valid snakedone id (a letter followed by letters, digits, `_`, `.`, `:` or `-`).
The label renders as a `<figure>` carrying that `id`, so ordinary Markdown links jump to it and the caption becomes a `<figcaption>`.
A non-renderer Python value is wrapped with the built-in `code` renderer, which shows the value as a bare expression.
If an `id` is reused for different archived content, the exporter warns, appends a numeric suffix to make the label unique, and notes the duplicate in its caption.

## Snakemake rules

A document can declare rule like in Snakemake that generates its archive or report, so a Snakefile can manage its input and output with wildcards (this requires the `snakemake` extra).
Declarations live in a single `with snakedone.rule() as r:` block (the "rule block") at the top of the document:

```python
import snakedone

with snakedone.rule("demo_report") as r:
    r.input(
        a="{sample}.tsv",
        b="{sample}.yaml",
    )
    r.output(
        "report/{sample}.tsv",
    )
    r.log(
        document="{sample}.html",
    )
    r.params(
        seed=1,
        prefix="{sample}-",
    )
    r.threads = 4
    r.resources(
        mem_mb=8000,
        runtime="2h",
    )
    r.conda(
        dependencies=["pandas=*"],
        pip=["snakemake"],
    )
r.wildcards(sample="boo")
```

### Directives declaration

A document has at most one rule block. `snakedone.rule()` may be called only once; add further declarations to the object it returns.
`input`, `output`, `log`, `params`, and `threads` declarations may also be scattered outside the block.
Declarations made through `r.input` / `r.output` / `r.log` / `r.params` are merged into the canonical declaration and returned resolved; for `input`, `output`, and `log` the result is a `Path`.
For example:

```python
with snakedone.rule("demo_report") as r:
    r.input(
        a="{sample}.tsv",
        b="{sample}.yaml",
    )
    r.params(
        seed=1,
        prefix="{sample}-",
    )
r.input.a  # raises because wildcard `sample` is unknown.
# once a pattern is matched, the wildcards update and the same value may be set repeatedly.
(b,) = r.input("boo.yaml")
assert b == Path("boo.yaml")  # the returned value is resolved as a path.
assert r.input.a == Path("boo.tsv")  # wildcards now apply to every declaration.
r.params.prefix = "haa-"  # raises: wildcard `haa` mismatches the previous `boo`.
r.params.seed = 2  # raises: value does not match the declared pattern.
# neither conflicts nor matches, so it is registered and written to the archive.
r.params.seed2 = 2
```

A concrete literal declared outside the block is inferred using script-side wildcard values only.
It is first matched against the patterns already in its own list; a match records the captured wildcards and stores the pattern.
Otherwise the literal is reverse-substituted with the `r.wildcards()` defaults and inferred captures; a value that cannot be rewritten is kept as written.
A later same-list pattern that would rewrite an already-accepted literal is an error; declare the pattern first, or put the fixed literal inside the block.
Declaring a default with `r.wildcards()` is the one point where existing literals are upgraded to patterns; a default that contradicts an inferred value is an error.
`output` and `log` must use the same wildcard set; the other lists may use a subset.

### Dynamic supports

Only literal values can be recorded; `lambda` functions declared inside the rule block are the exception.
`r.conda(dependencies=..., pip=..., channels=...)` declares the conda environment (rule block only): `dependencies` and `pip` become dependencies (the latter as a `pip:` sublist), and `channels` defaults to `conda-forge`.
`r.resources(**values)` is also rule-block only and is validated by Snakemake's resource mechanism.
Values remain statically readable: ordinary paths, `conda` values, and ordinary `params` round-trip through `repr` and `ast.literal_eval`.
`input` accepts a self-contained `lambda wildcards: ...`, and `params` accepts self-contained lambdas with Snakemake auxiliary parameters:

```python
r = snakedone.rule()
with r:
    r.params(
        selected=lambda wildcards, input: [
            path for path in input if wildcards.sample in path
        ],
    )
    r.input(table=lambda wildcards: f"results/{wildcards.sample}.tsv")
```

The first positional parameter must be `wildcards`, matching Snakemake's auxiliary-parameter convention.
Lambdas may use normal Python expressions, including calls and comprehensions; global or closure names, `:=`, nested lambda, and `*args`/`**kwargs` are rejected.
Defaults, when present, must be literals.
Snakemake's optional input-function `groupid` has no equivalent outside a group job and is not accepted yet.
Other functions and custom objects are not supported.

### Runtime wildcards

Same to Snakemake, wildcards are named `{placeholders}` in `input`/`output`/`log` patterns; defaults are declared once with `r.wildcards(sample="boo")`.
Read the effective value with `r.wildcards.sample` (or `r.wildcards["sample"]`); like pattern resolution it reflects declared defaults, inferred captures, and `--wildcards` overrides, and an unknown name raises `WildcardError`.
Assigning a concrete literal outside the block infers its pattern from the script-side wildcard values, so `r.output.report = "boo-1.tsv"` is recorded as `"{sample}-1.tsv"`.

Pass `--wildcards KEY=VALUE` (repeatable) to `snakedone` to override the effective values for a single execution.
Every declared pattern and the declared document target then resolve with the override, so `--wildcards sample=B` turns `"{sample}-1.tsv"` into `"B-1.tsv"`.
This is how the generated Snakefile rule forwards Snakemake's wildcard values.
The override never changes the defaults stored in the archive; without `--wildcards`, the next run uses the recorded defaults.

### Output redirection

An optional `output.document` or `log.document` marks the document's final `.snd` or `.html` target.
It must be declared inside the rule block (for example `r.output(document="{sample}.html")`); declaring both is an error, and any other suffix is rejected.

The archive target is chosen in this order:

1. `-o`/`--output` has the highest priority. The archive is written there, and the recorded `document` is reconciled with it:
   - if the `-o` value can be converted to a pattern with the current wildcards values, the existing `output.document` (or else `log.document`, or else a new `output.document`) records that pattern, so repeated wildcards runs stay stable;
   - otherwise the concrete `-o` cannot avoid overwriting, so any existing `document` is dropped.
2. Without `-o`, a declared `document` from the rule block is resolved with the effective wildcards and used.
3. Otherwise the archive falls back to the document's sibling `<stem>.snd` (or the `.snd` itself when the input already is an archive).

A declared `.html` document makes the effective target `.html`, which selects HTML export; see [HTML export](#html-export) for how `--html` and `--no-html` override this.

The target follows the rule, not the input filename.
An archive created with `-o` records the reconciled `document` pattern but neither the concrete name nor the `--wildcards` values, so re-executing it without `--wildcards` falls back to the recorded defaults.
For example, the [rule demo](examples/rule_demo.py) declares `r.wildcards(sample="A", feature="score")`:

| input file              | parameter                                                      | files changed on disk                               | behavior                                                                                                             |
| ----------------------- | -------------------------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `examples/rule_demo.py` | `-o rule_demo-B-count.html --wildcards sample=B feature=count` | writes `rule_demo-B-count.snd/.html`                | adds `document="rule_demo-{sample}-{feature}.html"` to the document.                                                 |
| `rule_demo-B-count.snd` |                                                                | writes `rule_demo-A-score.snd/.html`, not B-count   | executes the archive and resolves the declared document with the recorded defaults (A/score).                        |
| `rule_demo-B-count.snd` | `--diff`                                                       |                                                     | compares that re-execution against `rule_demo-A-score.snd`, not the input archive; exit 1 if missing target.         |
| `rule_demo-B-count.snd` | `--overwrite --html`                                           | creates/overwrites `rule_demo-A-score.snd/.html`    | similar to above                                                                                                     |
| `rule_demo-B-count.snd` | `--diff --html`                                                | create/check `rule_demo-A-score.snd`, write `.html` | creates a missing target archive, a difference against an existing archive still blocks export.                      |
| `rule_demo-B-count.snd` | `--html`                                                       | renders `rule_demo-B-count.html`                    | renders the stored results directly without executing, so this one keeps the input name.                             |
| `rule_demo-B-count.snd` | `--overwrite -o examples/rule_demo.html`                       | writes `examples/rule_demo.snd/.html`               | the concrete `-o` cannot become a pattern, so the declared `document` is dropped; execution uses defaults (A/score). |
| `rule_demo-B-count.snd` | `--overwrite --html --wildcards sample=B feature=count`        | rewrites `rule_demo-B-count.snd/.html`              | re-executes with an explicit override and reproduces the B-count target.                                             |

`input.document` is reserved for the document's own path; a user-declared `input.document` is rejected.

### Rule extraction

An explicit rule name must match `[A-Za-z_][A-Za-z0-9_]*` and is rejected otherwise.
The default document stem is normalized instead: invalid characters are replaced
with `_`, and a leading digit is prefixed with `_`.

`snakedone report.py --snakefile Snakefile` writes the matching Snakefile rule into
the target and `<target stem>.conda.yaml` next to it:
```python
rule report:
    input:
        a="{sample}.tsv",
        b="{sample}.yaml",
        document="report.py",
    output:
        document="{sample}.html",
    log:
        "logs/{sample}.log",
    params:
        seed=1,
    threads: 4
    resources:
        mem_mb=8000,
        runtime="2h",
    conda: "Snakefile.conda.yaml"
    shell:
        "snakedone {input.document:q} -o {output.document:q} --wildcards sample={wildcards.sample:q}"
```

The `.html` suffix passed through `-o` selects HTML export.

## Development

The Pixi development environment includes the HTML renderer, Datavzrd, Vega-Lite (via `vl-convert`), pandas, and polars, and targets Linux x86-64 and Python 3.14.
From the repository root:

```bash
pixi install
pixi run check
```

`pixi run check` runs pytest, Ruff, and Pyright.
Use `pixi run format` to format the code.

### Terminology

```text
report-block
├── markdown
└── code-output pair
    ├── code
    └── output slot
```

| Term           | Meaning                                                            |
| -------------- | ------------------------------------------------------------------ |
| `report-block` | A module-level `if "snakedone":` or `with snakedone.report:` block |
| `markdown`     | The first docstring inside the block                               |
| `code`         | A top-level statement that runs and may produce output             |
| `output slot`  | A docstring after a code statement, replaced on each update        |

### Rich output convention

Each `snakedone-output` fenced block represents one output item, so an output slot can mix ordinary text, images, and rich outputs.
The wrapper writes this block automatically when displayed as a bare expression or passed to `print()`.
The fence header names the renderer and may pin a version constraint; the body is the renderer's serialized data:

````text
```snakedone-output datavzrd=1
{
  "config": {
    "default-view": "results",
    "views": {"results": {"dataset": "data"}}
  },
  "csv": "sample,score\nA,0.8\nB,0.3\n"
}
```
````

A `RecordedOutput` carries the renderer-serialized `data` string, the renderer that produced it, and any nested `children`; its `text` is the snd fence while the document executes and the HTML that fills the report slot once the archive is rendered.
Each renderer defines, serializes (`to_snd`), validates, and renders (`to_html`) its own data format; `to_html` returns a `RecordedOutput`, and Datavzrd stores JSON with CSV text and the effective configuration, including loaded YAML contents.
A block body may itself contain `snakedone-output` blocks (as `label` does): the exporter renders each child once, gives it its own report id and file namespace, and substitutes it for the parent's `{{i}}` placeholder, so nested renderers keep separate styles, runtimes, and report files.
Nested outputs are recursively converted into reports, and browser assets are collected once per renderer name.
Renderer styles and runtimes share the exported document. Renderers should use renderer-specific CSS classes, avoid modifying generic document selectors or global JavaScript state, and must not depend on renderer resource loading order.

The header constraint is compared with the installed renderer version, so `datavzrd=1`, `datavzrd>=1`, and `datavzrd<2` are accepted forms.
Blocks that name an unknown renderer, declare an unsupported version, or cannot be validated remain readable as plain text and emit a warning instead of failing the export.
Older blocks without a renderer in the header are kept as plain text; regenerate the archive with `--overwrite` to use the versioned fence.
Do not hand-edit generated output slots to select a renderer: execution replaces recorded outputs, so make that choice in the code.
