snakedone
=========

`snakedone` is a validated python document, capable to archive outputs, and export as standalone HTML reports with markdown docstrings.

## Installation

Requires Python ≥3.11.
Install from the repository root:

```bash
python -m pip install -e .
# Optional HTML renderer:
python -m pip install -e '.[html]'
# Optional extras (each includes the HTML renderer):
python -m pip install -e '.[datavzrd]'   # interactive Datavzrd tables
python -m pip install -e '.[vegalite]'   # static Vega-Lite charts
```

Install pandas or polars separately for the DataFrames used by your document.

## Usage

```bash
snakedone examples/demo.py                 # create or replace the archive
snakedone examples/demo.py --diff          # compare against the archive
snakedone examples/demo.snd                # execute the archive and compare
snakedone examples/demo.snd --overwrite    # execute and update in place
```

In brief, use `-o` / `--output` to choose another destination. `--diff` never updates an existing archive; `--overwrite` updates the input archive.
`.py` files are never modified, and the archived `.snd` works the same as the original file.

The [demo](examples/demo.py) reads the adjacent `data.json` and records text, a DataFrame table, RGB data, and an explicitly printed Markdown image.

### Archive generation and comparison


With the default output path:

| Mode          | `.py` input                          | `.snd` input           |
| ------------- | ------------------------------------ | ---------------------- |
| `--diff`      | Compare against the sibling `.snd`   | Compare against itself |
| Default       | Create or replace the sibling `.snd` | Compare against itself |
| `--overwrite` | Create or replace the sibling `.snd` | Update in place        |

`--diff` executes the input, prints a unified diff when recorded outputs differ, and mutually exclusive with `--overwrite`.

Without `-o` / `--output` given, execution writes the target when it differs from the input path and compares when they are the same.


### HTML export

```bash
snakedone examples/demo.snd --html                # export stored results without executing
snakedone examples/demo.py --html                 # execute, write report.snd, export report.html
snakedone examples/demo.py -o report.html         # an .html output path also selects export
snakedone examples/demo.py --diff -o report.html  # create/compare before exporting
```

`--html` or an `.html` output suffix selects HTML export.
A `.snd` input with neither `--diff` nor `--overwrite` is read directly; all other combinations execute the input first and export only after successful archive generation or comparison.
In HTML mode, `--diff` creates a missing target archive instead of comparing against empty text; differences in an existing archive prevent export.

`-o` / `--output` determines both the archive and report names.
An `.html` or `.snd` suffix selects their shared basename; other names receive the appropriate suffix.

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
A top-level `with` is a report block when the context manager **is** the `from snakedone import report` at run time, any alias works.

Inside a block, the top-level statements are treated as follows:

- The first docstring is Markdown. A block may contain only Markdown. All other docstrings are always refreshed.
- Every statement produces output as if in a Python REPL:
- A non-string expression statement runs and echoes its value like a REPL (`repr`, or a rich block for recorded outputs), including an f-string.
- Any other statement (assignment, `import`, `for`, `if`, `try`, …) runs normally; its stdout is collected as one unit, so a loop prints all of its output into a single slot.
- The stdout of eahc statement are display in a doucstring below it, on each run.


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
`markdown` is rendered as Markdown, including headings, lists, links, fenced code, and tables.
Script code starts collapsed and occupies no height in the document flow.

CSV and other text outputs retain their original formatting.
Standalone `![](data:image/png;base64,...)` lines become inline images, and Markdown image links render as online images.
Text, images, and explicitly selected rich outputs appear in their recorded order within the same output section.
Rendering reads the archive without executing Python.

Wrap generated Markdown in `Markdown` when an expression's value should be rendered as document Markdown instead of plain text:

```python
from snakedone import Markdown

if "snakedone":
    Markdown("## Generated result\n\n- first\n- second")
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

The initial Datavzrd integration supports one archived dataset per output and any number of table views over it, including built-in `render-table` options such as column bars, heatmaps, and links.
Ordinary DataFrame expressions retain their existing display behavior; use the wrapper to select Datavzrd explicitly.

HTML export runs the `datavzrd` executable once per distinct recorded snapshot and embeds the generated report into the single HTML file, so sorting, filtering, paging, and built-in plots keep working offline.
If configuration validation or rendering fails, HTML export reports an error and preserves any existing HTML file.

### Vega-Lite charts

[Vega-Lite](https://vega.github.io/vega-lite/) chart from [Altair](https://altair-viz.github.io/) used as a report expression is automatically recorded with the Vega-Lite renderer:

```python
import altair as alt
import pandas as pd

frame = pd.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})
chart = alt.Chart(frame).mark_bar().encode(
    x="sample:N",
    y="score:Q",
    tooltip=["sample:N", "score:Q"],
)

if "snakedone":
    """
    ## Altair chart
    """
    vegalite(chart)
```

Install the renderer with `python -m pip install -e '.[vegalite]'`.
snakedone snapshots the chart's Vega-Lite specification and data, so the archive
does not depend on the original DataFrame.

HTML export inlines a static SVG preview with `vl-convert`, so the report is always a single offline file.
By default the preview is upgraded to an interactive chart when the page is opened online (disabled by `offline=True`).
Use `vegalite(chart, offline=True)` when the Altair chart should remain a pure
static SVG instead of upgrading to an interactive chart online.

Alternatively, `vegalite(config, data=None)` accepts a custom Vega-Lite
configuration and optional pandas or polars data. See the
[custom configuration and data example](examples/vegalite_demo.py).

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
