"""Pytest fixtures for JiraFlowEval tests."""

import os
from pathlib import Path

import pandas as pd
import pytest

from evaluator.spreadsheet import REPO_URL_COL, RESULT_COLUMNS


@pytest.fixture
def temp_dir(tmp_path):
    """A temporary directory for test files."""
    return tmp_path


@pytest.fixture
def sample_excel_path(tmp_path):
    """Path to a minimal valid Excel file with repo_url column."""
    path = tmp_path / "repos.xlsx"
    df = pd.DataFrame([{REPO_URL_COL: "https://github.com/user/repo1"}, {REPO_URL_COL: "https://github.com/org/repo2"}])
    df.to_excel(path, index=False, engine="openpyxl")
    return path


@pytest.fixture
def empty_repo_url_excel(tmp_path):
    """Excel with repo_url column but no valid URLs (empty / NaN)."""
    path = tmp_path / "empty.xlsx"
    df = pd.DataFrame([{REPO_URL_COL: ""}, {REPO_URL_COL: None}])
    df.to_excel(path, index=False, engine="openpyxl")
    return path


@pytest.fixture
def sample_config_yaml(tmp_path):
    """Path to a minimal scoring.yaml."""
    path = tmp_path / "scoring.yaml"
    path.write_text(
        "weights:\n  pipeline_runs: 3\n  gold_generated: 2\n  medallion_architecture: 3\n"
        "normalization:\n  max_score: 10\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    """Use temp paths for output/config so tests don't touch real dirs."""
    monkeypatch.setenv("TEMP_REPOS_DIR", str(tmp_path / "temp_repos"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("REPO_EVALUATOR_ROOT", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "scoring.yaml").write_text(
        "weights:\n  pipeline_runs: 3\n  gold_generated: 2\nnormalization:\n  max_score: 10\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCORING_CONFIG_PATH", str(config_dir / "scoring.yaml"))
