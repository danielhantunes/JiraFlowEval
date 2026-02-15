"""Integration test: full evaluate flow with mocked clone, pipeline, and LLM."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from evaluator.cli import evaluate
from evaluator.spreadsheet import REPO_URL_COL, RESULT_COLUMNS


@pytest.fixture
def minimal_repo(tmp_path):
    """A minimal repo dir with main.py (no real run)."""
    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    return tmp_path


def test_evaluate_integration_mocked(
    sample_excel_path,
    minimal_repo,
    tmp_path,
    monkeypatch,
):
    """Run evaluate with mocked clone and pipeline; output Excel has expected columns."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    output_name = "test_results.xlsx"
    out_path = tmp_path / "output" / output_name

    def fake_clone(url):
        return minimal_repo

    def fake_run_pipeline(repo_path, run_command_override=None):
        return {
            "pipeline_runs": True,
            "gold_generated": True,
            "error": None,
            "stdout": "",
            "stderr": "",
            "return_code": 0,
        }

    def fake_llm(context):
        return {
            "medallion_architecture": 3,
            "sla_logic": 3,
            "pipeline_organization": 3,
            "readme_clarity": 4,
            "code_quality": 3,
            "summary": "Test summary.",
        }

    with (
        patch("evaluator.cli.clone_repo", side_effect=fake_clone),
        patch("evaluator.cli.run_pipeline", side_effect=fake_run_pipeline),
        patch("evaluator.cli.evaluate_with_llm", side_effect=fake_llm),
    ):
        evaluate(file=sample_excel_path, output_name=output_name)

    assert out_path.exists()
    df = pd.read_excel(out_path, engine="openpyxl")
    for col in RESULT_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"
    assert REPO_URL_COL in df.columns
    assert len(df) == 2
    assert df["final_score"].notna().all()
