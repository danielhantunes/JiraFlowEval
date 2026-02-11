"""Path and environment utilities. No hardcoded paths or API keys."""

import os
from pathlib import Path


def get_project_root() -> Path:
    """Project root (parent of evaluator package)."""
    root = os.environ.get("REPO_EVALUATOR_ROOT")
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def get_temp_repos_dir() -> Path:
    """Directory for cloned repositories."""
    path = os.environ.get("TEMP_REPOS_DIR")
    if path:
        return Path(path).resolve()
    return get_project_root() / "temp_repos"


def get_output_dir() -> Path:
    """Directory for output files (e.g. repos_evaluated.xlsx)."""
    path = os.environ.get("OUTPUT_DIR")
    if path:
        return Path(path).resolve()
    return get_project_root() / "output"


def get_config_path() -> Path:
    """Path to scoring.yaml."""
    path = os.environ.get("SCORING_CONFIG_PATH")
    if path:
        return Path(path).resolve()
    return get_project_root() / "config" / "scoring.yaml"


def ensure_dirs() -> None:
    """Create temp_repos and output directories if they do not exist."""
    get_temp_repos_dir().mkdir(parents=True, exist_ok=True)
    get_output_dir().mkdir(parents=True, exist_ok=True)
