"""Unit tests for evaluator.scoring."""

from pathlib import Path

import pytest

from evaluator.scoring import (
    BOOL_METRICS,
    DEFAULT_MAX_SCORE,
    DEFAULT_SUMMARY_MAX_CHARS,
    DEFAULT_WEIGHTS,
    compute_final_score,
    load_config,
    metric_value,
)


def test_load_config_missing_file(monkeypatch, tmp_path):
    """When config file does not exist, defaults are returned."""
    monkeypatch.setenv("REPO_EVALUATOR_ROOT", str(tmp_path))
    monkeypatch.setenv("SCORING_CONFIG_PATH", str(tmp_path / "nonexistent.yaml"))
    config = load_config()
    assert config["weights"] == DEFAULT_WEIGHTS
    assert config["normalization"]["max_score"] == DEFAULT_MAX_SCORE
    assert config["normalization"]["summary_max_chars"] == DEFAULT_SUMMARY_MAX_CHARS


def test_load_config_from_path(sample_config_yaml):
    """When config exists, it is loaded and merged with defaults."""
    config = load_config(config_path=sample_config_yaml)
    assert config["weights"]["pipeline_runs"] == 3
    assert config["weights"]["medallion_architecture"] == 3
    assert config["normalization"]["max_score"] == 10
    assert config["normalization"]["summary_max_chars"] == DEFAULT_SUMMARY_MAX_CHARS


def test_load_config_summary_max_chars_custom(tmp_path):
    """summary_max_chars can be set in config file."""
    path = tmp_path / "scoring.yaml"
    path.write_text("normalization:\n  max_score: 100\n  summary_max_chars: 1200\n", encoding="utf-8")
    config = load_config(config_path=path)
    assert config["normalization"]["summary_max_chars"] == 1200


def test_metric_value_bool_metrics():
    """Bool metrics map True/yes/1 -> 5, False/empty -> 0."""
    assert metric_value(True, "pipeline_runs") == 5.0
    assert metric_value(False, "pipeline_runs") == 0.0
    assert metric_value(1, "gold_generated") == 5.0
    assert metric_value("yes", "gold_generated") == 5.0
    assert metric_value(None, "pipeline_runs") == 0.0


def test_metric_value_numeric_clamped():
    """Numeric metrics: 0-5 scale passed through; >5 treated as 0-100 and scaled to 0-5."""
    assert metric_value(3, "code_quality") == 3.0
    assert metric_value(100, "readme_clarity") == 5.0
    assert metric_value(80, "medallion_architecture") == 4.0
    assert metric_value(-1, "sla_logic") == 0.0


def test_compute_final_score_all_zeros():
    """All zero metrics -> 0 score."""
    metrics = {k: 0 for k in DEFAULT_WEIGHTS}
    score = compute_final_score(metrics, DEFAULT_WEIGHTS, max_score=100.0)
    assert score == 0.0


def test_compute_final_score_all_max():
    """All max values -> max_score. Use True for bool metrics, 5 for numeric."""
    weights = {"pipeline_runs": 1, "gold_generated": 1, "code_quality": 1}
    metrics = {"pipeline_runs": True, "gold_generated": True, "code_quality": 5}
    score = compute_final_score(metrics, weights, max_score=100.0)
    assert score == 100.0


def test_compute_final_score_mixed():
    """Mixed metrics produce scaled score (0-100 range)."""
    metrics = {
        "pipeline_runs": True,
        "gold_generated": True,
        "medallion_architecture": 3,
        "sla_logic": 4,
        "pipeline_organization": 2,
        "readme_clarity": 5,
        "code_quality": 3,
        "cloud_ingestion": 3,
        "naming_conventions_score": 4,
        "security_practices_score": 4,
    }
    score = compute_final_score(metrics, DEFAULT_WEIGHTS, max_score=100.0)
    assert 0 < score < 100
    assert isinstance(score, float)
