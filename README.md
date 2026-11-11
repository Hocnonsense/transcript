transcript
=========

`transcript` turns a Python file into an executable document.
It records report-block output in a `.tmd.py` archive and can export that archive as a single HTML report with rendered Markdown.

## Installation

Requires Python ≥3.11.
Install from the repository root:

```bash
python -m pip install -e .
# Optional HTML renderer:
python -m pip install -e '.[html]'
# Optional feature extras:
python -m pip install -e '.[datavzrd]'   # Datavzrd snapshot support
python -m pip install -e '.[vegalite]'   # Vega-Lite charts
python -m pip install -e '.[snakemake]'  # Snakemake rule declarations
```

Datavzrd HTML export also requires the `datavzrd` executable on `PATH`, for example from `conda install -c conda-forge datavzrd`.

## Usage

```bash
transcript examples/demo.py                 # create or replace the archive
transcript examples/demo.py --diff          # compare against the archive
transcript examples/demo.tmd.py                # execute the archive and compare
transcript examples/demo.tmd.py --overwrite    # execute and update in place
```

In brief, use `-o` / `--output` to choose another destination. `--diff` never updates an existing archive; `--overwrite` updates the resolved target.
`.py` files are never modified, and an archived `.tmd.py` can be used in place of the original `.py`.

The [demo](examples/demo.py) reads the adjacent `data.json` and records text, a DataFrame table, RGB data, and images.

### Archive generation and comparison

