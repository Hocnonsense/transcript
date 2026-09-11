# snakedone

Execute Python documents and save recorded outputs to `.snd` archives.
Write Markdown in `doc-md` and Python in `doc-code` using `>>>` and `...` prompts.
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

Datavzrd tables additionally require the `datavzrd` executable on `PATH`, for example `conda install -c conda-forge datavzrd`.

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
`pixi run snakedone examples/demo.py --html` (or `pixi run demo` for the archive only) then renders `examples/demo.html`, which shows the Datavzrd table.

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
snakedone examples/demo.py --html -o report.html

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
script-block
module-docstring
├── doc-md
└── doctest
    ├── doc-code
    └── doc-out
```

| Term               | Meaning                                                                       |
| ------------------ | ----------------------------------------------------------------------------- |
| `script-block`     | Ordinary Python code outside `module-docstring` elements                      |
| `module-docstring` | A standalone, unassigned module-level triple-quoted string                    |
| `doc-md`           | Markdown before the first `doctest`, or the entire string if it has none      |
| `doctest`          | A `doc-code` section followed by its `doc-out`                                |
| `doc-code`         | Python code introduced by `>>> ` and continued by `... `                      |
| `doc-out`          | Captured stdout and the displayed value of the final expression in `doc-code` |

Here, `module-docstring` includes qualifying strings anywhere at module level (Python's own term "module docstring" refers only to a string used as the module's first statement.)
A `doctest` uses doctest-style prompts without implying all behavior of Python's standard-library `doctest` module.

### Conventions

Store `doc-md` and `doctest` elements in `module-docstring` elements using `"""` or `'''`.
Strings inside blocks such as conditionals, loops, functions, classes, and context managers are not processed as `module-docstring` elements; their contents are preserved unchanged.
A document may contain just one string, or `doc-md` without any `doctest` elements.

- `doc-md` is the optional Markdown text before the first `>>> `.
- `>>> ` starts a `doctest`. Immediately following `... ` lines at the same indentation continue its `doc-code`.
- `doc-out` includes everything after `doc-code`, up to the next `>>> ` or the end of the string, including blank lines and prose. It is replaced on each update.
- To continue the narrative after a `doctest`, start a separate `module-docstring`.

The document and every `doctest` must have valid Python syntax, including during HTML export.
Implicitly concatenated strings and non-triple-quoted strings containing `doctest` elements are skipped with a warning; their existing contents remain unverified.

### Example

Save the following as `analysis.py`:

```python
value = 7

"""
# Analysis

>>> value
>>> value = 'updated'
>>> value
>>> for number in [1, 2]:
...     print(number)

(This text will be replaced.)
"""

value = 8
```

Running `snakedone analysis.py` produces this complete `analysis.snd`:

```python
value = 7

"""
# Analysis

>>> value
7
>>> value = 'updated'
>>> value
'updated'
>>> for number in [1, 2]:
...     print(number)
1
2
"""

value = 8
```

### Output and escaping

Each `doctest` captures stdout and displays the value of its final expression if that value is not `None`.
Values use `repr` by default; table objects with a `to_csv` method are displayed as CSV.
Images must be explicitly printed as data URIs; image objects are not automatically rendered.

Stdout from `script-block` elements is not archived.
Logger levels and handlers are left unchanged, so logging follows the document's configuration.
Logs directed to stdout during a `doctest` may also be captured.

In ordinary strings, `\n` escapes are decoded before `doctest` elements are parsed and are written as physical newlines in the archive.
Literal `\n` sequences in raw strings remain literal.
Escaping and quote spelling within `module-docstring` elements may be normalized.
Archives use UTF-8 and LF line endings and end with one newline.

Output lines beginning with optional whitespace followed by `>>> ` are escaped to `\>>> ` so they are not interpreted as code on the next run.
Backslashes are escaped in ordinary strings; quotes are escaped only when they would close the triple-quoted literal, so recorded JSON and prose stay readable in the archive.
A raw string containing its own triple-quote delimiter cannot be rendered and causes generation to fail.

## Execution semantics

Python ignores `doc-code` inside strings.
snakedone additionally executes that code when it reaches each `module-docstring`.
`doctest` elements in Python's module docstring run after all legal leading `from __future__` imports.
`script-block` elements execute normally, including conditional branches and context managers.

Each `module-docstring` receives a shallow copy of the current module namespace.
Its `doctest` elements share that copy; the bindings are discarded at the end of the string, and the next `module-docstring` receives a fresh copy.

- Creating, reassigning, or deleting names does not change bindings in the surrounding Python code.
- Lists, tables, modules, functions, and other objects remain shared. Mutating those objects can affect subsequent computation, and aliases remain intact.
- Existing functions retain their original globals, default arguments, and closures. Rebinding a name in a `doctest` does not redirect a function's globals.
- File I/O, iterator consumption, random state changes, and other side effects are not rolled back. This also applies in comparison mode.

Unhandled execution errors prevent archive writes, leaving an existing archive intact.

## HTML reports

Reports follow source order, alternating `script-block` elements and `module-docstring` elements.
`doc-md` is rendered as Markdown, including headings, lists, links, fenced code, and tables.
`script-block` elements start collapsed and occupy no height in the document flow.

CSV and other text outputs retain their original formatting.
Standalone `![](data:image/png;base64,...)` lines become inline images; bare PNG data URI lines from existing archives are also supported.
Text and images appear in their recorded order within the same `doc-out` section.
The rendering step reads the archive without executing Python.

### Datavzrd tables

Wrap a pandas or polars `DataFrame` to render it as an interactive [Datavzrd](https://datavzrd.github.io/) table in the HTML report:

```python
from snakedone import datavzrd

frame = pandas.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})

"""
>>> datavzrd(frame, {"views": {"results": {"dataset": "data"}}})
"""
```

`datavzrd(frame, config)` records a snapshot of the data as CSV plus the Datavzrd configuration in a `snakedone-output` block inside the archive.
That block stores only the renderer name and its payload; HTML export dispatches to the registered renderer, so new renderers can be added without changing the archive format or the HTML step.
`config` may be a mapping or a YAML filename, resolved against the document directory; when omitted, a single table view named `results` is created.
Every view must use the managed dataset `data`, and snakedone supplies `datasets.data.path` itself, so no intermediate files are kept.
A single-view configuration opens that table directly instead of Datavzrd's overview page; multiple views show the overview unless `default-view` selects one.
Configurations that require external assets, custom JavaScript, plots from external data, or online services are rejected when the snapshot is created; built-in `render-table` options such as column bars, heatmaps, and links are supported.

HTML export runs the `datavzrd` executable once per recorded table and embeds the generated report, including its scripts, styles, and data, into the single HTML file.
The report runs inside an iframe served from embedded `blob:` URLs, so sorting, filtering, paging, and built-in plots keep working without a network connection or the original data files.
Embedded report files are gzip-compressed and decompressed in the browser with `DecompressionStream`, and files shared by several reports are stored once, so a typical report stays near 2 MB instead of embedding Datavzrd's ~6 MB bundle verbatim.
This is why a report containing Datavzrd tables relaxes the report's Content Security Policy to allow `blob:` scripts and `'unsafe-eval'` (used by Vega plot expressions); documents without Datavzrd tables keep the stricter policy.

## Development

The Pixi development environment includes the HTML renderer and targets Linux x86-64 and Python 3.14.
From the repository root:

```bash
pixi install
pixi run check
```

`pixi run check` runs pytest, Ruff, and Pyright.
Use `pixi run format` to format the code.
