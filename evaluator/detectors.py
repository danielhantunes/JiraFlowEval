"""
Deterministic presence-based checks for repository evaluation.
Each check is a boolean function of repo_path. Scores are computed from
passed checks using fixed weights so the same structure always gets the same score.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Callable

from .logger import get_logger
from .pipeline_runner import _repo_uses_azure_ingestion

log = get_logger(__name__)

# Registry: (dimension, check_id, weight). Weights per dimension are normalized to 0-100.
CHECK_REGISTRY: list[tuple[str, str, int]] = [
    # Medallion architecture (5 checks, 20 each)
    ("medallion_architecture", "has_raw_layer", 20),
    ("medallion_architecture", "has_bronze_layer", 20),
    ("medallion_architecture", "has_silver_layer", 20),
    ("medallion_architecture", "has_gold_layer", 20),
    ("medallion_architecture", "pipeline_orchestrates_layers", 20),
    # SLA logic (5 checks, 20 each)
    ("sla_logic", "has_sla_calculation_file", 20),
    ("sla_logic", "gold_has_csv_reports", 20),
    ("sla_logic", "gold_has_parquet", 20),
    ("sla_logic", "code_references_business_hours_or_sla", 20),
    ("sla_logic", "gold_has_sla_related_columns", 20),
    # Pipeline organization (4 checks, 25 each)
    ("pipeline_organization", "has_main_or_run_pipeline", 25),
    ("pipeline_organization", "has_requirements_txt", 25),
    ("pipeline_organization", "has_config_or_env_example", 25),
    ("pipeline_organization", "has_clear_entrypoint", 25),
    # Readme clarity (3 checks: 40, 30, 30)
    ("readme_clarity", "has_readme", 40),
    ("readme_clarity", "readme_mentions_run_or_usage", 30),
    ("readme_clarity", "readme_substantive", 30),
    # Code quality (3 checks: 34, 33, 33)
    ("code_quality", "has_src_or_ingestion_structure", 34),
    ("code_quality", "has_docstrings_or_type_hints", 33),
    ("code_quality", "no_hardcoded_credentials_in_code", 33),
    # Naming (4 checks, 25 each)
    ("naming_conventions_score", "folders_lowercase_or_snake", 25),
    ("naming_conventions_score", "python_files_snake_case", 25),
    ("naming_conventions_score", "data_paths_use_layer_names", 25),
    ("naming_conventions_score", "has_common_folders", 25),
    # Sensitive data exposure (2 checks, 50 each)
    ("sensitive_data_exposure_score", "no_pii_in_source_files", 50),
    ("sensitive_data_exposure_score", "no_pii_in_medallion_data_files", 50),
]


def _read_file_safe(path: Path, max_size: int = 50_000) -> str:
    try:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:max_size]
    except Exception:
        return ""


def _has_raw_layer(repo_path: Path) -> bool:
    return (repo_path / "data" / "raw").is_dir()


def _has_bronze_layer(repo_path: Path) -> bool:
    return (repo_path / "data" / "bronze").is_dir()


def _has_silver_layer(repo_path: Path) -> bool:
    return (repo_path / "data" / "silver").is_dir()


def _has_gold_layer(repo_path: Path) -> bool:
    return (repo_path / "data" / "gold").is_dir()


def _pipeline_orchestrates_layers(repo_path: Path) -> bool:
    main_content = _read_file_safe(repo_path / "main.py") + _read_file_safe(repo_path / "src" / "main.py") + _read_file_safe(repo_path / "run_pipeline.py")
    return "bronze" in main_content.lower() and "silver" in main_content.lower() and "gold" in main_content.lower()


def _has_sla_calculation_file(repo_path: Path) -> bool:
    return (repo_path / "sla_calculation.py").is_file() or (repo_path / "src" / "sla" / "sla_calculation.py").is_file()


def _gold_has_csv_reports(repo_path: Path) -> bool:
    gold = repo_path / "data" / "gold"
    if not gold.is_dir():
        return False
    return any(f.suffix.lower() == ".csv" for f in gold.rglob("*") if f.is_file())


def _gold_has_parquet(repo_path: Path) -> bool:
    gold = repo_path / "data" / "gold"
    if not gold.is_dir():
        return False
    return any(f.suffix.lower() == ".parquet" for f in gold.rglob("*") if f.is_file())


def _code_references_business_hours_or_sla(repo_path: Path) -> bool:
    for py in repo_path.rglob("*.py"):
        if "__pycache__" in str(py) or "venv" in str(py):
            continue
        content = _read_file_safe(py)
        if re.search(r"business.?hour|sla|resolution.?hour", content, re.IGNORECASE):
            return True
    return False


def _gold_has_sla_related_columns(repo_path: Path) -> bool:
    for path in [repo_path / "src" / "gold", repo_path / "gold", repo_path / "src"]:
        if not path.is_dir():
            continue
        for py in path.rglob("*.py"):
            content = _read_file_safe(py)
            if re.search(r"sla|resolution|business.?hour|is_sla_met", content, re.IGNORECASE):
                return True
    return False


def _has_main_or_run_pipeline(repo_path: Path) -> bool:
    return (repo_path / "main.py").is_file() or (repo_path / "run_pipeline.py").is_file() or (repo_path / "src" / "main.py").is_file()


def _has_requirements_txt(repo_path: Path) -> bool:
    return (repo_path / "requirements.txt").is_file()


def _has_config_or_env_example(repo_path: Path) -> bool:
    return (repo_path / "config.py").is_file() or (repo_path / ".env.example").is_file() or (repo_path / ".env.sample").is_file() or (repo_path / "config.yaml").is_file() or (repo_path / "src" / "utils" / "config.py").is_file()


def _has_clear_entrypoint(repo_path: Path) -> bool:
    from .pipeline_runner import _find_entrypoint
    return _find_entrypoint(repo_path) is not None


def _has_readme(repo_path: Path) -> bool:
    return (repo_path / "README.md").is_file()


def _readme_mentions_run_or_usage(repo_path: Path) -> bool:
    content = _read_file_safe(repo_path / "README.md")
    return bool(re.search(r"run|usage|quick.?start|how to|install|setup", content, re.IGNORECASE))


def _readme_substantive(repo_path: Path) -> bool:
    content = _read_file_safe(repo_path / "README.md")
    return len(content.strip()) >= 200


def _has_src_or_ingestion_structure(repo_path: Path) -> bool:
    return (repo_path / "src").is_dir() or (repo_path / "ingestion").is_dir()


def _has_docstrings_or_type_hints(repo_path: Path) -> bool:
    for base in [repo_path / "src", repo_path / "ingestion", repo_path]:
        if not base.is_dir():
            continue
        for py in list(base.rglob("*.py"))[:15]:
            if "__pycache__" in str(py) or "venv" in str(py):
                continue
            content = _read_file_safe(py)
            if '"""' in content or "'''" in content or re.search(r"def\s+\w+\([^)]*:\s*[\w\[\]]+", content):
                return True
    return False


