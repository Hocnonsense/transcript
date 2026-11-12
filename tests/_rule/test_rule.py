"""Rule declarations, canonical block generation, and CLI routing."""

import subprocess
import sys
from pathlib import Path

import pytest
from snakemake.exceptions import WildcardError, WorkflowError
from snakemake.iocontainers import Namedlist

from transcript._rule.core import Rule, rule
from transcript._rule.registry import current, set_current
from transcript.execute import ExecutionScope

from ..conftest import run_cli, run_source


@pytest.fixture(autouse=True)
def clean_rule():
    set_current()
    yield
    set_current()


BLOCK_SOURCE = '''\
import transcript

with transcript.rule() as r:
    r.input(a="{sample}.tsv")
    r.output(document="{sample}.tmd.py")
    r.params(seed=1)
    r.threads = 4
    r.resources(mem_mb=8000, runtime="2h")
    r.conda(dependencies=["pandas=*"], pip=["snakemake"])
    r.wildcards(sample="s1")

if "transcript.md":
    """
    # Report
    """
    r.input.a
'''

SCATTER_SOURCE = '''\
import transcript

with transcript.rule() as r:
    pass

r.wildcards(sample="s1")
r.input.a = "{sample}.tsv"
r.params.seed = 1
r.threads = 4
r.resources(mem_mb=8000, runtime="2h")

if "transcript.md":
    """
    scattered
    """
    r.input.a
'''


def test_call_and_attribute_declarations():
    r = rule()
    r.wildcards(sample="s1")
    first = r.input("a.tsv")
    r.input("b.tsv")
    r.input(c="c.tsv")
    out = r.output(report="{sample}.tmd.py")
    assert isinstance(first, Namedlist)
    assert isinstance(out, Namedlist)
    assert str(first[0]) == "a.tsv"
    assert [str(path) for path in r.input] == ["a.tsv", "b.tsv", "c.tsv"]
    assert str(r.input[0]) == "a.tsv"
    assert str(r.input[2]) == "c.tsv"
    assert str(r.input.c) == "c.tsv"
    assert str(out[0]) == "s1.tmd.py"


def test_input_entry_order_and_conflicts():
    r = rule()
    r.input.a = "a"
    with pytest.raises(WorkflowError, match="anonymous entry"):
        r.input("b")

    r.input.a = "a"
    with pytest.raises(WorkflowError, match="already declared"):
        r.input.a = "b"

    r.wildcards(sample="s1")
    r.input.b = "{sample}.tsv"
    r.input.b = "s1.tsv"
    with pytest.raises(WorkflowError, match="already declared"):
        r.input.b = "s1.csv"
    assert str(r.input.b) == "s1.tsv"

    with pytest.raises(WorkflowError, match="once"):
        r.wildcards(sample="s2")


def test_fragment_reserves_only_input_document():
    r = rule()
    with r:
        r.input(document="source.py")
        r.output(document="x.tmd.py")
        r.log(document="x.log")
        r.params(document="metadata")
    with pytest.raises(WorkflowError, match="input.document"):
        r.make_snakemake_rule()


def test_runtime_wildcards_stay_on_the_rule_and_drive_resolution(tmp_path: Path):
    with ExecutionScope(tmp_path / "document.py", {"sample": "s2"}):
        r = rule()
        r.wildcards(sample="s1")
        r.input.a = "{sample}.tsv"
        assert str(r.input.a) == "s2.tsv"
        assert r.resolve("{sample}.tmd.py") == "s2.tmd.py"
    # the runtime wildcards stay on the rule after the execution scope exits
    assert str(r.input.a) == "s2.tsv"
    assert r.resolve("{sample}.tmd.py") == "s2.tmd.py"
    assert r.resolve("{sample}.tmd.py", {"sample": "s3"}) == "s3.tmd.py"

    r2 = Rule()
    with pytest.raises(WildcardError, match="sample"):
        r2.input.a = "{sample}.tsv"


