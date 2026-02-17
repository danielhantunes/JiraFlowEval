"""Unit tests for evaluator.detectors (deterministic presence-based checks)."""

from pathlib import Path

import pytest

from evaluator.detectors import (
    CHECK_REGISTRY,
    CHECK_ID_TO_IMPROVEMENT,
    build_suggested_improvements,
    compute_dimension_scores,
    run_checks,
    build_deterministic_summary,
    build_deterministic_evaluation_report,
    build_deterministic_evaluation_report_compact,
)


def test_run_checks_returns_dict(tmp_path):
    """run_checks returns a dict of check_id -> bool."""
    result = run_checks(tmp_path)
    assert isinstance(result, dict)
    check_ids = {c[1] for c in CHECK_REGISTRY}
    assert set(result.keys()) == check_ids
    assert all(isinstance(v, bool) for v in result.values())


def test_compute_dimension_scores_deterministic(tmp_path):
    """Same check results produce same dimension scores."""
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "bronze").mkdir(parents=True)
    (tmp_path / "data" / "silver").mkdir(parents=True)
    (tmp_path / "data" / "gold").mkdir(parents=True)
    (tmp_path / "main.py").write_text("from x import run_bronze, run_silver, run_gold", encoding="utf-8")
    r1 = run_checks(tmp_path)
    s1 = compute_dimension_scores(r1)
    r2 = run_checks(tmp_path)
    s2 = compute_dimension_scores(r2)
    assert s1 == s2
    assert s1["medallion_architecture"] == 100


def test_compute_dimension_scores_partial(tmp_path):
    """Only some checks pass -> partial score."""
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "bronze").mkdir(parents=True)
    result = run_checks(tmp_path)
    scores = compute_dimension_scores(result)
    assert scores["medallion_architecture"] == 40
    assert 0 <= scores["medallion_architecture"] <= 100


def test_python_files_snake_case_allows_init(tmp_path):
    """__init__.py and __main__.py are allowed; only user modules must be snake_case."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    result = run_checks(tmp_path)
    assert result["python_files_snake_case"] is True
    (tmp_path / "src" / "ProcessData.py").write_text("", encoding="utf-8")
    result = run_checks(tmp_path)
    assert result["python_files_snake_case"] is False


def test_no_pii_in_source_files_pass(tmp_path):
    """no_pii_in_source_files passes when no email or phone in .py under src/, ingestion/, or root."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1  # no pii", encoding="utf-8")
    result = run_checks(tmp_path)
    assert result["no_pii_in_source_files"] is True
    scores = compute_dimension_scores(result)
    assert scores["sensitive_data_exposure_score"] == 100


def test_no_pii_in_source_files_fail_email(tmp_path):
    """no_pii_in_source_files fails when a source file contains an email."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("contact = 'user@example.com'", encoding="utf-8")
    result = run_checks(tmp_path)
    assert result["no_pii_in_source_files"] is False
    scores = compute_dimension_scores(result)
    assert scores["sensitive_data_exposure_score"] == 0


def test_no_pii_in_source_files_fail_phone(tmp_path):
    """no_pii_in_source_files fails when a source file contains a phone number."""
    (tmp_path / "main.py").write_text("phone = '(123) 456-7890'", encoding="utf-8")
    result = run_checks(tmp_path)
    assert result["no_pii_in_source_files"] is False


def test_gold_has_parquet_check(tmp_path):
    """gold_has_parquet passes when data/gold contains .parquet file; contributes to sla_logic."""
    (tmp_path / "data" / "gold").mkdir(parents=True)
    result = run_checks(tmp_path)
    assert result["gold_has_parquet"] is False
    (tmp_path / "data" / "gold" / "report.parquet").write_bytes(b"\x00")
    result = run_checks(tmp_path)
    assert result["gold_has_parquet"] is True
    scores = compute_dimension_scores(result)
    assert scores["sla_logic"] == 20  # only gold_has_parquet passes (1 of 5 × 20)


def test_build_deterministic_summary():
    """Summary includes check count and dimension scores."""
    check_results = {"has_readme": True, "has_main": True}
    dimension_scores = {"medallion_architecture": 60, "sla_logic": 75}
    s = build_deterministic_summary(check_results, dimension_scores, True, True, None)
    assert "2/2 checks passed" in s or "checks passed" in s
    assert "60" in s or "75" in s


def test_build_deterministic_evaluation_report():
    """Report is deterministic and contains expected sections (no subjective content)."""
    check_results = {check_id: False for _d, check_id, _w in CHECK_REGISTRY}
    check_results["has_raw_layer"] = True
    scores = {
        "final_score": 25,
        "medallion_architecture": 20,
        "sla_logic": 0,
        "pipeline_organization": 0,
        "readme_clarity": 0,
        "code_quality": 0,
        "naming_conventions_score": 0,
        "cloud_ingestion": 0,
        "security_practices_score": 50,
        "sensitive_data_exposure_score": 0,
        "pipeline_runs": False,
        "gold_generated": False,
    }
    report = build_deterministic_evaluation_report(check_results, scores)
    assert "## Executive summary" in report
    assert "25/100" in report
    assert "Presence-based checks" in report
    assert "## Architecture (medallion layers)" in report
    assert "## Sensitive data (PII)" in report
    assert "## Score justification (presence-based)" in report
    assert "No subjective scoring" in report
    assert "## Suggested Improvements" in report
    assert "Add a raw layer" not in report  # has_raw_layer passed
    assert "Add a bronze layer" in report or "Add a gold layer" in report  # many failed
    # Same inputs -> same output
    report2 = build_deterministic_evaluation_report(check_results, scores)
    assert report == report2


def test_build_suggested_improvements():
    """Suggested improvements list is derived only from failed checks."""
    all_pass = {check_id: True for _d, check_id, _w in CHECK_REGISTRY}
    assert build_suggested_improvements(all_pass) == []
    all_fail = {check_id: False for _d, check_id, _w in CHECK_REGISTRY}
    suggestions = build_suggested_improvements(all_fail)
    assert len(suggestions) == len(CHECK_ID_TO_IMPROVEMENT)
    assert any("snake_case" in s for s in suggestions)
    assert any("raw layer" in s for s in suggestions)


def test_build_deterministic_evaluation_report_compact_under_limit():
    """Compact report stays under max_chars by design (no truncation)."""
    check_results = {check_id: True for _d, check_id, _w in CHECK_REGISTRY}
    scores = {
        "final_score": 75,
        "medallion_architecture": 100,
        "sla_logic": 80,
        "pipeline_organization": 100,
        "readme_clarity": 60,
        "code_quality": 67,
        "naming_conventions_score": 75,
        "cloud_ingestion": 0,
        "security_practices_score": 70,
        "sensitive_data_exposure_score": 100,
        "pipeline_runs": True,
        "gold_generated": True,
    }
    for max_chars in (1800, 500, 300):
        report = build_deterministic_evaluation_report_compact(check_results, scores, max_chars=max_chars)
        assert len(report) <= max_chars, f"Compact report length {len(report)} > {max_chars}"
        assert "Final score" in report or "Checks:" in report
        assert "75" in report
    # With all checks passing we still get cloud suggestion (cloud_ingestion=0); section may appear
    report_1800 = build_deterministic_evaluation_report_compact(check_results, scores, max_chars=1800)
    assert "Suggested Improvements" in report_1800 or "Cloud:" in report_1800
