# JiraFlowEval — Repository Evaluator

**What it does:** Reads an Excel list of repository URLs, clones each repo, runs its pipeline in Docker, and evaluates it using **deterministic presence-based checks** (boolean best-practice detectors + fixed weights). Use it to assess Jira/data-pipeline repos against a common standard (e.g. medallion layout, SLA, security, PII).

**What you get:** One Excel file with your original columns plus **scores** and a **summary** per repo. Same repo structure → same scores every time. No API key is required for scoring.

🚧 *Under active development.*

---

## Table of contents

- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Input & output](#input--output)
- [Configuration](#configuration)
- [Environment variables](#environment-variables)
- [Testing](#testing)
- [CI: GitHub Actions](#ci-github-actions)
- [Design decisions](#design-decisions)
- [Project layout](#project-layout)
- [Architecture & data flow](#architecture--data-flow)
- [How evaluation works](#how-evaluation-works)
- [Development](#development)
- [Limitations](#limitations)

---

## Prerequisites

| Requirement | Purpose |
|-------------|---------|
| **Docker** | Runs the evaluator and each candidate repo’s pipeline in containers. **Required**; there is no local fallback. |
| **Git** | Used to clone candidate repositories. |
| **OpenAI API key** | **Required for LLM-generated output.** When set, the evaluator uses the LLM (OpenAI) for the detailed narrative **evaluation report** and for inferring the run command from the README (when requested via `USE_README_RUN_COMMAND` or as **fallback** when auto-discovery finds no entrypoint). If not set, the evaluation report is a deterministic compact report and run-command discovery is non-LLM only. **Numeric scores are always computed without the LLM** (deterministic checks). |

---

## Quick start

### 1. Clone and configure

```bash
git clone <this-repo-url>
cd JiraFlowEval
cp .env.example .env
```

Edit `.env` and set **`OPENAI_API_KEY`** so the evaluator uses the LLM for the narrative evaluation report and (when needed) for run-command inference. Without it, you still get numeric scores and a deterministic compact report.

*Windows:* `copy .env.example .env` then edit in your editor.

### 2. Prepare the input file

- Create an `input/` folder if it doesn’t exist.
- Add an Excel file (e.g. `input/repos.xlsx`) with at least one column: **`repo_url`**.
- Put one repository URL per row (e.g. `https://github.com/org/repo-name`).
- Any other columns (name, email, etc.) are preserved in the output.

If the repo includes `input/repos_example.xlsx`, copy it to `input/repos.xlsx` and replace the URLs.

### 3. Build and run

```bash
docker compose build
docker compose run --rm evaluator
```

- **Input (default):** `input/repos.xlsx`
- **Output (default):** `output/repos_evaluated.xlsx`

For each row the tool: clones the repo → runs its pipeline in Docker → runs deterministic checks → computes scores → appends results. No manual steps per repo.

**Custom input/output:**

```bash
docker compose run --rm evaluator evaluate --file input/my_repos.xlsx --output my_results.xlsx
```

**CLI options:**

| Option | Short | Default | Description |
|--------|--------|---------|-------------|
| `--file` | `-f` | `input/repos.xlsx` | Input Excel path |
| `--output` | `-o` | `repos_evaluated.xlsx` | Output filename (written under `output/`). Input file is never overwritten. |

**Run without Docker for the evaluator** (pipeline runs still use Docker on the host):

```bash
pip install -r requirements.txt
python main.py evaluate --file input/repos.xlsx --output repos_evaluated.xlsx
```

---

## Input & output

### Input

- **Format:** Excel (`.xlsx`) with at least a column **`repo_url`** (one URL per row).
- **Location:** e.g. `input/repos.xlsx`. Other columns are kept in the output.

### Output

The output Excel contains all original columns plus:

| Column | Description |
|--------|-------------|
| `pipeline_runs` | Pipeline ran successfully (boolean / 0–100 in file). |
| `gold_generated` | `data/gold` exists and contains at least one CSV. |
| `medallion_architecture` | Score 0–100 (from presence checks: raw/bronze/silver/gold layers, orchestration). |
| `sla_logic` | Score 0–100 (SLA file, gold CSV/parquet, business-hours/SLA references). |
| `pipeline_organization` | Score 0–100 (entrypoint, requirements, config/env example). |
| `readme_clarity` | Score 0–100 (README present, run/usage mentioned, substantive). |
| `code_quality` | Score 0–100 (src/ingestion structure, docstrings/type hints, no hardcoded credentials). |
| `cloud_ingestion` | 0 or 100 (100 if Azure/cloud ingestion is detected). |
| `naming_conventions_score` | Score 0–100 (folders/files/data paths, common folders). |
| `security_practices_score` | Score 0–100 (credentials, env usage, .gitignore, config safety). |
| `sensitive_data_exposure_score` | Score 0–100: no email/phone PII in (1) source files under `src/`, `ingestion/`, or root, and (2) non–gitignored JSON/CSV/Parquet in `data/raw`, `data/bronze`, `data/silver`, `data/gold`. |
| `final_score` | Arithmetic mean of the score columns above (0–100). Same as the average of the column scores in the output. |
| `summary` | Short **deterministic** technical summary (checks passed, dimension scores, pipeline status). |
| `evaluation_report` | Detailed technical report including a **Suggested Improvements** section (actionable recommendations from detected issues only). **When `OPENAI_API_KEY` is set:** the LLM is used to generate this narrative. **Otherwise:** a deterministic compact report is produced (same content style, no API). Capped at 1800 characters. |

---

## Configuration

Edit **`config/scoring.yaml`** to change max score and summary length. The **final score** is the arithmetic average of the score columns (weights in the config are not used for the final score).

---

## Environment variables

**Required**

- **Docker** — must be installed; each candidate repo’s pipeline runs in a `python:3.12-slim` container.

**Optional** (in `.env` or shell)

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | **Recommended.** When set, the evaluator uses the LLM for the **evaluation report** and for README run-command extraction (when needed). Required for full LLM-based evaluation output; without it, a deterministic report is used. Numeric scores are always deterministic. |
| `USE_README_RUN_COMMAND` | Set to `1`, `true`, or `yes` to have the LLM infer the run command from each repo’s README instead of auto-detecting `main.py` / `run_pipeline.py`. When unset, the LLM is still used as a **fallback** when auto-discovery finds no entrypoint (requires `OPENAI_API_KEY`). |
| `TEMP_REPOS_DIR` | Where to clone repos (default: `temp_repos/`). |
| `OUTPUT_DIR` | Where to write results (default: `output/`). |
| `SCORING_CONFIG_PATH` | Path to scoring config (default: `config/scoring.yaml`). |

**Azure / candidate pipelines:** If candidate repos use Azure Blob or a specific input file, set in `.env`: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_ACCOUNT_URL`, `AZURE_CONTAINER_NAME`, `AZURE_BLOB_NAME`, and optionally `RAW_INPUT_FILENAME`. These are passed into the pipeline container. For GitHub Actions, see [CI: GitHub Actions](#ci-github-actions).

---

## Testing

Tests run **inside Docker in CI** (same environment as production). Locally you can use Docker or the host. No API key is needed; clone, pipeline, and LLM are mocked in the integration test. Coverage is for the `evaluator` package; CI fails if coverage drops below 55%.

**In Docker (recommended, matches CI):**

```bash
docker compose build
docker compose run --rm -T --entrypoint pytest evaluator tests/ -v --cov=evaluator --cov-report=term-missing --cov-fail-under=55
```

**On the host (optional):**

```bash
pip install -r requirements.txt
pytest tests/ -v --cov=evaluator --cov-report=term-missing
pytest tests/ --cov=evaluator --cov-report=html   # open htmlcov/index.html
```

---

## CI: GitHub Actions

The workflow **runs only when you trigger it:** **Actions → Build, test & evaluate → Run workflow.** It does not run on push.

1. **Build & test:** Builds the Docker image and runs the test suite inside the container (coverage ≥ 55%).
2. **Evaluate (optional):** If you have set the required secrets/variables, the same run can evaluate all repos in `input/repos.xlsx` and upload the result Excel as an artifact.

**Secrets and variables** (under **Settings → Secrets and variables → Actions**):

| Type | Name | Purpose |
|------|------|---------|
| Secret | `OPENAI_API_KEY` | For LLM-generated evaluation report. |
| Secret | `AZURE_TENANT_ID` | Azure AD tenant (if candidate repos use Azure). |
| Secret | `AZURE_CLIENT_ID` | Azure app ID. |
| Secret | `AZURE_CLIENT_SECRET` | Azure client secret. |
| Variable | `AZURE_ACCOUNT_URL` | Storage account URL. |
| Variable | `AZURE_CONTAINER_NAME` | Blob container name. |
| Variable | `AZURE_BLOB_NAME` | Blob name (if used). |
| Variable | `RAW_INPUT_FILENAME` | Optional. Input file name for repos that read a local file. |
| Secret | `DOCKERHUB_USERNAME` | Optional. Avoid Docker Hub rate limit. |
| Secret | `DOCKERHUB_TOKEN` | Optional. With `DOCKERHUB_USERNAME`. |

Use **Secrets** for credentials (masked in logs) and **Variables** for non-sensitive config. If `input/repos.xlsx` is missing, the workflow creates a default list so the evaluate job can still run.

---

## Design decisions

| Decision | Rationale |
|----------|-----------|
| **Docker mandatory for pipeline runs** | Each candidate repo runs in a `python:3.12-slim` container: same environment everywhere, isolation for untrusted code. No local/venv fallback. |
| **Tests in Docker in CI** | Same image as evaluation; validates exact runtime and paths. |
| **Coverage threshold (55%)** | CI fails if coverage drops; keeps a minimum quality bar. |
| **Final score = average of columns** | The overall score is the arithmetic mean of the 11 score columns (pipeline_runs, gold_generated, medallion, SLA, etc.). Config in `scoring.yaml` sets max score and summary length only. |
| **Deterministic scores** | Numeric scores come from boolean presence checks and fixed weights (same structure → same scores). The LLM is used for the narrative evaluation report and for run-command inference when `OPENAI_API_KEY` is set; otherwise a deterministic compact report is used. |
| **Retries** | Git clone and optional OpenAI calls are retried to reduce impact of transient failures. |
| **Workflow on demand** | Evaluation runs only when you trigger the workflow, not on every push. |

---

## Project layout

```
JiraFlowEval/
├── evaluator/
│   ├── cli.py              # CLI and evaluate orchestration
│   ├── spreadsheet.py      # Excel read/write
│   ├── repo_cloner.py      # Clone/pull repos
│   ├── pipeline_runner.py  # Run pipeline in Docker
│   ├── context_collector.py
│   ├── detectors.py        # Deterministic presence checks
│   ├── security_scorer.py  # Credential and .gitignore checks
│   ├── llm_evaluator.py    # LLM evaluation report (when OPENAI_API_KEY set)
│   ├── scoring.py          # Weights and final score
│   ├── logger.py
│   └── utils.py
├── config/
│   └── scoring.yaml
├── tests/
├── input/                  # Place your .xlsx here
├── temp_repos/
├── output/
├── main.py                 # Entry: python main.py [evaluate ...]
├── Dockerfile
├── docker-compose.yml
├── .env.example            # Copy to .env, set OPENAI_API_KEY for LLM report
├── requirements.txt
└── README.md
```

---

## Architecture & data flow

**Flow:** Excel (repo URLs) → clone each repo into `temp_repos/` → run pipeline in Docker (`python:3.12-slim`) → run deterministic checks on repo files → compute dimension scores and final score (average of columns) → call LLM for narrative evaluation report when `OPENAI_API_KEY` is set, otherwise build deterministic compact report → write result row to output Excel. One row per repo; failures (clone or pipeline) still produce a row with zero scores and an error summary.

---

## How evaluation works

For each repo the tool:

1. **Clone** into `temp_repos/<repo_name>` (or pull if already present).
2. **Run pipeline** in a Docker container (`python:3.12-slim`): installs `requirements.txt`, runs the entrypoint. The command is chosen by: auto-discovery (`main.py`, `run_pipeline.py`, `src/main.py`); or, if `USE_README_RUN_COMMAND` is set, from the README via LLM; or, if auto-discovery finds nothing, from the README via LLM as fallback (requires `OPENAI_API_KEY`). Timeout 180s.
3. **Verify** that `data/gold` exists and contains at least one CSV.
4. **Run deterministic checks** (medallion layers, SLA, pipeline org, readme, code quality, naming, security) and compute dimension scores from fixed weights.
5. **Collect context** (README, project tree, `sla_calculation.py`, main pipeline file, execution summary; content capped per file).
6. **Compute final score** as the average of the score columns; build the deterministic summary (and compact report if no API key). `config/scoring.yaml` controls max score and summary length only.
7. **Optional:** If `OPENAI_API_KEY` is set, call the LLM to generate the detailed **evaluation_report**.
8. Append all result columns to the row and write the spreadsheet.

**Failure handling:** If clone fails, the row is still written with zero scores and a summary explaining the failure; pipeline and LLM are skipped for that repo. If the pipeline fails, the summary includes the error. One repo’s error does not stop the rest; errors are logged.

---

## Development

- **Add or change a presence check:** Edit `evaluator/detectors.py`. Register the check in `CHECK_REGISTRY` (dimension, check_id, weight). Implement the detector function and add it to `DETECTORS`. Dimension scores are 0–100 from passed checks; `sensitive_data_exposure_score` is set to 0 if any PII check fails.
- **Scoring:** Final score is the average of the 11 score columns (`evaluator/scoring.py`: `compute_final_score_as_average`, `FINAL_SCORE_AVERAGE_KEYS`). Config in `config/scoring.yaml` sets max score and summary length.
- **Run against one repo locally:** Put a single-row Excel with one `repo_url` in `input/`, then run the evaluator; or run the pipeline and checks from the repo root (see `evaluator/cli.py` and `evaluator/detectors.py` for entrypoints).

---

## Limitations

- **Docker required** for running candidate pipelines; there is no local/venv fallback. Evaluator itself can run on the host with `python main.py evaluate ...`.
- **Pipeline timeout:** 180 seconds per repo. Slow pipelines may be marked as failed.
- **Private repos:** Clone requires valid Git credentials (SSH key or token). Set up access before adding private URLs to the input file.
- **No versioning of results:** Output file is overwritten per run; keep a copy if you need to compare runs.