def test_execution_scope_scopes_and_restores_the_current_rule(tmp_path: Path):
    assert current() is None
    with ExecutionScope(tmp_path / "document.py"):
        job = rule()
        assert current() is job
    assert current() is None

    outer = Rule()
    set_current(outer)
    with ExecutionScope(tmp_path / "nested.py", {"sample": "inner"}):
        assert current() is None
        inner = rule()
        assert current() is inner
    assert current() is outer


def test_rule_errors_when_a_rule_is_already_current(tmp_path: Path):
    with ExecutionScope(tmp_path / "document.py"):
        rule()
        with pytest.raises(WorkflowError, match="only be called once per document"):
            rule()


def test_wildcards_view_reads_declared_inferred_and_runtime_values(tmp_path: Path):
    defaults_only = rule()
    defaults_only.wildcards(sample="s1", feature="score")
    assert defaults_only.wildcards.sample == "s1"
    assert defaults_only.wildcards["feature"] == "score"
    assert "sample" in defaults_only.wildcards
    with pytest.raises(WildcardError, match="missing"):
        defaults_only.wildcards.missing

    with ExecutionScope(tmp_path / "document.py", {"sample": "s2"}):
        runtime = rule()
        runtime.wildcards(sample="s1")
        assert runtime.wildcards.sample == "s2"
    # the runtime value stays on the rule after the scope exits
    assert runtime.wildcards.sample == "s2"

    set_current()
    inferred = rule()
    with inferred:
        inferred.input(a="{sample}.tsv")
    inferred.input.b = "s1.tsv"
    assert inferred.wildcards.sample == "s1"


def test_canonical_block_is_written(tmp_path: Path):
    _, archive = run_source(tmp_path, BLOCK_SOURCE)
    assert "with transcript.rule() as r:  # transcript:rule" in archive
    assert '    r.input(\n        a="{sample}.tsv",\n    )' in archive
    assert '    r.output(\n        document="{sample}.tmd.py",\n    )' in archive
    assert "    r.params(\n        seed=1,\n    )" in archive
    assert "    r.threads = 4" in archive
    assert (
        '    r.resources(\n        mem_mb=8000,\n        runtime="2h",\n    )'
        in archive
    )
    assert (
        "    r.conda(\n"
        "        dependencies=[\n"
        '            "pandas=*",\n'
        "        ],\n"
        "        pip=[\n"
        '            "snakemake",\n'
        "        ],\n"
        "        channels=[\n"
        '            "conda-forge",\n'
        "        ],\n"
        "    )"
    ) in archive
    assert '    r.wildcards(\n        sample="s1",\n    )' in archive
    assert "PosixPath('s1.tsv')" in archive


def test_block_generation_is_idempotent(tmp_path: Path):
    for source in (BLOCK_SOURCE, SCATTER_SOURCE):
        _, first = run_source(tmp_path, source)
        _, second = run_source(tmp_path, first)
        assert first == second


def test_scattered_declarations_create_the_block(tmp_path: Path):
    _, archive = run_source(tmp_path, SCATTER_SOURCE)
    assert "with transcript.rule() as r:  # transcript:rule" in archive
    assert '    r.input(\n        a="{sample}.tsv",\n    )' in archive
    assert "    r.params(\n        seed=1,\n    )" in archive
    assert "    r.threads = 4" in archive
    assert (
        '    r.resources(\n        mem_mb=8000,\n        runtime="2h",\n    )'
        in archive
    )


def test_named_rule_is_kept_and_recorded_in_the_marker(tmp_path: Path):
    assert Rule("custom").name == "custom"
    source = """\
import transcript

r = transcript.rule("custom")
r.input.a = "a.tsv"
"""
    _, archive = run_source(tmp_path, source)
    assert "with r:  # transcript:rule custom:" in archive
    assert Rule.from_tmd(archive).name == "custom"


def test_rule_name_must_be_an_identifier():
    for name in ("", "1bad", "bad-name", "[", "a b"):
        with pytest.raises(WorkflowError, match="invalid rule name"):
            Rule(name)


