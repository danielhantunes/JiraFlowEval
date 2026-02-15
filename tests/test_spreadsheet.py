"""Unit tests for evaluator.spreadsheet."""

from pathlib import Path

import pandas as pd
import pytest

from evaluator.spreadsheet import (
    REPO_URL_COL,
    RESULT_COLUMNS,
    build_result_row,
    get_repo_rows,
    load_input,
    write_results,
)


def test_load_input_success(sample_excel_path):
    """Load valid Excel with repo_url returns DataFrame."""
    df = load_input(sample_excel_path)
    assert REPO_URL_COL in df.columns
    assert len(df) == 2


def test_load_input_file_not_found():
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_input(Path("/nonexistent/repos.xlsx"))


def test_load_input_missing_column(tmp_path):
    """Excel without repo_url raises ValueError."""
    path = tmp_path / "bad.xlsx"
    pd.DataFrame([{"name": "a", "email": "b"}]).to_excel(path, index=False, engine="openpyxl")
    with pytest.raises(ValueError, match="Missing required column"):
        load_input(path)


def test_get_repo_rows_empty(empty_repo_url_excel):
    """Rows with empty/NaN repo_url are filtered out."""
    df = pd.read_excel(empty_repo_url_excel, engine="openpyxl")
    rows = get_repo_rows(df)
    assert len(rows) == 0


def test_get_repo_rows_from_sample(sample_excel_path):
    """Valid URLs are returned as list of dicts."""
    df = load_input(sample_excel_path)
    rows = get_repo_rows(df)
    assert len(rows) == 2
    assert rows[0][REPO_URL_COL] == "https://github.com/user/repo1"


def test_build_result_row():
    """Original row is merged with result columns."""
    original = {"repo_url": "https://x.com/y", "name": "Alice"}
    result = {"final_score": 7.5, "summary": "Good.", "pipeline_runs": True}
    row = build_result_row(original, result)
    assert row["repo_url"] == "https://x.com/y"
    assert row["name"] == "Alice"
    assert row["final_score"] == 7.5
    assert row["summary"] == "Good."
    assert row["pipeline_runs"] is True
    for col in RESULT_COLUMNS:
        assert col in row


def test_write_results_creates_file(tmp_path):
    """write_results creates Excel at path and parent dirs."""
    out = tmp_path / "subdir" / "out.xlsx"
    rows = [
        {"repo_url": "https://a.com/b", "final_score": 8.0, "summary": "Ok"},
    ]
    write_results(rows, out)
    assert out.exists()
    df = pd.read_excel(out, engine="openpyxl")
    assert "repo_url" in df.columns
    assert len(df) == 1