def _no_hardcoded_credentials_in_code(repo_path: Path) -> bool:
    from .security_scorer import _has_hardcoded_credentials, _read_file_safe as _sec_read
    for py in repo_path.rglob("*.py"):
        if "__pycache__" in str(py) or "venv" in str(py) or ".venv" in str(py):
            continue
        try:
            rel = py.relative_to(repo_path)
            if any(p.startswith(".") for p in rel.parts):
                continue
        except ValueError:
            continue
        if _has_hardcoded_credentials(_sec_read(py)):
            return False
    return True


def _folders_lowercase_or_snake(repo_path: Path) -> bool:
    for p in repo_path.iterdir():
        if not p.is_dir() or p.name.startswith(".") or p.name in ("venv", ".venv", "__pycache__", "node_modules"):
            continue
        if p.name != p.name.lower() or " " in p.name:
            return False
        if not re.match(r"^[a-z][a-z0-9_]*$", p.name):
            return False
    return True


# Conventional Python file names that are allowed even though they don't match snake_case.
_PYTHON_CONVENTIONAL_STEMS = frozenset({"__init__", "__main__"})


def _python_files_snake_case(repo_path: Path) -> bool:
    for base in [repo_path / "src", repo_path / "ingestion", repo_path]:
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            if "__pycache__" in str(py) or "venv" in str(py):
                continue
            name = py.stem
            if name in _PYTHON_CONVENTIONAL_STEMS:
                continue
            if not re.match(r"^[a-z][a-z0-9_]*$", name):
                return False
    return True