def test_rule_marker_must_match_the_complete_pattern():
    source = """\
with r:  # transcript:rule invalid-name:
    pass
"""
    with pytest.raises(WorkflowError, match="No # transcript:rule block found"):
        Rule.from_tmd(source)


def test_cli_routes_to_the_declared_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(BLOCK_SOURCE, encoding="utf-8")
    result = run_cli(source)
    assert result.returncode == 0, result.stderr
    archive = tmp_path / "s1.tmd.py"
    assert archive.is_file()
    assert not (tmp_path / "report.tmd.py").exists()
    assert "PosixPath('s1.tsv')" in archive.read_text(encoding="utf-8")


def test_cli_wildcard_changes_the_resolved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(BLOCK_SOURCE, encoding="utf-8")
    result = run_cli(source, "--wildcards", "sample=s9")
    assert result.returncode == 0, result.stderr
    archive = (tmp_path / "s9.tmd.py").read_text(encoding="utf-8")
    assert "PosixPath('s9.tsv')" in archive
    assert '    r.wildcards(\n        sample="s1",\n    )' in archive


NO_DOCUMENT_SOURCE = """\
import transcript

with transcript.rule() as r:
    r.output(temp="{sample}.tmd.py")
    r.wildcards(sample="s1")
"""


HTML_DOCUMENT_SOURCE = """\
import transcript

with transcript.rule() as r:
    r.output(document="{sample}.html")
    r.wildcards(sample="s1")
"""


def test_cli_html_document_respects_the_html_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(HTML_DOCUMENT_SOURCE, encoding="utf-8")
    for flags, export_html in (((), True), (("--no-html",), False)):
        target = tmp_path / "s1.html"
        target.unlink(missing_ok=True)
        result = run_cli(source, *flags)
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "s1.tmd.py").is_file()
        assert target.exists() is export_html


def test_cli_html_forces_export_without_a_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(NO_DOCUMENT_SOURCE, encoding="utf-8")
    result = run_cli(source, "--html")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "report.tmd.py").is_file()
    assert (tmp_path / "report.html").is_file()


def test_document_must_be_declared_inside_the_rule_block():
    r = rule()
    with pytest.raises(WorkflowError, match="inside the rule block"):
        r.output.document = "x.tmd.py"
    with pytest.raises(WorkflowError, match="inside the rule block"):
        r.log.document = "x.log"


def test_cli_dash_o_records_a_wildcard_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(NO_DOCUMENT_SOURCE, encoding="utf-8")
    scenarios = (
        ("s2.tmd.py", "{sample}.tmd.py", False),
        ("s2.html", "{sample}.html", True),
    )
    for output, document, export_html in scenarios:
        result = run_cli(source, "--wildcards", "sample=s2", "-o", output)
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "s2.html").exists() is export_html
        archive = (tmp_path / "s2.tmd.py").read_text(encoding="utf-8")
        assert f'document="{document}"' in archive


def test_cli_dash_o_drops_a_concrete_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(BLOCK_SOURCE, encoding="utf-8")
    result = run_cli(source, "-o", "fixed.tmd.py")
    assert result.returncode == 0, result.stderr
    archive = (tmp_path / "fixed.tmd.py").read_text(encoding="utf-8")
    assert "document=" not in archive


def test_from_tmd_round_trips_the_block(tmp_path: Path):
    _, archive = run_source(tmp_path, BLOCK_SOURCE)
    job = Rule.from_tmd(archive)
    assert job.name is None
    assert str(job.input.a) == "s1.tsv"
    conda = job._conda
    assert conda is not None
    assert conda.dependencies == ["pandas=*"]
    assert conda.pip == ["snakemake"]
    assert conda.channels == ["conda-forge"]
    assert job._threads == 4
    assert job._resources == {"mem_mb": 8000, "runtime": "2h"}


