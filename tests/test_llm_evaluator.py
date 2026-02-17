"""Unit tests for evaluator.llm_evaluator (report generation)."""

from unittest.mock import MagicMock, patch

import pytest

from evaluator.llm_evaluator import (
    generate_detailed_report,
    format_docker_results_for_summary,
    SUMMARY_USER_TEMPLATE,
)


def test_generate_detailed_report_no_api_key(monkeypatch):
    """When OPENAI_API_KEY is not set, returns fallback message."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    context = {"readme": "", "project_tree": "x", "execution_summary": {}}
    scores = {"final_score": 70, "medallion_architecture": 80}
    out = generate_detailed_report(context, scores)
    assert "not generated" in out.lower() or "OPENAI_API_KEY" in out


def test_generate_detailed_report_success(monkeypatch):
    """When API returns content, returns report text."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    context = {"readme": "Hi", "project_tree": "tree", "execution_summary": {}}
    scores = {"final_score": 72, "medallion_architecture": 80, "summary": "Short."}

    fake_content = "## Executive summary\n\nThis repo implements a Medallion pipeline."

    with patch("evaluator.llm_evaluator.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = fake_content
        mock_client.chat.completions.create.return_value = mock_response

        out = generate_detailed_report(context, scores)

    assert "Executive summary" in out
    assert "Medallion" in out


def test_format_docker_results_for_summary_none():
    """When run_result is None, return message that no Docker run was performed."""
    out = format_docker_results_for_summary(None)
    assert "No Docker run performed" in out


def test_format_docker_results_for_summary_with_result():
    """Docker results include pipeline ran, return code, gold generated; only use provided data."""
    run_result = {
        "pipeline_runs": True,
        "gold_generated": True,
        "return_code": 0,
        "error": None,
        "stdout": "ok",
        "stderr": "",
    }
    out = format_docker_results_for_summary(run_result)
    assert "Pipeline ran: Yes" in out
    assert "Return code: 0" in out
    assert "Gold/reports generated: Yes" in out
    assert "Stdout:" in out


def test_summary_user_template_includes_sections():
    """Summary prompt template has placeholders for scores, flags, docker_results, and max_chars."""
    assert "{scores}" in SUMMARY_USER_TEMPLATE
    assert "{flags}" in SUMMARY_USER_TEMPLATE
    assert "{docker_results}" in SUMMARY_USER_TEMPLATE
    assert "{max_chars}" in SUMMARY_USER_TEMPLATE
    assert "Docker" in SUMMARY_USER_TEMPLATE
    assert "Do not change" in SUMMARY_USER_TEMPLATE or "do not" in SUMMARY_USER_TEMPLATE.lower()