With the default output path (no `-o` and no rule-declared [document redirection](#output-redirection)):

| Mode          | `.py` input                             | `.tmd.py` input        |
| ------------- | --------------------------------------- | ---------------------- |
| `--diff`      | Compare against the sibling `.tmd.py`   | Compare against itself |
| Default       | Create or replace the sibling `.tmd.py` | Compare against itself |
| `--overwrite` | Create or replace the sibling `.tmd.py` | Update in place        |

`--diff` executes the input, prints a unified diff when recorded outputs differ, and is mutually exclusive with `--overwrite`.

Without `-o` / `--output`, execution writes the target when it differs from the input path and compares when they are the same.
A document whose rule declares `output.document` or `log.document` uses that target instead whenever the input executes, so a re-executed `.tmd.py` can write a different target than the input archive.

### HTML export

```bash
transcript examples/demo.tmd.py --html                # export stored results without executing
transcript examples/demo.py --html                 # execute, write demo.tmd.py, export demo.html
transcript examples/demo.py -o report.html         # an .html output path also selects export
transcript examples/demo.py --diff -o report.html  # create/compare before exporting
```

`--html` or an `.html` output suffix selects HTML export; `--no-html` forces archive-only and ignores a declared `.html` document.
With neither flag, HTML is exported when the effective target is `.html`, that is an `.html` output path or a `.html` document [declared by a rule](#output-redirection).
A `.tmd.py` input with neither `--diff` nor `--overwrite` is read directly; all other combinations execute the input first and export only after successful archive generation or comparison.
In HTML mode, `--diff` creates a missing target archive instead of comparing against empty text; differences in an existing archive prevent export.

`-o` / `--output` determines both the archive and report names.
`-o report.html` writes `report.tmd.py` and `report.html`; `-o report.tmd.py` selects the archive name; other names receive the `.tmd.py` suffix.
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

if "transcript":
    """
    # Analysis
    """
    value
```

- `if "transcript":` is always true, so the file runs with plain Python and needs no dependency.
- `with transcript.report:` runs a real context manager and requires `import transcript`.

The two forms are equivalent and may be mixed in one document.
A top-level `with` is a report block when its context manager is the `report` imported from `transcript`; any alias works.

Inside a block:

- The first docstring is the block's Markdown; a block may consist of Markdown alone.
- A non-string expression statement runs and echoes its value like a REPL (`repr`, or a rich output for recorded values), including an f-string.
- Any other statement (assignment, `import`, `for`, `if`, `try`, …) runs normally; its captured output is collected as one unit, so a loop writes all of its output into a single slot.
- Each statement's captured output is written to a docstring directly below it on every run.

### Example

Save the following as `analysis.py`:

```python
value = 7

if "transcript":
    """
    # Analysis
    """
    value
    value = "updated"
    value
    for number in [1, 2]:
        print(number)
```

Running `transcript analysis.py` produces this complete `analysis.tmd.py`:

```python
value = 7

if "transcript":
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

transcript captures each top-level statement's output and writes it back into the block's output docstrings.
Running the file with plain Python executes the blocks but does not echo bare expressions or update docstrings.
Unhandled execution errors prevent archive writes, leaving an existing archive intact.

## HTML reports

Reports follow source order, alternating script code and report blocks.
The page renders Markdown docstrings and highlights Python in the browser from the embedded archive.
On first use it downloads pinned browser libraries for Markdown, syntax highlighting, and review diffs from jsDelivr and stores them in a browser cache.
An internet connection is therefore required only while those assets are not cached.
Script code starts collapsed and can be revealed with its adjacent toggle.

CSV and other text outputs retain their original formatting.
Use `image()` or `bitmap()` for embedded bitmap data; HTTP(S) image links in Markdown remain external images.
Text, images, and explicitly selected rich outputs appear in their recorded order within the same output section.
Rendering reads the archive without executing Python.

Markdown blocks and `markdown()` outputs can be reviewed in place: select text, then click the floating `✎` button to propose an edit, leave a comment, or do both.
Edits and comments can be transferred across document revisions; when an annotated range is superseded, its old source is retained to show the diff.
Each annotated range has an outlined box and a badge that opens its revision record list.
The list shows the reviewed window from oldest to newest, with one row per source version and one per review.
A boundary timestamp separates successive source versions; each source row has a colored line on the left, and its associated edits and highlights use the same color.
Every review row has a delete `×`; reviews that are not superseded also have an edit `✎`.

### Embedded source

Exported page embeds the archive it was generated from.
The **Export .tmd.py** button downloads the embedded archive body with the current annotations appended.
The **Save .html** button instead downloads a copy of the page containing the current annotations.
Passing that saved `.html` back to `transcript` extracts the body and annotations into a `.tmd.py` file:

```bash
transcript report.html               # (over)write report.tmd.py next to the page
transcript report.html -o copy.tmd.py   # write copy.tmd.py instead
```

The `.tmd.py` suffix is always used; an `.html` input never executes and never renders a new page.
Both `--diff` and `--overwrite` work for this extraction; when the target `.tmd.py` already exists, the default is `--diff`.

### Transferring annotations

`transcript` transfers annotations onto a freshly generated archive by diffing the old and new bodies.
Old source versions and reviews remain in the history, while new source versions link back to the regions they replaced.
That link is stored as one `span@timestamp` string in the source's optional `cover`; a review's derived `coveredAt` array records the superseded subranges in the same form and omits ranges that are still live.
The reference is chosen in this order: an explicit `--previous`, else the document's own review block, else an already existing target archive.

- `transcript document.py --overwrite` transfers the block from the existing `document.tmd.py` automatically.
- `transcript document.py --overwrite --previous reviewed.tmd.py` takes it from another archive. An explicit `--previous` wins over the input's own review block, so it also overrides a stale or regenerated one; it does not apply to a `.html` input.
- `--previous reviewed.html` takes it from a page's body plus the annotations in its reviews island.

Use `--diff` instead of `--overwrite` to inspect the migrated archive before writing it.
The block's marker records a hash of the body before it. An archive that was hand-edited behind the block's back no longer matches, so an implicit transfer drops the annotations (with a warning), and an explicitly given `--previous` with a stale hash is refused with an error instead of writing anything.

Try the demo with `pixi run demo-review`: `examples/review_demo.py` is one revision with live annotations only, and `examples/review_history.py` reviews a configuration block across revisions, so some of its annotations are now fully or partly superseded.

### Rich outputs

Wrap generated Markdown in `markdown` when an expression's value should be rendered as document Markdown instead of plain text:

```python
from transcript import markdown

if "transcript":
    markdown("## Generated result\n\n- first\n- second")
```

### Bitmap images

Use `bitmap()` to snapshot a PNG, JPEG, GIF, or WebP path, bytes, or binary file-like object into the archive:

```python
from transcript import bitmap

if "transcript":
    bitmap("result.png", alt="Simulation result")
```

`image()` accepts all of the same static bitmap sources, and additionally accepts a Matplotlib `Figure`, `Axes`, artist, or the artist list returned by `plt.plot()`.

```python
import matplotlib.pyplot as plt

from transcript import image

plot = plt.plot([0, 1, 2], [0, 1, 0])

if "transcript":
    image(plot, alt="A line plot")
```

### tables

Use `table()` to render a pandas or polars `DataFrame` as a basic GitHub-flavored Markdown table:

```python
import pandas as pd

from transcript import table

frame = pd.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})

if "transcript":
    """
    ## Results
    """
    table(frame)
```


Wrap a pandas or polars `DataFrame` to render it as an interactive [Datavzrd](https://datavzrd.github.io/) table in the HTML report:

```python
import pandas as pd

from transcript import datavzrd

frame = pd.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})

if "transcript":
    """
    ## Interactive table
    """
    datavzrd(frame, {"views": {"results": {"dataset": "data"}}})
```

`datavzrd(frame, config)` records a snapshot of the data as CSV plus the Datavzrd configuration in the archive.
`config` may be a mapping or a YAML filename, resolved against the current working directory.
When `config` is omitted, a single view named `results` is recorded and Datavzrd renders it with its own defaults (it detects column types from the data).
Every view must use the managed dataset `data`; transcript supplies the data path itself, so no intermediate files are kept.
A single-view configuration opens that table directly instead of Datavzrd's overview page; multiple views show the overview unless `default-view` selects one.

To configure column plots, save this as `table.yaml` in the working directory and use `datavzrd(frame, "table.yaml")`:

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

The [pandas and polars example](examples/table_demo.py) uses a shared [YAML configuration](examples/datavzrd.yaml) with column bars, a heatmap, and two views of the same dataset.
HTML export runs the `datavzrd` executable once per distinct recorded snapshot and embeds the generated report into the single HTML file, so sorting, filtering, paging, and built-in plots keep working offline.
If configuration validation or rendering fails, HTML export reports an error and preserves any existing HTML file.

### Vega-Lite charts

Wrap a [Vega-Lite](https://vega.github.io/vega-lite/) chart from [Altair](https://altair-viz.github.io/) with `vegalite()` to record its specification and data:

```python
import altair as alt
import pandas as pd

from transcript import vegalite

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

if "transcript":
    """
    ## Altair chart
    """
    vegalite(chart)
```

transcript snapshots the chart's Vega-Lite specification and data, so the archive does not depend on the original DataFrame.

HTML export inlines a static SVG preview with `vl-convert`, so the report stays a single offline file.
Online, the preview is upgraded to an interactive chart by default; pass `offline=True` to keep a pure static SVG.

Alternatively, `vegalite(config, data=None)` accepts a custom Vega-Lite configuration and optional pandas or polars data. See the [custom configuration and data example](examples/vegalite_demo.py).

### Labelled outputs

Wrap a value or a rich output with `label(value, id, caption="")` to give it a stable document anchor and an optional caption:

```python
from transcript import label, markdown

measurements = {"sample": "A", "score": 0.8, "passed": True}

if "transcript":
    """
    See the [measurements](#sample-a) and the
    [quality decision](#sample-a-decision).
    """
    label(measurements, "sample-a", "Sample A measurements")
    label(
        markdown("## Decision\n\nSample A passed."),
        "sample-a-decision",
    )
```

`id` must be a valid transcript id (a letter followed by letters, digits, `_`, `.`, `:` or `-`).
The label renders as a `<figure>` carrying that `id`, so ordinary Markdown links jump to it and the caption becomes a `<figcaption>`.
A non-renderer Python value is wrapped with the built-in `code` renderer, which shows the value as a bare expression.
If an `id` is reused for different archived content, the exporter warns, appends a numeric suffix to make the label unique, and notes the duplicate in its caption.

### Composed panel grids

Wrap several outputs with `compose(*panels, ncol=2, labels=True)` to arrange them as a panel grid:

```python
from transcript import compose, label

if "transcript":
    """
    ## Comparison
    """
    compose(
        label(chart_control, "panel-a", "Control"),
        label(chart_treated, "panel-b", "Treatment"),
        ncol=2,
    )
```

Panels fill row by row and share the same column widths; the grid collapses to one column on narrow screens.
Each panel is tagged `(A)`, `(B)`, ... in reading order; pass `labels=False` to omit them.
This first version only lays panels out; it does not align axes or merge their scales.

## Snakemake rules

A document can declare a Snakemake-style rule that generates its archive or report, allowing a Snakefile to manage its inputs and outputs with wildcards. This requires the `snakemake` extra.
Declarations live in a single `with transcript.rule() as r:` block (the "rule block") at the top of the document:

```python
import transcript

with transcript.rule("demo_report") as r:
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

### Directive declarations

A document has at most one rule block. `transcript.rule()` may be called only once; add further declarations to the object it returns.
`input`, `output`, `log`, `params`, and `threads` declarations may also be scattered outside the block.
Declarations made through `r.input` / `r.output` / `r.log` / `r.params` are merged into the canonical declaration and returned resolved; for `input`, `output`, and `log` the result is a `Path`.
For example:

```python
from pathlib import Path

import transcript

with transcript.rule("demo_report") as r:
    r.input(
        a="{sample}.tsv",
        b="{sample}.yaml",
    )
    r.params(
        seed=1,
        prefix="{sample}-",
    )
r.input.a  # Raises because wildcard `sample` is unknown.
# Once a pattern is matched, the wildcards update and the same value may be set repeatedly.
(b,) = r.input("boo.yaml")
assert b == Path("boo.yaml")  # The returned value is resolved as a path.
assert r.input.a == Path("boo.tsv")  # Wildcards now apply to every declaration.
r.params.prefix = "haa-"  # Raises: wildcard `haa` conflicts with `boo`.
r.params.seed = 2  # Raises: the value does not match the declaration.
# This name is new, so it is registered and written to the archive.
r.params.seed2 = 2
```

A concrete literal declared outside the block is inferred using script-side wildcard values only.
It is first matched against the patterns already in its own list; a match records the captured wildcards and stores the pattern.
Otherwise the literal is reverse-substituted with the `r.wildcards()` defaults and inferred captures; a value that cannot be rewritten is kept as written.
A later same-list pattern that would rewrite an already-accepted literal is an error; declare the pattern first, or put the fixed literal inside the block.
Declaring a default with `r.wildcards()` is the one point where existing literals are upgraded to patterns; a default that contradicts an inferred value is an error.
`output` and `log` must use the same wildcard set; the other lists may use a subset.

### Dynamic values

Only literal values can be recorded; `lambda` functions declared inside the rule block are the exception.
`r.conda(dependencies=..., pip=..., channels=...)` declares the conda environment (rule block only): `dependencies` and `pip` become dependencies (the latter as a `pip:` sublist), and `channels` defaults to `conda-forge`.
`r.resources(**values)` is also rule-block only and is validated by Snakemake's resource mechanism.
Values remain statically readable: ordinary paths, `conda` values, and ordinary `params` round-trip through `repr` and `ast.literal_eval`.
`input` accepts a self-contained `lambda wildcards: ...`, and `params` accepts self-contained lambdas with Snakemake auxiliary parameters:

```python
import transcript

r = transcript.rule()
with r:
    r.params(
        selected=lambda wildcards, input: [
            path for path in input if wildcards.sample in path
        ],
    )
    r.input(table=lambda wildcards: f"results/{wildcards.sample}.tsv")
```

The first positional parameter receives `wildcards`, matching Snakemake's auxiliary-parameter convention; its Python parameter name is not significant.
Lambdas may use normal Python expressions, including calls and comprehensions; global or closure names, `:=`, nested lambda, and `*args`/`**kwargs` are rejected.
Defaults, when present, must be literals.
Snakemake's optional input-function `groupid` has no equivalent outside a group job and is not accepted yet.
Other functions and custom objects are not supported.

### Runtime wildcards

As in Snakemake, wildcards are named `{placeholders}` in `input`, `output`, and `log` patterns; defaults are declared once with `r.wildcards(sample="boo")`.
Read the effective value with `r.wildcards.sample` (or `r.wildcards["sample"]`); like pattern resolution it reflects declared defaults, inferred captures, and `--wildcards` overrides, and an unknown name raises `WildcardError`.
Assigning a concrete literal outside the block infers its pattern from the script-side wildcard values, so `r.output.report = "boo-1.tsv"` is recorded as `"{sample}-1.tsv"`.

Pass `--wildcards KEY=VALUE` (repeatable) to `transcript` to override the effective values for a single execution.
Every declared pattern and the declared document target then resolve with the override, so `--wildcards sample=B` turns `"{sample}-1.tsv"` into `"B-1.tsv"`.
This is how the generated Snakefile rule forwards Snakemake's wildcard values.
The override never changes the defaults stored in the archive; without `--wildcards`, the next run uses the recorded defaults.

### Output redirection

An optional `output.document` or `log.document` marks the document's final `.tmd.py` or `.html` target.
It must be declared inside the rule block (for example `r.output(document="{sample}.html")`); declaring both is an error, and any other suffix is rejected.

The archive target is chosen in this order:

1. `-o`/`--output` has the highest priority. The archive is written there, and the recorded `document` is reconciled with it:
   - if the `-o` value can be converted to a pattern with the current wildcard values, the existing `output.document` (or else `log.document`, or else a new `output.document`) records that pattern, so runs with different wildcard values remain stable;
   - otherwise the concrete `-o` cannot avoid overwriting, so any existing `document` is dropped.
2. Without `-o`, a declared `document` from the rule block is resolved with the effective wildcards and used.
3. Otherwise the archive falls back to the document's sibling `<stem>.tmd.py` (or the `.tmd.py` itself when the input already is an archive).

A declared `.html` document makes the effective target `.html`, which selects HTML export; see [HTML export](#html-export) for how `--html` and `--no-html` override this.

The target follows the rule, not the input filename.
An archive created with `-o` records the reconciled `document` pattern but neither the concrete name nor the `--wildcards` values, so re-executing it without `--wildcards` falls back to the recorded defaults.
For example, the [rule demo](examples/rule_demo.py) declares `r.wildcards(sample="A", feature="score")`:

| input file              | parameter                                                      | files changed on disk                               | behavior                                                                                                             |
| ----------------------- | -------------------------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `examples/rule_demo.py` | `-o rule_demo-B-count.html --wildcards sample=B feature=count` | writes `rule_demo-B-count.tmd.py/.html`                | adds `document="rule_demo-{sample}-{feature}.html"` to the document.                                                 |
| `rule_demo-B-count.tmd.py` |                                                                | writes `rule_demo-A-score.tmd.py/.html`, not B-count   | executes the archive and resolves the declared document with the recorded defaults (A/score).                        |
| `rule_demo-B-count.tmd.py` | `--diff`                                                       |                                                     | compares that re-execution against `rule_demo-A-score.tmd.py`, not the input archive; exit 1 if missing target.         |
| `rule_demo-B-count.tmd.py` | `--overwrite --html`                                           | creates/overwrites `rule_demo-A-score.tmd.py/.html`    | similar to above                                                                                                     |
| `rule_demo-B-count.tmd.py` | `--diff --html`                                                | create/check `rule_demo-A-score.tmd.py`, write `.html` | creates a missing target archive, a difference against an existing archive still blocks export.                      |
| `rule_demo-B-count.tmd.py` | `--html`                                                       | renders `rule_demo-B-count.html`                    | renders the stored results directly without executing, so this one keeps the input name.                             |
| `rule_demo-B-count.tmd.py` | `--overwrite -o examples/rule_demo.html`                       | writes `examples/rule_demo.tmd.py/.html`               | the concrete `-o` cannot become a pattern, so the declared `document` is dropped; execution uses defaults (A/score). |
| `rule_demo-B-count.tmd.py` | `--overwrite --html --wildcards sample=B feature=count`        | rewrites `rule_demo-B-count.tmd.py/.html`              | re-executes with an explicit override and reproduces the B-count target.                                             |

In practice, run `transcript examples/rule_demo.py -o rule_demo-A-score.html` once, then use the generated `.tmd.py` as the template.

### Rule extraction

An explicit rule name must match `[A-Za-z_][A-Za-z0-9_]*` and is rejected otherwise.
The default document stem is normalized instead: invalid characters are replaced
with `_`, and a leading digit is prefixed with `_`.
`input.document` is reserved for the document's own path; a user-declared `input.document` is rejected.

`transcript report.py --snakefile Snakefile` writes the matching Snakefile rule into
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
        "transcript {input.document:q} -o {output.document:q} --wildcards sample={wildcards.sample:q}"
```

The `.html` suffix passed through `-o` selects HTML export.

## Development

The Pixi development environment includes the HTML renderer, Datavzrd, Vega-Lite (via `vl-convert`), pandas, and polars, and targets Linux x86-64 and Python 3.14.
From the repository root:

```bash
pixi install
pixi run check
```

`pixi run check` runs Ruff, Pyright, the frontend type-check and tests, the frontend build, and pytest.
Use `pixi run format` to format the code.

Browser sources live in `src/frontend` as TypeScript and CSS.
`pixi run frontend-build` generates the `transcript.min.js` and `style.min.css` assets embedded by the Python package; tests and package builds run this automatically.
Development and source builds require esbuild; installed wheels only use their packaged minified assets.

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
| `report-block` | A module-level `if "transcript":` or `with transcript.report:` block |
| `markdown`     | The first docstring inside the block                               |
| `code`         | A top-level statement that runs and may produce output             |
| `output slot`  | A docstring after a code statement, replaced on each update        |

### Roadmap

transcript is under active development: the items below are planned.

- More for Composed renderer:
    - explicit `Panel` placement, shared axes over the union of raw domains, max-margin alignment, data-coordinate annotations, legend merging, and an extended compose header.
- More for Sidebar:
    - bibliography `references`, a sidebar outline/figure list, an abbreviation list.
- More for Browser rendering:
    - more themes
- More for Snakemake runtime:
    - inheriting the `script:`-injected job context into `Rule` instead of relying on static declarations or recomputed lambdas.
- More Review function:
    - allow mark simple shapes and texts on figures.
- More renderers:
    - `pickle`: an opt-in escape hatch for values with no portable representation.

### Rich output convention

Each `transcript-output` fenced block represents one output item, so an output slot can mix ordinary text, images, and rich outputs.
Renderer objects write this block automatically when displayed as bare expressions or passed to `print()`.
The fence header names the renderer and may pin a version constraint; the body is the renderer's serialized data:

````text
```transcript-output datavzrd=1
{
  "config": {
    "default-view": "results",
    "views": {"results": {"dataset": "data"}}
  },
  "csv": "sample,score\nA,0.8\nB,0.3\n"
}
```
````

Each renderer owns its archive format: `serialize()` produces the fence body, `to_tmd()` wraps it in the versioned fence, and `to_html()` validates a stored body and returns a `Rendered` value containing HTML, files, nested children, and display metadata.
After parsing a fence, `RecordedOutput` associates that rendered value with its renderer class and source span.
Datavzrd, for example, stores JSON containing CSV text and the effective configuration, including the contents of a loaded YAML file.
A block body may itself contain `transcript-output` blocks (as `label` and `compose` do): the exporter renders each child once, gives it its own report id and file namespace, and substitutes it for the parent's `{{i}}` placeholder, so nested renderers keep separate styles, runtimes, and report files.
Nested outputs are recursively converted into reports, and browser assets are collected once per renderer name.
Renderer styles and runtimes share the exported document. Renderers should use renderer-specific CSS classes, avoid modifying generic document selectors or global JavaScript state, and must not depend on renderer resource loading order.

The header constraint is compared with the installed renderer version, so `datavzrd=1`, `datavzrd>=1`, and `datavzrd<2` are accepted forms.
Blocks that name an unknown renderer, declare an unsupported version, or cannot be validated remain readable as plain text and emit a warning instead of failing the export.
Older blocks without a renderer in the header are kept as plain text; regenerate the archive with `--overwrite` to use the versioned fence.
Do not hand-edit generated output slots to select a renderer: execution replaces recorded outputs, so make that choice in the code.