def test_emit_rule_writes_a_fragment_and_conda(tmp_path: Path):
    source = tmp_path / "report.py"
    source.write_text(BLOCK_SOURCE, encoding="utf-8")
    target = tmp_path / "Snakefile"
    conda = tmp_path / "Snakefile.conda.yaml"
    result = run_cli(source, "--snakefile", str(target))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

    expected_fragment = (
        "rule report:\n"
        "    input:\n"
        '        a="{sample}.tsv",\n'
        f'        document="{source}",\n'
        "    output:\n"
        '        document="{sample}.tmd.py",\n'
        "    params:\n"
        "        seed=1,\n"
        "    threads: 4\n"
        "    resources:\n"
        "        mem_mb=8000,\n"
        '        runtime="2h",\n'
        "    conda:\n"
        f'        "{conda}"\n'
        "    shell:\n"
        '        "transcript {input.document:q} -o {output.document:q}'
        ' --wildcards sample={wildcards.sample:q}"\n'
    )
    assert target.read_text(encoding="utf-8") == expected_fragment

    expected_conda = (
        "channels:\n"
        "  - conda-forge\n"
        "dependencies:\n"
        "  - pandas=*\n"
        "  - pip:\n"
        "      - snakemake\n"
    )
    assert conda.read_text(encoding="utf-8") == expected_conda


def test_emit_rule_from_an_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "report.py"
    source.write_text(BLOCK_SOURCE, encoding="utf-8")
    assert run_cli(source).returncode == 0
    archive = tmp_path / "s1.tmd.py"
    target = tmp_path / "Snakefile"
    result = run_cli(archive, "--snakefile", str(target))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    fragment = target.read_text(encoding="utf-8")
    assert fragment.startswith("rule s1:\n")
    assert 'document="' in fragment and "s1.tmd.py" in fragment
    assert 'document="{sample}.tmd.py"' in fragment


def test_fragment_routes_a_paired_html_document():
    r = Rule()
    r._filename = "my-report.py"
    with r:
        r.output(tmd="{sample}.tmd.py", document="{sample}.html")
    fragment = r.make_snakemake_rule()
    assert fragment.startswith("rule my_report:\n")
    assert 'tmd="{sample}.tmd.py"' in fragment
    assert 'document="{sample}.html"' in fragment
    assert "-o {output.document:q}" in fragment


def test_fragment_document_target_branches():
    default = Rule()
    default._filename = "report.py"
    with default:
        default.output(o="report.tmd.py")
    assert "-o " not in default.make_snakemake_rule()

    log_target = Rule()
    log_target._filename = "report.py"
    with log_target:
        log_target.output(o="{sample}.tmd.py")
        log_target.log(document="{sample}.html")
    assert "-o {log.document:q}" in log_target.make_snakemake_rule()

    duplicate = Rule()
    with duplicate:
        duplicate.output(document="report.tmd.py")
        duplicate.log(document="report.tmd.py")
    with pytest.raises(WorkflowError, match="output or log"):
        duplicate.make_snakemake_rule()


def _values(container):
    return [value for _, value in container._raw_items()]


def test_out_of_block_literals_are_inferred_to_patterns():
    r = rule()
    with r:
        r.input(a="{sample}.tsv")
        r.output(report="{sample}.tmd.py")
    r.input.b = "s1.tsv"
    assert _values(r.input) == ["{sample}.tsv", "{sample}.tsv"]


def test_a_later_pattern_does_not_rewrite_an_earlier_literal():
    r = rule()
    with r:
        r.input("{sample}.tsv")
    r.input("s1.tsv")
    r.input("A.txt")
    with pytest.raises(WorkflowError, match="declared before"):
        r.input("{sample}.txt")
    assert _values(r.input) == ["{sample}.tsv", "A.txt"]


def test_reverse_substitution_handles_cyclic_values():
    r = rule()
    r.wildcards(ext="csv", csv="ext", input="aaa")
    r.input("csv.ext")
    assert _values(r.input) == ["{ext}.{csv}"]


def test_reverse_substitution_rejects_ambiguous_shared_values():
    r = rule()
    r.wildcards(a="x", b="x")
    with pytest.raises(WorkflowError, match="share the value"):
        r.input("x.tsv")
    assert _values(r.input) == []


