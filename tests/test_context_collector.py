"""Unit tests for evaluator.context_collector."""

from pathlib import Path

import pytest

from evaluator.context_collector import collect_context, context_to_string


def test_context_to_string_includes_sections():
    """context_to_string includes README, tree, naming audit, sla, pipeline, execution."""
    context = {
        "readme": "Hello",
        "project_tree": "├── main.py",
        "naming_audit": "folder: src/",
        "sla_calculation": "def sla(): ...",
        "main_pipeline": "print(1)",
        "execution_summary": {"pipeline_runs": True},
    }
    s = context_to_string(context)
    assert "README" in s
    assert "Project tree" in s
    assert "Naming audit" in s
    assert "sla_calculation" in s
    assert "Main pipeline" in s
    assert "Execution summary" in s
    assert "Hello" in s
    assert "True" in s


def test_collect_context_empty_dir(tmp_path):
    """Empty repo dir yields empty readme/tree, execution from result."""
    result = {"pipeline_runs": False, "gold_generated": False, "return_code": 1, "error": "fail"}
    ctx = collect_context(tmp_path, result)
    assert ctx["readme"] == ""
    assert "execution_summary" in ctx
    assert ctx["execution_summary"]["pipeline_runs"] is False
    assert ctx["execution_summary"]["error"] == "fail"


def test_collect_context_reads_readme(tmp_path):
    """README.md content is read and truncated if long."""
    (tmp_path / "README.md").write_text("Short readme.", encoding="utf-8")
    ctx = collect_context(tmp_path, {})
    assert "Short readme" in ctx["readme"]


def test_collect_context_finds_main_pipeline(tmp_path):
    """Finds main.py or run_pipeline.py as main_pipeline."""
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    ctx = collect_context(tmp_path, {})
    assert "print" in ctx["main_pipeline"]
