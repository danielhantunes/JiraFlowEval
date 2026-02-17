"""Unit tests for evaluator.pipeline_runner (pure helpers)."""

from pathlib import Path
from unittest.mock import patch

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


def test_repo_uses_azure_ingestion_false(tmp_path):
    """No Azure markers -> False."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ingestion").mkdir()
    (tmp_path / "src" / "ingestion" / "ingest_raw.py").write_text(
        "def ingest(): pass  # local file only", encoding="utf-8"
    )
    assert pr._repo_uses_azure_ingestion(tmp_path) is False


def test_repo_uses_azure_ingestion_true(tmp_path):
    """Azure marker in ingestion code -> True."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ingestion").mkdir()
    (tmp_path / "src" / "ingestion" / "ingest_raw.py").write_text(
        "from azure.storage.blob import BlobServiceClient", encoding="utf-8"
    )
    assert pr._repo_uses_azure_ingestion(tmp_path) is True


def test_get_repo_raw_input_filename_from_env_example(tmp_path):
    """Read RAW_INPUT_FILENAME from .env.example."""
    (tmp_path / ".env.example").write_text(
        "RAW_INPUT_FILENAME=issues.json\nOTHER=x", encoding="utf-8"
    )
    assert pr._get_repo_raw_input_filename(tmp_path) == "issues.json"


def test_get_repo_raw_input_filename_from_python(tmp_path):
    """Read default from getenv in config."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "utils").mkdir()
    (tmp_path / "src" / "utils" / "config.py").write_text(
        'RAW_INPUT_FILENAME = os.getenv("RAW_INPUT_FILENAME", "tickets_raw.json")',
        encoding="utf-8",
    )
    assert pr._get_repo_raw_input_filename(tmp_path) == "tickets_raw.json"


def test_get_repo_raw_input_filename_default(tmp_path, monkeypatch):
    """No config and no env -> default filename."""
    monkeypatch.delenv("RAW_INPUT_FILENAME", raising=False)
    assert pr._get_repo_raw_input_filename(tmp_path) == "tickets_raw.json"


def test_require_raw_input_file_exists_azure_skipped(tmp_path):
    """Repo with Azure ingestion skips file check."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ingestion").mkdir()
    (tmp_path / "src" / "ingestion" / "ingest.py").write_text("azure blob", encoding="utf-8")
    assert pr._require_raw_input_file_exists(tmp_path) is None


def test_require_raw_input_file_exists_has_file(tmp_path):
    """Local ingestion with file present -> None."""
    filename = pr._get_repo_raw_input_filename(tmp_path)
    (tmp_path / filename).write_text("{}", encoding="utf-8")
    assert pr._require_raw_input_file_exists(tmp_path) is None


def test_require_raw_input_file_exists_missing_file(tmp_path):
    """Local ingestion without file -> error message."""
    err = pr._require_raw_input_file_exists(tmp_path)
    assert err is not None
    expected_name = pr._get_repo_raw_input_filename(tmp_path)
    assert expected_name in err
    assert "missing" in err.lower() or "required" in err.lower()


def test_run_pipeline_skips_when_raw_file_missing(tmp_path):
    """run_pipeline returns error and does not run Docker when local repo has no raw file."""
    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    with patch.object(pr, "_run_in_docker") as mock_docker:
        result = pr.run_pipeline(tmp_path)
    assert result["pipeline_runs"] is False
    assert result["error"] is not None
    expected_name = pr._get_repo_raw_input_filename(tmp_path)
    assert expected_name in result["error"]
    mock_docker.assert_not_called()