def test_inferred_value_must_agree_with_declared_wildcards():
    r = rule()
    with r:
        r.input(a="{sample}.tsv")
    r.wildcards(sample="s1")
    r.input.b = "s9.tsv"
    assert _values(r.input) == ["{sample}.tsv", "s9.tsv"]
    with pytest.raises(WorkflowError, match="not 's10'"):
        r.input("s10.tsv")


def test_concrete_output_is_allowed_under_cli_wildcards(tmp_path: Path):
    r = rule()
    with ExecutionScope(tmp_path / "document.py", {"sample": "s1"}):
        r.output.report = "fixed.tmd.py"
    assert _values(r.output) == ["fixed.tmd.py"]


def test_output_and_log_must_share_one_wildcard_set():
    r = rule()
    r.wildcards(sample="s1", batch="b1")
    r.output.report = "{sample}.tmd.py"
    with pytest.raises(WorkflowError, match="output/log share"):
        r.log.run = "{batch}.log"


def test_params_threads_and_resources_allow_scattered_declarations():
    r = rule()
    r.params(seed=1)
    r.threads = 4
    r.resources(mem_mb=8000)
    with r:
        r.params(mode="fast")
        r.threads = 4
        r.resources(mem_mb=8000)
    r.params.label = "result"
    r.threads = 4
    r.resources(runtime="2h")

    assert r.params.seed == 1
    assert r.params.mode == "fast"
    assert r.params.label == "result"
    assert r._threads == 4
    assert r._resources == {"mem_mb": 8000, "runtime": "2h"}

    with pytest.raises(WorkflowError, match="already declared as 4"):
        r.threads = 8
    with pytest.raises(WorkflowError, match="already declared as 8000"):
        r.resources(mem_mb=1200)


def test_snakemake_wildcard_constraints_are_used_for_names_and_resolution():
    r = rule()
    r.wildcards(sample="ABC")
    r.output.report = "{sample,[A-Z]+}.tmd.py"
    assert r.wildcard_names() == {"sample"}
    assert str(r.output.report) == "ABC.tmd.py"


def test_threads_must_be_a_positive_integer():
    r = rule()
    for value in (0, -1, True, 1.5, "4"):
        with pytest.raises(WorkflowError, match="positive integer"):
            r.threads = value  # type: ignore


LAMBDA_SOURCE = """\
import transcript

with transcript.rule() as r:
    r.input(data="{sample}.tsv")
    r.output(document="{sample}.tmd.py")
    r.params(
        selected=lambda wildcards, input: [
            path.upper() for path in input if wildcards.sample in path
        ],
        raw=lambda wildcards: "{literal}",
    )
    r.wildcards(sample="s1")

if "transcript.md":
    r.params.selected
    r.params.raw
"""


def test_params_lambdas_round_trip_and_are_not_evaluated_when_read(tmp_path: Path):
    _, first = run_source(tmp_path, LAMBDA_SOURCE)
    assert "selected=lambda wildcards, input: [" in first
    assert "raw=lambda wildcards: '{literal}'" in first
    assert "['S1.TSV']" in first
    assert "'{literal}'" in first

    job = Rule.from_tmd(first)
    fragment = job.make_snakemake_rule()
    assert "selected=lambda wildcards, input: [" in fragment
    assert "raw=lambda wildcards: '{literal}'" in fragment

    _, second = run_source(tmp_path, first)
    assert second == first

    broken = """\
with r:  # transcript:rule
    r.output(
        document="report.tmd.py",
    )
    r.params(
        broken=lambda wildcards: 1 / 0,
    )
"""
    static = Rule.from_tmd(broken)
    assert "broken=lambda wildcards: 1 / 0" in static.make_snakemake_rule()


def test_multiple_params_lambdas_on_one_line_are_identified(tmp_path: Path):
    source = """\
import transcript

with transcript.rule() as r:
    r.params(one=lambda wildcards: 1, two=lambda wildcards: 2)
"""
    _, archive = run_source(tmp_path, source)
    assert "one=lambda wildcards: 1" in archive
    assert "two=lambda wildcards: 2" in archive