def _data_paths_use_layer_names(repo_path: Path) -> bool:
    data = repo_path / "data"
    if not data.is_dir():
        return True
    layers = {"raw", "bronze", "silver", "gold"}
    for f in data.rglob("*"):
        if f.is_file():
            try:
                rel = f.relative_to(data)
                if rel.parts and rel.parts[0].lower() in layers:
                    return True
            except ValueError:
                pass
    return False


def _has_common_folders(repo_path: Path) -> bool:
    names = {p.name.lower() for p in repo_path.iterdir() if p.is_dir() and not p.name.startswith(".")}
    return bool(names & {"src", "data", "config", "tests"})


# PII patterns: email and phone (deterministic detection in source files only).
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
# International (+prefix) or US-style (xxx) xxx-xxxx only; avoid matching version numbers or IPs
_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[-.\s]?\d{2,}(?:[-.\s]?\d{2,}){2,}|\(\d{3}\)\s*\d{3}[-.]?\d{4})\b"
)


def _no_pii_in_source_files(repo_path: Path) -> bool:
    """Return True if no email or phone PII is found in Python source files under src/, ingestion/, or root."""
    def scan_file(py: Path) -> bool:
        content = _read_file_safe(py)
        if _EMAIL_RE.search(content):
            return False
        if _PHONE_RE.search(content):
            return False
        return True

    for base in [repo_path / "src", repo_path / "ingestion"]:
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            path_str = str(py)
            if "__pycache__" in path_str or "venv" in path_str or ".venv" in path_str:
                continue
            if not scan_file(py):
                return False
    for py in repo_path.glob("*.py"):
        if not scan_file(py):
            return False
    return True


def _load_gitignore_patterns(repo_path: Path) -> list[str]:
    """Load .gitignore patterns (strip comments/blank; normalize to /)."""
    gitignore = repo_path / ".gitignore"
    if not gitignore.is_file():
        return []
    patterns = []
    for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Normalize to forward slashes for matching
        patterns.append(line.replace("\\", "/"))
    return patterns


def _is_gitignored(repo_path: Path, file_path: Path, patterns: list[str]) -> bool:
    """Return True if file_path (under repo_path) is matched by any .gitignore pattern."""
    try:
        rel = file_path.relative_to(repo_path)
    except ValueError:
        return False
    path_posix = rel.as_posix()
    for pattern in patterns:
        # Support ** by replacing with * for fnmatch (loose: * in fnmatch doesn't match /)
        # So we use a simple prefix/suffix fallback for patterns containing **
        if "**" in pattern:
            parts = pattern.split("**")
            prefix = parts[0].rstrip("/")
            suffix = parts[-1].lstrip("/") if len(parts) > 1 else ""
            if prefix and not path_posix.startswith(prefix + "/") and path_posix != prefix:
                continue
            if suffix and not path_posix.endswith(suffix) and not fnmatch.fnmatch(path_posix, "*" + suffix):
                continue
            return True
        if fnmatch.fnmatch(path_posix, pattern):
            return True
        if fnmatch.fnmatch(path_posix, pattern.rstrip("/") + "/*"):
            return True
    return False


def _text_has_pii(text: str) -> bool:
    """Return True if text contains email or phone PII."""
    if _EMAIL_RE.search(text):
        return True
    if _PHONE_RE.search(text):
        return True
    return False


def _scan_json_or_csv_for_pii(file_path: Path, max_chars: int = 500_000) -> bool:
    """Return True if file (JSON or CSV) contains PII. True = has PII (fail)."""
    content = _read_file_safe(file_path, max_size=max_chars)
    return _text_has_pii(content)


