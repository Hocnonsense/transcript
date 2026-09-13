# snakedone

Execute Python documents and save recorded outputs to `.snd` archives.
Write Markdown and real Python inside module-level report blocks.
Archives remain valid Python and can be executed again to compare or update their outputs, or exported to standalone HTML reports.

## Installation

Requires Python ≥3.11, with no mandatory third-party runtime dependencies.
Install from the repository root:

```bash
python -m pip install -e .
# For HTML export, install the optional renderer:
python -m pip install -e '.[html]'
# For interactive Datavzrd tables in HTML, install the datavzrd extra
# (it includes the HTML renderer):
python -m pip install -e '.[datavzrd]'
```

Exporting Datavzrd tables to HTML additionally requires the `datavzrd` executable on `PATH`, for example `conda install -c conda-forge datavzrd`.
Install pandas or polars separately for the DataFrames used by your document.
Creating an archive does not invoke Datavzrd, and opening the exported HTML needs only a browser.

## Usage

```bash
# Execute the source and create or replace its archive.
snakedone examples/demo.py

# Execute the source and compare against its archive.
snakedone examples/demo.py --diff

# Execute the archive and compare its recorded outputs.
snakedone examples/demo.snd

# Execute and update the archive in place.
snakedone examples/demo.snd --overwrite
```

The example reads the adjacent `data.json` and creates `examples/demo.snd`, recording text, a CSV table, RGB data, an explicitly printed Markdown image (`![](data:image/png;base64,...)`), and a Datavzrd snapshot. Change the data file to try comparing and updating the archive.
`snakedone examples/datavzrd_demo.py --html` then renders `examples/datavzrd_demo.html`, which shows the Datavzrd table.

### Archive generation and comparison

With the default output path:

| Mode          | `.py` input                          | `.snd` input           |
| ------------- | ------------------------------------ | ---------------------- |
| `--diff`      | Compare against the sibling `.snd`   | Compare against itself |
| Default       | Create or replace the sibling `.snd` | Compare against itself |
| `--overwrite` | Create or replace the sibling `.snd` | Update in place        |

`--diff` and `--overwrite` are mutually exclusive.
`--diff` executes the input, prints a unified diff when recorded outputs differ, and leaves the archive unchanged.
A missing archive is compared against empty text, except when exporting HTML as described below.

Use `-o` / `--output` to select a different archive path.
Without an explicit mode, execution writes the target when it differs from the input path and compares when they are the same.

`.py` source files are always kept unchanged.
An archive does not require the original `.py` file, but execution still needs any data files and dependencies used by its code.

### HTML export

```bash
# Export stored results without executing the archive.
snakedone examples/demo.snd --html
snakedone examples/demo.snd -o report.html

# Execute Python, write report.snd, then export report.html.
snakedone examples/demo.py -o report.html

# An .html output path also selects HTML export.
snakedone examples/demo.py -o report.html

# Create a missing report.snd or compare against it before exporting.
snakedone examples/demo.py --diff -o report.html
```

`--html` or an `.html` output suffix selects HTML export.
A `.snd` input with neither `--diff` nor `--overwrite` is read directly: its stored results are exported without execution or verification.
All other combinations execute the input first and export only after successful archive generation or comparison.
In HTML mode, `--diff` creates a missing target archive instead of comparing against empty text; differences in an existing archive prevent export.

The output path determines both the archive and report names.
An `.html` or `.snd` suffix selects their shared basename.
Other names receive the appropriate suffix: `-o report.v1` selects `report.v1.snd`, while adding `--html` also selects `report.v1.html`.
Direct export from `.snd` reads the input archive and writes only the report.

