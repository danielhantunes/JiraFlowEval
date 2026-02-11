"""CLI: python -m evaluator.cli evaluate --file repos.xlsx"""

from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv()

from .context_collector import collect_context
from .logger import get_logger, log_repo_error
from .pipeline_runner import run_pipeline
from .repo_cloner import clone_repo
from .scoring import load_config, compute_final_score
from .spreadsheet import (
    load_input,
    get_repo_rows,
    build_result_row,
    write_results,
    RESULT_COLUMNS,
    REPO_URL_COL,
)
from .llm_evaluator import evaluate_with_llm
from .utils import ensure_dirs, get_output_dir

log = get_logger(__name__)
app = typer.Typer(help="Repository evaluator for Python Data Engineering challenges.")


@app.command()
def evaluate(
    file: Path = typer.Option(..., "--file", "-f", path_type=Path, help="Input Excel file with repo_url column"),
    output_name: str = typer.Option("repos_evaluated.xlsx", "--output", "-o", help="Output Excel filename"),
):
    """Read spreadsheet, clone repos, run pipelines, evaluate with LLM, write results."""
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
    max_score = config["normalization"].get("max_score", 10)

    result_rows = []
    for i, row in enumerate(rows):
        url = row.get(REPO_URL_COL, "")
        log.info("Evaluating %s (%s/%s)", url, i + 1, len(rows))
        result = _evaluate_one(url, row, weights, max_score)
        result_rows.append(result)

    out_path = get_output_dir() / output_name
    write_results(result_rows, out_path)
    log.info("Done. Results written to %s", out_path)


def _evaluate_one(repo_url: str, original_row: dict, weights: dict, max_score: float) -> dict:
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
        "summary": "",
    }

    repo_path = clone_repo(repo_url)
    if repo_path is None:
        log_repo_error(log, repo_url, "clone", "Clone failed")
        return build_result_row(original_row, _metrics_to_result(metrics, weights, max_score))

    run_result = run_pipeline(repo_path)
    metrics["pipeline_runs"] = run_result.get("pipeline_runs", False)
    metrics["gold_generated"] = run_result.get("gold_generated", False)

    context = collect_context(repo_path, run_result)
    llm_result = evaluate_with_llm(context)
    for k in ["medallion_architecture", "sla_logic", "pipeline_organization", "readme_clarity", "code_quality"]:
        metrics[k] = llm_result.get(k, 0)
    metrics["summary"] = llm_result.get("summary", "")

    return build_result_row(original_row, _metrics_to_result(metrics, weights, max_score))


def _metrics_to_result(metrics: dict, weights: dict, max_score: float) -> dict:
    """Compute final_score and build result dict with all required columns."""
    final = compute_final_score(metrics, weights, max_score)
    out = {k: metrics.get(k) for k in RESULT_COLUMNS if k != "final_score"}
    out["final_score"] = final
    return out


if __name__ == "__main__":
    app()