def _scan_parquet_for_pii(file_path: Path) -> bool:
    """Return True if Parquet file string columns contain PII. True = has PII (fail)."""
    try:
        import pandas as pd
    except ImportError:
        return False
    try:
        df = pd.read_parquet(file_path)
    except Exception:
        return False
    # Concatenate string representation of all columns and scan
    text = df.astype(str).to_string()
    return _text_has_pii(text)


def _no_pii_in_medallion_data_files(repo_path: Path) -> bool:
    """Return True if no email or phone PII is found in non-gitignored JSON/CSV/Parquet under data/raw, bronze, silver, gold."""
    patterns = _load_gitignore_patterns(repo_path)
    medallion_dirs = ["raw", "bronze", "silver", "gold"]
    data_dir = repo_path / "data"
    if not data_dir.is_dir():
        return True
    for layer in medallion_dirs:
        layer_dir = data_dir / layer
        if not layer_dir.is_dir():
            continue
        for ext in ("*.json", "*.csv", "*.parquet"):
            for f in layer_dir.rglob(ext):
                if not f.is_file():
                    continue
                if _is_gitignored(repo_path, f, patterns):
                    continue
                if f.suffix.lower() == ".json" or f.suffix.lower() == ".csv":
                    if _scan_json_or_csv_for_pii(f):
                        return False
                elif f.suffix.lower() == ".parquet":
                    if _scan_parquet_for_pii(f):
                        return False
    return True


# Map check_id -> detector function
DETECTORS: dict[str, Callable[[Path], bool]] = {
    "has_raw_layer": _has_raw_layer,
    "has_bronze_layer": _has_bronze_layer,
    "has_silver_layer": _has_silver_layer,
    "has_gold_layer": _has_gold_layer,
    "pipeline_orchestrates_layers": _pipeline_orchestrates_layers,
    "has_sla_calculation_file": _has_sla_calculation_file,
    "gold_has_csv_reports": _gold_has_csv_reports,
    "gold_has_parquet": _gold_has_parquet,
    "code_references_business_hours_or_sla": _code_references_business_hours_or_sla,
    "gold_has_sla_related_columns": _gold_has_sla_related_columns,
    "has_main_or_run_pipeline": _has_main_or_run_pipeline,
    "has_requirements_txt": _has_requirements_txt,
    "has_config_or_env_example": _has_config_or_env_example,
    "has_clear_entrypoint": _has_clear_entrypoint,
    "has_readme": _has_readme,
    "readme_mentions_run_or_usage": _readme_mentions_run_or_usage,
    "readme_substantive": _readme_substantive,
    "has_src_or_ingestion_structure": _has_src_or_ingestion_structure,
    "has_docstrings_or_type_hints": _has_docstrings_or_type_hints,
    "no_hardcoded_credentials_in_code": _no_hardcoded_credentials_in_code,
    "folders_lowercase_or_snake": _folders_lowercase_or_snake,
    "python_files_snake_case": _python_files_snake_case,
    "data_paths_use_layer_names": _data_paths_use_layer_names,
    "has_common_folders": _has_common_folders,
    "no_pii_in_source_files": _no_pii_in_source_files,
    "no_pii_in_medallion_data_files": _no_pii_in_medallion_data_files,
}

