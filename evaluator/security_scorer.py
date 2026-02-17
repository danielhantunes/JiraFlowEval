"""Security practices score (0-100) from credential handling and DevSecOps hygiene checks."""

from __future__ import annotations

import re
from pathlib import Path

from .logger import get_logger

log = get_logger(__name__)

# Points per category (total 100)
POINTS_NO_HARDCODED = 40
POINTS_ENV_VARS = 20
POINTS_ENV_IGNORED = 15
POINTS_GITIGNORE_SECURITY = 15
POINTS_SAFE_CONFIG = 10

# Patterns that suggest hardcoded credentials (assignments to secret-like names with a value)
HARDCODED_PATTERNS = [
    re.compile(r'\b(?:api_key|apikey)\s*=\s*["\'][^"\']+["\']', re.IGNORECASE),
    re.compile(r'\bpassword\s*=\s*["\'][^"\']*["\']', re.IGNORECASE),
    re.compile(r'\bclient_secret\s*=\s*["\'][^"\']+["\']', re.IGNORECASE),
    re.compile(r'\b(?:secret_key|secret)\s*=\s*["\'][^"\']+["\']', re.IGNORECASE),
    re.compile(r'\b(?:access_key|access_token|token)\s*=\s*["\'][^"\']+["\']', re.IGNORECASE),
    re.compile(r'\b(?:connection_string|conn_str|connection_str)\s*=\s*["\'][^"\']+["\']', re.IGNORECASE),
    re.compile(r'^\s*ACCESS_KEY\s*=\s*.+', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*SECRET_KEY\s*=\s*.+', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*SECRET_ACCESS_KEY\s*=\s*.+', re.MULTILINE | re.IGNORECASE),
    re.compile(r'\bsk-[a-zA-Z0-9]{20,}\b'),  # OpenAI-style key
]

# Patterns that suggest environment variable usage (good)
ENV_VAR_PATTERNS = [
    re.compile(r'\bos\.getenv\s*\(', re.IGNORECASE),
    re.compile(r'\bos\.environ\s*\[', re.IGNORECASE),
    re.compile(r'\bos\.environ\.get\s*\(', re.IGNORECASE),
]

# .gitignore entries that improve security (presence = good)
GITIGNORE_SECURITY_ENTRIES = [".env", "secrets.json", "credentials.json", "*.key", "*.pem", ".env.local", ".env.*.local"]


def _has_hardcoded_credentials(content: str) -> bool:
    """True if content matches any hardcoded credential pattern."""
    for pat in HARDCODED_PATTERNS:
        if pat.search(content):
            return True
    return False


def _uses_env_vars(content: str) -> bool:
    """True if content uses os.getenv or os.environ."""
    for pat in ENV_VAR_PATTERNS:
        if pat.search(content):
            return True
    return False


def _read_file_safe(path: Path, max_size: int = 100_000) -> str:
    try:
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:max_size] if len(text) > max_size else text
    except Exception as e:
        log.debug("Could not read %s: %s", path, e)
        return ""


def _gitignore_lines(repo_path: Path) -> list[str]:
    """Return normalized .gitignore lines (stripped, no comments)."""
    p = repo_path / ".gitignore"
    if not p.is_file():
        return []
    text = _read_file_safe(p)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _env_ignored_properly(repo_path: Path) -> bool:
    """True if .env does not exist, or .env exists and is in .gitignore."""
    env_file = repo_path / ".env"
    if not env_file.exists():
        return True
    lines = _gitignore_lines(repo_path)
    for line in lines:
        if line.strip() == ".env" or line.strip().startswith(".env"):
            return True
    return False


def _config_has_secrets(repo_path: Path) -> bool:
    """True if config.yaml or config.json contain credential-like content."""
    for name in ["config.yaml", "config.yml", "config.json", "configuration.yaml", "configuration.json"]:
        p = repo_path / name
        if not p.is_file():
            continue
        content = _read_file_safe(p)
        if _has_hardcoded_credentials(content):
            return True
        # Also check for key: value that looks like a secret
        if re.search(r'(?:password|secret|api_key|token|key):\s*["\']?[a-zA-Z0-9_\-]{8,}', content, re.IGNORECASE):
            return True
    return False


def _skip_path(repo_path: Path, f: Path) -> bool:
    """True if path should be skipped (venv, cache, hidden dirs)."""
    try:
        rel = f.relative_to(repo_path)
    except ValueError:
        return True
    parts = str(rel).replace("\\", "/").split("/")
    for seg in parts:
        if seg.startswith(".") and seg != ".env":
            return True
        if seg in ("__pycache__", "venv", ".venv", "node_modules", "env"):
            return True
    return False


def compute_security_score(repo_path: Path) -> int:
    """
    Compute security_practices_score 0-100 based on:
    - No hardcoded credentials (40)
    - Uses environment variables (20)
    - .env ignored properly (15)
    - .gitignore security entries (15)
    - Safe config files (10)
    """
    repo_path = Path(repo_path)
    hardcoded_found = False
    env_used = False
    for ext in ["*.py", "*.yml", "*.yaml", "*.json"]:
        for f in repo_path.rglob(ext):
            if _skip_path(repo_path, f):
                continue
            content = _read_file_safe(f)
            if _has_hardcoded_credentials(content):
                hardcoded_found = True
            if _uses_env_vars(content):
                env_used = True
        if hardcoded_found:
            break

    score = 0
    if not hardcoded_found:
        score += POINTS_NO_HARDCODED
    if env_used:
        score += POINTS_ENV_VARS
    if _env_ignored_properly(repo_path):
        score += POINTS_ENV_IGNORED
    security_entries_found = 0
    lines = _gitignore_lines(repo_path)
    for entry in GITIGNORE_SECURITY_ENTRIES:
        for line in lines:
            if line == entry or (entry.startswith("*") and (line == entry or line.endswith(entry[1:]))):
                security_entries_found += 1
                break
            if entry in line:
                security_entries_found += 1
                break
    score += min(POINTS_GITIGNORE_SECURITY, security_entries_found * 5)
    if not _config_has_secrets(repo_path):
        score += POINTS_SAFE_CONFIG
    return min(100, score)
