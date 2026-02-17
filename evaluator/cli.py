"""CLI: python -m evaluator.cli evaluate --file repos.xlsx"""

import os
from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv()

from .context_collector import collect_context
from .logger import get_logger, log_repo_error
from .pipeline_runner import run_pipeline, _find_entrypoint, _repo_uses_azure_ingestion
from .repo_cloner import clone_repo
from .scoring import load_config, compute_final_score_as_average, metric_value, BOOL_METRICS, DEFAULT_MAX_SCORE
from .spreadsheet import (
    load_input,
    get_repo_rows,
    build_result_row,
    write_results,
    RESULT_COLUMNS,
    REPO_URL_COL,
)
from .detectors import (
    run_checks,
    compute_dimension_scores,
    build_deterministic_summary,
    build_deterministic_evaluation_report_compact,
)
from .llm_evaluator import get_run_command_from_readme, generate_evaluation_summary_llm, format_docker_results_for_summary
from .security_scorer import compute_security_score
from .utils import ensure_dirs, get_output_dir

log = get_logger(__name__)
app = typer.Typer(help="Repository evaluator for Python Data Engineering challenges.")

_DEFAULT_FILE = Path("input/repos.xlsx")
_DEFAULT_OUTPUT = "repos_evaluated.xlsx"


def _run_evaluate(file: Path, output_name: str) -> None:
    """Shared evaluation logic (used by default callback and evaluate command)."""
    ensure_dirs()
    try:
        df = load_input(file)
    except FileNotFoundError as e:
        log.error("%s", e)
        raise typer.Exit(1)
    except ValueError as e:
        log.error("%s", e)
        raise typer.Exit(1)

    rows = get_repo_rows(df)
    if not rows:
        log.warning("No rows with repo_url found in %s", file)
        raise typer.Exit(0)

    config = load_config()
    weights = config["weights"]
    max_score = config["normalization"].get("max_score", DEFAULT_MAX_SCORE)
    summary_max_chars = config["normalization"].get("summary_max_chars", 1800)
    env_limit = os.environ.get("EVALUATION_SUMMARY_MAX_CHARS")
    if env_limit is not None:
        try:
            summary_max_chars = max(100, int(env_limit))
        except ValueError:
            pass

    result_rows = []
    for i, row in enumerate(rows):
        url = row.get(REPO_URL_COL, "")
        log.info("Evaluating %s (%s/%s)", url, i + 1, len(rows))
        result = _evaluate_one(url, row, weights, max_score, summary_max_chars)
        result_rows.append(result)

    out_path = get_output_dir() / output_name
    write_results(result_rows, out_path)
    log.info("Done. Results written to %s", out_path)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    file: Path = typer.Option(
        _DEFAULT_FILE, "--file", "-f", path_type=Path, help="Input Excel file with repo_url column"
    ),
    output_name: str = typer.Option(
        _DEFAULT_OUTPUT, "--output", "-o", help="Output Excel filename"
    ),
):
    """Repository evaluator: clone repos, run pipelines, score with LLM. Run with no args or use 'evaluate' subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    _run_evaluate(file, output_name)


@app.command()
def evaluate(
    file: Path = typer.Option(..., "--file", "-f", path_type=Path, help="Input Excel file with repo_url column"),
    output_name: str = typer.Option(_DEFAULT_OUTPUT, "--output", "-o", help="Output Excel filename"),
):
    """Read spreadsheet, clone repos, run pipelines, evaluate with LLM, write results."""
    _run_evaluate(file, output_name)


def _get_run_command_from_readme_at(repo_path: Path) -> str | None:
    """Read README at repo_path and return LLM-inferred run command, or None."""
    readme_path = repo_path / "README.md"
    if not readme_path.is_file():
        return None
    try:
        readme_text = readme_path.read_text(encoding="utf-8", errors="replace")
        return get_run_command_from_readme(readme_text)
    except Exception:
        return None


def _evaluate_one(repo_url: str, original_row: dict, weights: dict, max_score: float, summary_max_chars: int = 1800) -> dict:
    """Run clone -> pipeline -> context -> LLM -> score; merge into one result row."""
    # Start with original row; fill result columns from pipeline + LLM + scoring
    metrics = {
        "pipeline_runs": False,
        "gold_generated": False,
        "medallion_architecture": 0,
        "sla_logic": 0,
        "pipeline_organization": 0,
        "readme_clarity": 0,
        "code_quality": 0,
        "cloud_ingestion": 0,
        "naming_conventions_score": 0,
        "security_practices_score": 0,
        "sensitive_data_exposure_score": 0,
        "summary": "",
    }

    repo_path = clone_repo(repo_url)
    if repo_path is None:
        log_repo_error(log, repo_url, "clone", "Clone failed")
        metrics["summary"] = "Clone failed (e.g. broken link, private repo, or network error). Score reflects no evaluation."
        return build_result_row(original_row, _metrics_to_result(metrics, weights, max_score))

    run_command_override = None
    if os.environ.get("USE_README_RUN_COMMAND", "").strip().lower() in ("1", "true", "yes"):
        run_command_override = _get_run_command_from_readme_at(repo_path)
        if run_command_override:
            log.info("Using run command from README: %s", run_command_override)
    if run_command_override is None and _find_entrypoint(repo_path) is None:
        run_command_override = _get_run_command_from_readme_at(repo_path)
        if run_command_override:
            log.info(
                "Using run command from README (fallback; auto-discovery found no entrypoint): %s",
                run_command_override,
            )

    run_result = run_pipeline(
        repo_path,
        run_command_override=run_command_override,
    )
    metrics["pipeline_runs"] = run_result.get("pipeline_runs", False)
    metrics["gold_generated"] = run_result.get("gold_generated", False)

    context = collect_context(repo_path, run_result)
    # Deterministic presence-based scoring from boolean checks
    check_results = run_checks(repo_path)
    dimension_scores = compute_dimension_scores(check_results)
    for k, v in dimension_scores.items():
        metrics[k] = v
    metrics["cloud_ingestion"] = 100 if _repo_uses_azure_ingestion(repo_path) else 0
    metrics["security_practices_score"] = compute_security_score(repo_path)
    metrics["summary"] = build_deterministic_summary(
        check_results,
        dimension_scores,
        metrics["pipeline_runs"],
        metrics["gold_generated"],
        run_result.get("error"),
    )
    if not metrics["pipeline_runs"] and run_result.get("error"):
        err = (run_result.get("error") or "").strip()[:300]
        if err:
            metrics["summary"] = f"Pipeline error: {err}. " + (metrics["summary"] or "")

    result = _metrics_to_result(metrics, weights, max_score)
    docker_results_text = format_docker_results_for_summary(run_result)
    llm_summary = generate_evaluation_summary_llm(
        check_results, result, max_chars=summary_max_chars, docker_results=docker_results_text
    )
    if llm_summary is not None:
        result["evaluation_report"] = llm_summary
    else:
        result["evaluation_report"] = build_deterministic_evaluation_report_compact(
            check_results, result, max_chars=summary_max_chars
        )
    return build_result_row(original_row, result)


def _metrics_to_result(metrics: dict, weights: dict, max_score: float) -> dict:
    """Compute final_score as average of column scores; build result dict (all scores 0-100)."""
    final = compute_final_score_as_average(metrics, max_score)
    out = {}
    for k in RESULT_COLUMNS:
        if k == "final_score":
            out[k] = final
        elif k in BOOL_METRICS:
            out[k] = 100 if metrics.get(k) else 0
        elif k in ("medallion_architecture", "sla_logic", "pipeline_organization", "readme_clarity", "code_quality", "cloud_ingestion", "naming_conventions_score", "security_practices_score", "sensitive_data_exposure_score"):
            # Dimensions are stored as 0-100 (deterministic from checks or security scorer)
            out[k] = round(metrics.get(k, 0))
        elif k == "summary":
            out[k] = metrics.get(k, "")
        elif k == "evaluation_report":
            out[k] = ""  # filled in after this call via build_deterministic_evaluation_report
        else:
            out[k] = metrics.get(k)
    return out


if __name__ == "__main__":
    app()
