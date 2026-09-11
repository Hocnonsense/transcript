# snakedone

Execute Python documents and save recorded outputs to `.snd` files. Write prose in Markdown and records using doctest-style `>>>` and `...` prompts.
The generated archive remains valid Python and can be executed again to compare or update its outputs.

HTML rendering is not yet implemented.

## Installation and usage

Requires Python ≥3.11, with no mandatory third-party runtime dependencies.
Install from the repository root:

```bash
python -m pip install -e .
snakedone examples/demo.py
```

The example reads the adjacent `data.json` and creates `examples/demo.snd`,
recording text, a CSV table, RGB data, and an explicitly printed PNG data URI.

```bash
# Execute the source and compare against the existing archive.
snakedone examples/demo.py --diff

# After editing examples/data.json, regenerate the archive.
snakedone examples/demo.py

# Execute the archive itself and compare its recorded outputs.
snakedone examples/demo.snd

# Execute and update the archive in place.
snakedone examples/demo.snd --overwrite
```

| param \\ input | `.py`                                | `.snd`                 |
| -------------- | ------------------------------------ | ---------------------- |
| `--diff`       | Compare against the existing `.snd`  | Compare against itself |
| Default        | Create or replace the sibling `.snd` | Compare against itself |
| `--overwrite`  | Create or replace the sibling `.snd` | Update in place        |


`--diff` and `--overwrite` are mutually exclusive.
Comparison prints a unified diff without writing the archive.
If the `.snd` doesn;t exists, will compare with an empty string.
All modes execute the document's code, any `.py` file is kept unchanged.
An archive does not require the original `.py` file, but still needs any data files and dependencies used by its code.

Exit codes:

- `0`: the archive was written successfully, or comparison found no differences.
- `1`: comparison found differences. Currently, uncaught file I/O errors, such as
  a missing input or archive, also exit with this code.
- `2`: invalid arguments, or an error while parsing, executing, or rendering the
  document.

## Document syntax

### Conventions

Store prose and records in standalone, unassigned triple-quoted strings (`"""` or `'''`).
Strings are recognized at module level and inside blocks nested only through `if` / `elif` / `else` and synchronous `with` statements.
Records inside loops, functions, classes, `try`, `match`, or `async with` are not processed.
A document may contain just one string, or prose without any records.

- Text before the first `>>> ` is Markdown prose. This section is optional.
- `>>> ` starts a Python record. Immediately following `... ` lines at the same indentation continue that record's code.
- Everything after the code, up to the next `>>> ` or the end of the string, is replaceable output, including blank lines and prose.
- To continue the narrative after a record, start a separate string.

### Example

Save the following as `analysis.py`:

```python
value = 7

"""
# Documents

>>> value
>>> value = 'sth'
>>> value
>>> for number in [1, 2]:
...     print(number)

(text here will be deleted)
"""

value = 8
```

Running `snakedone analysis.py` produces this complete `analysis.snd`:

```python
value = 7

"""
# Documents

>>> value
7
>>> value = 'sth'
>>> value
'sth'
>>> for number in [1, 2]:
...     print(number)
1
2
"""

value = 8
```

Assignments within records affect only the current string's namespace bindings.
The surrounding Python code is preserved.

### Output and escaping

Each record captures stdout and displays the value of its final expression if that value is not `None`.
Values use `repr` by default; table objects with a `to_csv` method are displayed as CSV.
Images must be explicitly printed as data URIs; image objects are not automatically rendered.

Stdout from ordinary Python code is not archived. Logger levels and handlers are left unchanged, so logging follows the document's configuration.
Logs directed to stdout during a record may also be captured.

In ordinary strings, `\n` escapes are decoded before records are parsed and are written as physical newlines in the archive.
Literal `\n` sequences in raw strings remain literal.
Escaping and quote spelling within record strings may be normalized.
Archives use UTF-8 and LF line endings and end with one newline.

Output lines beginning with optional whitespace followed by `>>> ` are escaped to `\>>> ` so they are not interpreted as code on the next run.
Backslashes and matching quotes are escaped in ordinary strings.
A raw string containing its own triple-quote delimiter cannot be rendered and causes generation to fail.
Implicitly concatenated strings and non-triple-quoted strings containing records are skipped with a warning; their existing contents remain unverified.

## Execution semantics

Python ignores record code inside strings. snakedone additionally executes that code when it reaches each string.
Records in the module docstring run after all legal leading `from __future__` imports.

Each executed record string receives a shallow copy of the current module namespace.
Records within that string share the copy.
Its bindings are discarded at the end of the string, and the next string receives a fresh copy.

- Creating, reassigning, or deleting names does not change bindings in the   surrounding Python code.
- Lists, tables, modules, functions, and other objects remain shared. Mutating those objects can affect subsequent computation, and aliases remain intact.
- Existing functions retain their original globals, default arguments, and closures. Rebinding a name in a record does not redirect a function's globals.
- File I/O, iterator consumption, random state changes, and other side effects are not rolled back. This also applies in comparison mode.

Only records in selected branches execute.
Old outputs in unexecuted branches are cleared when generating the archive, while code and prose are preserved.
Records inside `with` execute before the context exits.
If the context suppresses a record's exception, execution continues after the context; remaining records in that string are skipped, and previously completed outputs are retained.
Unhandled execution errors prevent archive writes, leaving an existing archive intact.
Empty output can mean either that a record did not execute or that it executed without producing output.

## Development

The Pixi development environment targets Linux x86-64 and Python 3.14. From the repository root:

```bash
pixi install
pixi run check
```

`pixi run check` runs pytest, Ruff, and Pyright.
Use `pixi run format` to format the code.