See [HTML reports](#html-reports) for rendering details.

### Exit codes

- `0`: archive generation, comparison, or HTML export succeeded.
- `1`: comparison found differences, or an uncaught archive file I/O error occurred, such as a missing input file.
- `2`: invalid arguments, document parsing or execution errors, or HTML input/output or rendering errors.

## Document syntax

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

- `if "snakedone":` is always true, so the file runs with plain Python and needs no dependency; the string literal itself is the marker.
- `with snakedone.report:` runs a real context manager and requires `import snakedone`; the tool writes a `# snakedone` marker after its colon in the archive.
The two entries are equivalent and may be mixed in one document.

`report` is a plain object.
A top-level `with` is a report block when the context manager **is** that object at run time, so `with snakedone.report:`, `with report:` (after `from snakedone import report`) and any alias all work.

The `# snakedone` marker right after the `with` colon is handled during `.snd` generation: execution removes any existing marker and re-adds it where `context is report`.
That keeps archives (`.snd`) self-describing for HTML export without ever forcing a `with` to be a report block.

Inside a block, the top-level statements are treated as follows:

- The first docstring is Markdown. A block may contain only Markdown. All other strings are considered as output slot and refreshed in `.snd`
- A non-string expression statement runs and echoes its value like a REPL (`repr`, or CSV for tables and a rich block for recorded outputs).
- Any other statement (assignment, `import`, `for`, `if`, `try`, …) runs normally; its stdout is archived.
- Every statement that produces output is followed by an output docstring, which is
  rebuilt on each run. Existing output docstrings are discarded and regenerated.

Specfically:
`for`, `if`, and `try` are collected as one unit, so a loop prints all of its output into a single slot.
An f-string is a computed expression (not a docstring), so it is echoed rather than treated as Markdown.

To continue the narrative, start another report block.
The document and every block must have valid Python syntax, including during HTML export.

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

### Output and escaping

Each statement captures stdout and displays the value as if in python REPL.

Stdout from code outside report blocks is not archived.
Logging follows the document's configuration, and logs directed to stdout during a report block may also be captured.

Archives use UTF-8 and LF line endings and end with one newline.
Backslashes `\` are escaped in output docstrings; quotes are escaped only when they would close the triple-quoted literal, so recorded JSON and prose stay readable in the archive.

## Execution semantics

Python runs report blocks normally.
snakedone additionally captures each top-level statement's output and writes it back into the block's output docstrings.

`if "snakedone":` and `with snakedone.report:` behave the same under snakedone.
Running the file with plain Python executes the blocks but does not echo bare expressions or update docstrings; `if "snakedone":` needs no import.

Unhandled execution errors prevent archive writes, leaving an existing archive intact.

## HTML reports

Reports follow source order, alternating script code and report blocks.
`markdown` is rendered as Markdown, including headings, lists, links, fenced code, and tables.
Script code starts collapsed and occupies no height in the document flow.

CSV and other text outputs retain their original formatting.
Standalone `![](data:image/png;base64,...)` lines become inline images; bare PNG data URI lines from existing archives are also supported.
Text, images, and explicitly selected rich outputs appear in their recorded order within the same output section.
The rendering step reads the archive without executing Python.

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

`datavzrd(frame, config)` records a snapshot of the data as CSV plus the Datavzrd configuration in a `snakedone-output` block inside the archive.
HTML export dispatches the block to the registered renderer, so new renderers can be added without changing the archive format or the HTML step.
`config` may be a mapping or a YAML filename, resolved against the current working directory like any Python file read; when omitted, a single table view named `results` is created.
Every view must use the managed dataset `data`, and snakedone supplies `datasets.data.path` itself, so no intermediate files are kept.
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

The [pandas and polars example](examples/datavzrd_demo.py) uses a shared [YAML configuration](examples/datavzrd.yaml) with column bars, a heatmap, and two views of the same dataset:

The initial Datavzrd integration supports one archived dataset per output and any number of table views over it.
Built-in `render-table` options such as column bars, heatmaps, and links are supported.
Ordinary DataFrame expressions retain their existing display behavior; use the wrapper to select Datavzrd explicitly.

HTML export runs the `datavzrd` executable once per distinct recorded snapshot and embeds the generated report, including its scripts, styles, and data, into the single HTML file.
The report runs inside a sandboxed iframe with embedded `data:` URLs for its resources, so sorting, filtering, paging, and built-in plots keep working without a network connection or the original data files.
Embedded report files are gzip-compressed and decompressed in the browser with `DecompressionStream`, and files shared by several reports are stored once, so a typical report stays near 2 MB instead of embedding Datavzrd's ~6 MB bundle verbatim.
This is why a report containing Datavzrd tables relaxes the report's Content Security Policy to allow embedded `data:` and `blob:` scripts and `'unsafe-eval'` (used by Vega plot expressions); documents without Datavzrd tables keep the stricter policy.
If configuration validation or rendering fails, HTML export reports an error and preserves any existing HTML file.

## Development

The Pixi development environment includes the HTML renderer, Datavzrd, pandas, and polars, and targets Linux x86-64 and Python 3.14.
From the repository root:

```bash
pixi install
pixi run check
```

`pixi run check` runs pytest, Ruff, and Pyright.
Use `pixi run format` to format the code.