def test_lambda_must_be_defined_inside_the_rule_block(tmp_path: Path):
    sources = (
        """\
import transcript

r = transcript.rule()
r.params(value=lambda wildcards: 1)

with r:
    r.output(document="report.tmd.py")
""",
        """\
import transcript

with transcript.rule() as r:
    r.output(document="report.tmd.py")

r.params(value=lambda wildcards: 1)
""",
        """\
import transcript

value = lambda wildcards: 1

with transcript.rule() as r:
    r.params(value=value)
""",
    )
    for source in sources:
        with pytest.raises(WorkflowError, match="inside the rule block"):
            run_source(tmp_path, source)


def test_lambda_without_a_document_index_is_accepted():
    r = rule()
    r.params(value=lambda wildcards: 1)
    assert r.params.value == 1


def test_standalone_rule_block_releases_the_current_rule():
    r = rule()
    with r:
        r.output(document="report.tmd.py")
    assert current() is None


def test_plain_python_runs_a_rule_block_with_a_lambda(tmp_path: Path):
    source = """\
import transcript

with transcript.rule() as r:
    r.output(document="report.tmd.py")
    r.params(value=lambda wildcards: 1)

assert r.params.value == 1
"""
    path = tmp_path / "plain.py"
    path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_input_lambda_uses_wildcards_and_round_trips(tmp_path: Path):
    source = """\
import transcript

with transcript.rule() as r:
    r.input(
        one=lambda wildcards: f"{wildcards.sample}.tsv",
        many=lambda wildcards: [
            f"{wildcards.sample}.csv",
            f"{wildcards.sample}.json",
        ],
    )
    r.output(document="{sample}.tmd.py")
    r.wildcards(sample="s1")

if "transcript.md":
    r.input.one
    r.input.many
"""
    _, first = run_source(tmp_path, source)
    assert "one=lambda wildcards: f'{wildcards.sample}.tsv'" in first
    assert "many=lambda wildcards: [" in first
    assert "PosixPath('s1.tsv')" in first
    assert "[PosixPath('s1.csv'), PosixPath('s1.json')]" in first

    job = Rule.from_tmd(first)
    fragment = job.make_snakemake_rule()
    assert "one=lambda wildcards: f'{wildcards.sample}.tsv'" in fragment
    assert "many=lambda wildcards: [" in fragment

    _, second = run_source(tmp_path, first)
    assert second == first


def test_input_lambda_return_value_must_contain_paths(tmp_path: Path):
    source = """\
import transcript

with transcript.rule() as r:
    r.input(value=lambda wildcards: 1)

r.input.value
"""
    with pytest.raises(WorkflowError, match="path or an iterable of paths"):
        run_source(tmp_path, source)


def test_params_lambda_rejects_non_static_forms(tmp_path: Path):
    cases = (
        ("lambda wildcards: suffix", "external names: suffix"),
        ("lambda wildcards: len(wildcards.sample)", "external names: len"),
        ("lambda wildcards: (value := wildcards.sample)", "assignment expression"),
        ("lambda wildcards: lambda wildcards: 1", "another lambda"),
        ("lambda: 1", "first positional parameter"),
        ("lambda wildcards, **kwargs: 1", "cannot use .*kwargs"),
        ("lambda wildcards, other: other", "unsupported parameters: other"),
    )
    for expression, message in cases:
        source = f"""\
import transcript

suffix = ".txt"
with transcript.rule() as r:
    r.params(value={expression})
"""
        with pytest.raises(WorkflowError, match=message):
            run_source(tmp_path, source)


def test_interactive_params_lambda_receives_snakemake_aux_context():
    r = rule()
    r.threads = 4
    r.resources(mem_mb=8000)
    r.params(
        threads_value=lambda wildcards, threads: threads,
        resources_value=lambda wildcards, resources: resources,
    )
    assert r.params.threads_value == 4
    assert r.params.resources_value == {"mem_mb": 8000}
