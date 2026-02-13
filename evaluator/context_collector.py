"""Collect evidence for LLM: README, tree, sla_calculation.py, main pipeline, execution summary."""

from pathlib import Path
from typing import Any

from .logger import get_logger

log = get_logger(__name__)

MAX_CHARS_PER_FILE = 4000
TREE_DEPTH = 3


def _read_limited(path: Path) -> str:
    """Read file content capped at MAX_CHARS_PER_FILE."""
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_CHARS_PER_FILE:
            text = text[:MAX_CHARS_PER_FILE] + "\n... [truncated]"
        return text
    except Exception as e:
        log.warning("Could not read %s: %s", path, e)
        return f"[read error: {e}]"


def _tree(dir_path: Path, prefix: str = "", depth: int = 0, max_depth: int = 3) -> str:
    if depth >= max_depth:
        return ""
    lines = []
    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        for i, p in enumerate(entries):
            is_last = i == len(entries) - 1
            name = p.name
            if p.name.startswith(".") and p.name != ".git":
                continue
            if p.name == "venv" or p.name == ".venv" or p.name == "__pycache__":
                continue
            branch = "└── " if is_last else "├── "
            lines.append(prefix + branch + name)
            if p.is_dir() and depth + 1 < max_depth:
                ext = "    " if is_last else "│   "
                lines.append(_tree(p, prefix + ext, depth + 1, max_depth))
    except PermissionError:
        lines.append(prefix + "[permission denied]")
    return "\n".join(lines)


def collect_context(repo_path: Path, execution_result: dict) -> dict[str, Any]:
    """
    Gather README, project tree (depth 3), sla_calculation.py, main pipeline file,
    and deterministic execution summary. Each file content limited to 4000 chars.
    """
    repo_path = Path(repo_path)
    context: dict[str, Any] = {
        "readme": "",
        "project_tree": "",
        "sla_calculation": "",
        "main_pipeline": "",
        "execution_summary": {},
    }

    readme = repo_path / "README.md"
    if readme.exists():
        context["readme"] = _read_limited(readme)

    context["project_tree"] = _tree(repo_path, max_depth=TREE_DEPTH)

    for sla_rel in ["sla_calculation.py", "src/sla/sla_calculation.py"]:
        sla = repo_path / sla_rel
        if sla.exists():
            context["sla_calculation"] = _read_limited(sla)
            break

    for rel in ["main.py", "run_pipeline.py", "src/main.py", "src/run_pipeline.py"]:
        p = repo_path / rel
        if p.exists():
            context["main_pipeline"] = _read_limited(p)
            break

    context["execution_summary"] = {
        "pipeline_runs": execution_result.get("pipeline_runs", False),
        "gold_generated": execution_result.get("gold_generated", False),
        "return_code": execution_result.get("return_code"),
        "stdout_preview": (execution_result.get("stdout") or "")[:500],
        "stderr_preview": (execution_result.get("stderr") or "")[:500],
        "error": execution_result.get("error"),
    }

    return context


def context_to_string(context: dict[str, Any]) -> str:
    """Format context dict as a single string for the LLM prompt."""
    parts = [
        "=== README.md ===",
        context.get("readme", "") or "(none)",
        "\n=== Project tree (depth 3) ===",
        context.get("project_tree", "") or "(none)",
        "\n=== sla_calculation.py ===",
        context.get("sla_calculation", "") or "(not found)",
        "\n=== Main pipeline file ===",
        context.get("main_pipeline", "") or "(none)",
        "\n=== Execution summary ===",
        str(context.get("execution_summary", {})),
    ]
    return "\n".join(parts)
