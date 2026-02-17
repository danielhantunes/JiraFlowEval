"""Unit tests for evaluator.security_scorer."""

from pathlib import Path

import pytest

from evaluator.security_scorer import compute_security_score


def test_security_score_no_repo(tmp_path):
    """Empty dir: no hardcoded, no env, no .env → partial score."""
    score = compute_security_score(tmp_path)
    assert 0 <= score <= 100
    # No .env, no hardcoded, no config with secrets; may have 0 env usage and 0 gitignore
    assert score >= 40  # at least no hardcoded + .env "ok" (no .env)


def test_security_score_env_ignored(tmp_path):
    """ .env in .gitignore → env_ignored points."""
    (tmp_path / ".gitignore").write_text(".env\n.env.local\n", encoding="utf-8")
    (tmp_path / ".env").write_text("KEY=value", encoding="utf-8")
    score = compute_security_score(tmp_path)
    assert score >= 15  # .env ignored gives 15


def test_security_score_env_not_ignored_penalty(tmp_path):
    """ .env exists and not in .gitignore → no env_ignored points."""
    (tmp_path / ".env").write_text("KEY=value", encoding="utf-8")
    # No .gitignore or .gitignore without .env
    score = compute_security_score(tmp_path)
    # Should not get the 15 pts for .env ignored
    assert score < 55  # 40 (no hardcoded) + 15 (env ignored) = 55 if we had both; we miss 15


def test_security_score_hardcoded_reduces(tmp_path):
    """Hardcoded api_key → no 'no hardcoded' points."""
    (tmp_path / "main.py").write_text('api_key = "sk-12345678901234567890"', encoding="utf-8")
    score = compute_security_score(tmp_path)
    assert score < 40  # we lose the 40 pts


def test_security_score_env_usage_increases(tmp_path):
    """os.getenv in code → env usage points."""
    (tmp_path / "main.py").write_text('import os; x = os.getenv("API_KEY")', encoding="utf-8")
    score = compute_security_score(tmp_path)
    assert score >= 20  # at least env vars 20


def test_security_score_gitignore_entries(tmp_path):
    """ .gitignore with .env and *.key → gitignore points."""
    (tmp_path / ".gitignore").write_text(".env\n*.key\nsecrets.json\n", encoding="utf-8")
    score = compute_security_score(tmp_path)
    assert score >= 15  # gitignore security entries