# Actionable improvement suggestions for each failed check (used in Suggested Improvements section).
CHECK_ID_TO_IMPROVEMENT: dict[str, str] = {
    "has_raw_layer": "Add a raw layer (e.g. data/raw) to improve traceability and reprocessing capability.",
    "has_bronze_layer": "Add a bronze layer (e.g. data/bronze) for normalized raw data.",
    "has_silver_layer": "Add a silver layer (e.g. data/silver) for enriched/cleaned data.",
    "has_gold_layer": "Add a gold layer (e.g. data/gold) for business-ready outputs and reports.",
    "pipeline_orchestrates_layers": "Ensure the main pipeline orchestrates all medallion layers (raw → bronze → silver → gold) in sequence.",
    "has_sla_calculation_file": "Add an SLA calculation module (e.g. sla_calculation.py or src/sla/sla_calculation.py).",
    "gold_has_csv_reports": "Produce at least one CSV report from the gold layer (e.g. average SLA by analyst or by ticket type).",
    "gold_has_parquet": "Consider producing Parquet outputs from the gold layer for efficient storage and querying.",
    "code_references_business_hours_or_sla": "Implement or reference business-hours or SLA logic in code (e.g. resolution time in business hours).",
    "gold_has_sla_related_columns": "Include SLA-related columns in gold outputs (e.g. resolution time, expected SLA, is_sla_met).",
    "has_main_or_run_pipeline": "Add a clear pipeline entrypoint (main.py or run_pipeline.py).",
    "has_requirements_txt": "Add requirements.txt for reproducible dependencies.",
    "has_config_or_env_example": "Add configuration (e.g. config.py, .env.example, or config.yaml) for environment-specific settings.",
    "has_clear_entrypoint": "Ensure a discoverable entrypoint (main.py, run_pipeline.py, or src/main.py).",
    "has_readme": "Add a README.md with project description and usage.",
    "readme_mentions_run_or_usage": "Improve README by adding run/usage instructions (e.g. how to run the pipeline).",
    "readme_substantive": "Improve README with more substantive content (e.g. pipeline architecture section and execution instructions).",
    "has_src_or_ingestion_structure": "Organize code under src/ or ingestion/ for clearer structure.",
    "has_docstrings_or_type_hints": "Add docstrings or type hints to improve code clarity and maintainability.",
    "no_hardcoded_credentials_in_code": "Move hardcoded credentials from code to environment variables (e.g. .env); do not commit secrets.",
    "folders_lowercase_or_snake": "Use lowercase snake_case for folder names (e.g. data, src, config).",
    "python_files_snake_case": "Rename Python files to snake_case to follow Python naming standards (e.g. process_data.py not ProcessData.py).",
    "data_paths_use_layer_names": "Use medallion layer names in data paths (e.g. data/raw, data/bronze, data/silver, data/gold).",
    "has_common_folders": "Adopt common project folders (e.g. src, data, config, tests).",
    "no_pii_in_source_files": "Remove emails or other PII from source files; use config or environment variables for sensitive data.",
    "no_pii_in_medallion_data_files": "Remove emails or other PII from JSON/CSV/Parquet in data/ (raw, bronze, silver, gold), or add those files to .gitignore so they are not committed.",
}


def build_suggested_improvements(check_results: dict[str, bool]) -> list[str]:
    """Return actionable improvement suggestions for each failed check. Order matches CHECK_REGISTRY."""
    seen: set[str] = set()
    out: list[str] = []
    for _dim, check_id, _weight in CHECK_REGISTRY:
        if check_id in seen or check_results.get(check_id, True):
            continue
        seen.add(check_id)
        suggestion = CHECK_ID_TO_IMPROVEMENT.get(check_id)
        if suggestion:
            out.append(suggestion)
    return out


def run_checks(repo_path: Path) -> dict[str, bool]:
    """Run all registered checks; return {check_id: passed}."""
    repo_path = Path(repo_path)
    result = {}
    for _dim, check_id, _weight in CHECK_REGISTRY:
        if check_id in result:
            continue
        fn = DETECTORS.get(check_id)
        if fn is None:
            result[check_id] = False
            continue
        try:
            result[check_id] = bool(fn(repo_path))
        except Exception as e:
            log.debug("Check %s failed: %s", check_id, e)
            result[check_id] = False
    return result


def compute_dimension_scores(check_results: dict[str, bool]) -> dict[str, int]:
    """Compute 0-100 score per dimension from check results using fixed weights."""
    dimension_totals: dict[str, int] = {}
    dimension_earned: dict[str, int] = {}
    for dimension, check_id, weight in CHECK_REGISTRY:
        dimension_totals[dimension] = dimension_totals.get(dimension, 0) + weight
        if check_results.get(check_id, False):
            dimension_earned[dimension] = dimension_earned.get(dimension, 0) + weight
    out = {}
    for dim, total in dimension_totals.items():
        earned = dimension_earned.get(dim, 0)
        out[dim] = round(100 * earned / total) if total else 0
    return out


