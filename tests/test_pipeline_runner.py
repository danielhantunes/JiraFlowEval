"""Unit tests for evaluator.pipeline_runner (pure helpers)."""

from pathlib import Path

import pytest

from evaluator import pipeline_runner as pr


def test_find_entrypoint_root_main_py(tmp_path):
    """Finds main.py at repo root."""
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    result = pr._find_entrypoint(tmp_path)
    assert result is not None
    path, is_module = result
    assert path.name == "main.py"
    assert is_module is False


def test_find_entrypoint_run_pipeline_py(tmp_path):
    """Finds run_pipeline.py when main.py absent."""
    (tmp_path / "run_pipeline.py").write_text("", encoding="utf-8")
    result = pr._find_entrypoint(tmp_path)
    assert result is not None
    path, is_module = result
    assert path.name == "run_pipeline.py"
    assert is_module is False


def test_find_entrypoint_module(tmp_path):
    """Finds src/main.py as module."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("", encoding="utf-8")
    result = pr._find_entrypoint(tmp_path)
    assert result is not None
    path, is_module = result
    assert is_module is True
    assert "src" in str(path)


def test_find_entrypoint_none(tmp_path):
    """No entrypoint returns None."""
    (tmp_path / "other.py").write_text("", encoding="utf-8")
    assert pr._find_entrypoint(tmp_path) is None


def test_gold_has_csv_no_dir(tmp_path):
    """No data/gold dir -> False."""
    assert pr._gold_has_csv(tmp_path) is False


def test_gold_has_csv_empty_dir(tmp_path):
    """data/gold with no CSV -> False."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True)
    assert pr._gold_has_csv(tmp_path) is False


def test_gold_has_csv_with_csv(tmp_path):
    """data/gold with at least one CSV -> True."""
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True)
    (gold / "report.csv").write_text("a,b\n1,2", encoding="utf-8")
    assert pr._gold_has_csv(tmp_path) is True


def test_entrypoint_to_cmd_string_script(tmp_path):
    """Script entrypoint -> 'python main.py'."""
    entry = tmp_path / "main.py"
    cmd = pr._entrypoint_to_cmd_string(entry, tmp_path, is_module=False)
    assert cmd == "python main.py"


def test_entrypoint_to_cmd_string_module(tmp_path):
    """Module entrypoint -> 'python -m src.main'."""
    entry = tmp_path / "src" / "main.py"
    entry.parent.mkdir(parents=True)
    entry.touch()
    cmd = pr._entrypoint_to_cmd_string(entry, tmp_path, is_module=True)
    assert "python -m" in cmd
    assert "src.main" in cmd
