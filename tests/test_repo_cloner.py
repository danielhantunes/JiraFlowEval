"""Unit tests for evaluator.repo_cloner."""

import pytest

from evaluator.repo_cloner import repo_name_from_url


def test_repo_name_from_url_https():
    """https://github.com/user/repo -> user_repo."""
    assert repo_name_from_url("https://github.com/user/repo") == "user_repo"
    assert repo_name_from_url("https://github.com/org/project-name") == "org_project-name"


def test_repo_name_from_url_with_git_suffix():
    """URL ending in .git is normalized."""
    assert repo_name_from_url("https://github.com/a/b.git") == "a_b"


def test_repo_name_from_url_ssh():
    """git@github.com:user/repo.git -> user_repo."""
    assert repo_name_from_url("git@github.com:user/repo.git") == "user_repo"


def test_repo_name_from_url_sanitize():
    """Invalid chars in fallback name are replaced."""
    name = repo_name_from_url("https://example.com/some/weird.repo.name")
    assert " " not in name
    assert name == "weird.repo.name" or "_" in name