def build_deterministic_summary(
    check_results: dict[str, bool],
    dimension_scores: dict[str, int],
    pipeline_runs: bool,
    gold_generated: bool,
    run_error: str | None,
) -> str:
    """Build a short deterministic summary from check results and scores."""
    parts = []
    if run_error and not pipeline_runs:
        parts.append(f"Pipeline error: {run_error[:200]}.")
    total_checks = len(check_results)
    passed = sum(1 for v in check_results.values() if v)
    parts.append(f"Deterministic evaluation: {passed}/{total_checks} checks passed.")
    for dim, score in sorted(dimension_scores.items()):
        parts.append(f"{dim}: {score}/100.")
    if pipeline_runs and gold_generated:
        parts.append("Pipeline ran successfully; gold layer and reports generated.")
    elif pipeline_runs:
        parts.append("Pipeline ran; gold/reports not verified.")
    return " ".join(parts)[:800]


def build_deterministic_evaluation_report(
    check_results: dict[str, bool],
    scores: dict,
) -> str:
    """
    Build a structured technical evaluation report from check results and scores only.
    No subjective or LLM-based content; same inputs always produce the same report.
    """
    lines = []
    final = scores.get("final_score", 0)
    pipeline_ok = scores.get("pipeline_runs") in (True, 100)
    gold_ok = scores.get("gold_generated") in (True, 100)

    lines.append("## Executive summary")
    lines.append("")
    lines.append(f"Final score: {final}/100. Pipeline ran: {'Yes' if pipeline_ok else 'No'}. Gold layer/reports generated: {'Yes' if gold_ok else 'No'}.")
    passed = sum(1 for v in check_results.values() if v)
    lines.append(f"Presence-based checks: {passed}/{len(check_results)} passed. All scores are computed from these checks and fixed weights.")
    lines.append("")

    # Group checks by dimension
    dim_checks: dict[str, list[tuple[str, bool]]] = {}
    for dimension, check_id, _weight in CHECK_REGISTRY:
        dim_checks.setdefault(dimension, []).append((check_id, check_results.get(check_id, False)))

    lines.append("## Architecture (medallion layers)")
    lines.append("")
    for check_id, ok in dim_checks.get("medallion_architecture", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## SLA logic")
    lines.append("")
    for check_id, ok in dim_checks.get("sla_logic", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## Pipeline organization")
    lines.append("")
    for check_id, ok in dim_checks.get("pipeline_organization", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## Readme clarity")
    lines.append("")
    for check_id, ok in dim_checks.get("readme_clarity", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## Code quality")
    lines.append("")
    for check_id, ok in dim_checks.get("code_quality", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## Naming conventions")
    lines.append("")
    for check_id, ok in dim_checks.get("naming_conventions_score", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## Sensitive data (PII)")
    lines.append("")
    for check_id, ok in dim_checks.get("sensitive_data_exposure_score", []):
        lines.append(f"- {check_id}: {'Pass' if ok else 'Fail'}")
    lines.append("")

    lines.append("## Cloud ingestion & security")
    lines.append("")
    lines.append(f"- cloud_ingestion score: {scores.get('cloud_ingestion', 0)}/100 (100 if Azure/cloud ingestion detected, else 0).")
    lines.append(f"- security_practices_score: {scores.get('security_practices_score', 0)}/100 (from credential and .gitignore checks).")
    lines.append(f"- sensitive_data_exposure_score: {scores.get('sensitive_data_exposure_score', 0)}/100 (no email/phone PII in source or non-gitignored medallion data files).")
    lines.append("")

    lines.append("## Score justification (presence-based)")
    lines.append("")
    lines.append("Each dimension score = 100 × (sum of weights for passed checks) / (sum of weights for that dimension).")
    for dim in ["medallion_architecture", "sla_logic", "pipeline_organization", "readme_clarity", "code_quality", "naming_conventions_score", "sensitive_data_exposure_score"]:
        sc = scores.get(dim, 0)
        lines.append(f"- {dim}: {sc}/100")
    lines.append("")
    lines.append("No subjective scoring; identical repository structure yields identical scores.")

    # Suggested Improvements
    suggestions = build_suggested_improvements(check_results)
    if scores.get("cloud_ingestion", 0) == 0:
        suggestions.append("Consider adding cloud ingestion (e.g. Azure Blob) for production-style pipelines.")
    if (scores.get("security_practices_score", 100) or 100) < 50:
        suggestions.append("Move hardcoded credentials to environment variables and ensure .env is in .gitignore.")
    if (scores.get("sensitive_data_exposure_score", 100) or 100) < 100:
        suggestions.append("Remove emails or other PII from source files; use config or environment variables for sensitive data.")
    if suggestions:
        lines.append("")
        lines.append("## Suggested Improvements")
        lines.append("")
        for s in suggestions:
            lines.append(f"- {s}")
    return "\n".join(lines)


def build_deterministic_evaluation_report_compact(
    check_results: dict[str, bool],
    scores: dict,
    max_chars: int = 1800,
) -> str:
    """
    Build a technical summary from check results and scores that stays under max_chars by design.
    Sections are added only while total length would not exceed max_chars; no truncation/slicing.
    Keeps line breaks for readability. Same inputs produce same output (deterministic).
    """
    parts: list[str] = []
    final = scores.get("final_score", 0)
    pipeline_ok = scores.get("pipeline_runs") in (True, 100)
    gold_ok = scores.get("gold_generated") in (True, 100)
    passed = sum(1 for v in check_results.values() if v)
    total_checks = len(check_results)

    def add(text: str) -> bool:
        """Append line(s) if total would stay <= max_chars. Returns True if added."""
        candidate = "\n".join(parts + [text]) if parts else text
        if len(candidate) <= max_chars:
            parts.append(text)
            return True
        return False

    add(f"Final score: {final}/100. Pipeline ran: {'Yes' if pipeline_ok else 'No'}. Gold generated: {'Yes' if gold_ok else 'No'}.")
    add(f"Checks: {passed}/{total_checks} passed.")
    add("")

    # Group checks by dimension (same as full report)
    dim_checks: dict[str, list[tuple[str, bool]]] = {}
    for dimension, check_id, _weight in CHECK_REGISTRY:
        dim_checks.setdefault(dimension, []).append((check_id, check_results.get(check_id, False)))

    section_titles = [
        ("medallion_architecture", "Medallion"),
        ("sla_logic", "SLA logic"),
        ("pipeline_organization", "Pipeline org"),
        ("readme_clarity", "Readme"),
        ("code_quality", "Code quality"),
        ("naming_conventions_score", "Naming"),
        ("sensitive_data_exposure_score", "PII"),
    ]
    for dim_key, title in section_titles:
        checks = dim_checks.get(dim_key, [])
        sc = scores.get(dim_key, 0)
        line = f"{title} ({sc}/100): " + ", ".join(f"{c}={('P' if ok else 'F')}" for c, ok in checks)
        if not add(line):
            break
    add("")
    add(f"Cloud: {scores.get('cloud_ingestion', 0)}/100. Security: {scores.get('security_practices_score', 0)}/100. PII: {scores.get('sensitive_data_exposure_score', 0)}/100.")
    add("Scores from presence checks only; no subjective scoring.")

    # Suggested Improvements (from failed checks and low scores)
    suggestions = build_suggested_improvements(check_results)
    if scores.get("cloud_ingestion", 0) == 0:
        suggestions.append("Consider adding cloud ingestion (e.g. Azure Blob) for production-style pipelines.")
    if (scores.get("security_practices_score", 100) or 100) < 50:
        suggestions.append("Move hardcoded credentials to environment variables and ensure .env is in .gitignore.")
    if (scores.get("sensitive_data_exposure_score", 100) or 100) < 100:
        suggestions.append("Remove emails or other PII from source files; use config or environment variables for sensitive data.")
    if suggestions:
        add("")
        add("## Suggested Improvements")
        add("")
        for s in suggestions:
            if not add(f"- {s}"):
                break
    return "\n".join(parts)
