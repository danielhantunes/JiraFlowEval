# Repository Evaluator (JiraFlowEval)

**What it does:** Takes an Excel list of repository URLs, clones each repo, runs its pipeline in Docker, and uses an LLM to score it (architecture, SLA logic, code quality, etc.). **What you get:** One Excel file with original columns plus scores and a short summary per repo.

🚧 *Under active development.*

The workflow runs **on demand** only: in the GitHub repo go to **Actions → Build, test & evaluate → Run workflow**. It builds the Docker image and runs all tests inside the container (coverage ≥55%). If the **OPENAI_API_KEY** secret is set, the same run can include a full evaluation on all repos in the input file (see [Step 7](#step-7-optional-enable-automated-evaluation-in-ci) and [Design decisions](#design-decisions)).

---

## Prerequisites

Before you start, ensure you have:

| Requirement | Purpose |
|-------------|---------|
| **Docker** | Runs the evaluator and every candidate repo's pipeline in containers (mandatory; no local fallback). |
| **Git** | Used to clone candidate repositories. |
| **OpenAI API key** | Required for LLM scoring (stored in `.env`). |

---

## Implement this project step by step

Follow these steps to run the evaluator locally or in your own fork.

### Step 1: Clone the repository

```bash
git clone <this-repo-url>
cd JiraFlowEval
```

### Step 2: Create and configure `.env`

Copy the template and set your OpenAI API key (required for LLM scoring):

```bash
cp .env.example .env
```

Then edit `.env` and set:

- **`OPENAI_API_KEY`** – your OpenAI API key (e.g. `sk-...`).

*(On Windows: `copy .env.example .env` then edit in Notepad or your editor.)*

Optional: set `USE_README_RUN_COMMAND=1` if you want the LLM to infer the run command from each repo's README. If candidate repos need Azure, add the Azure env vars listed in [Environment](#environment).

### Step 3: Prepare the input spreadsheet

1. Create the `input/` folder if it does not exist.
2. Add an Excel file (e.g. `input/repos.xlsx`) with at least one column: **`repo_url`**.
3. Put one repository URL per row (e.g. `https://github.com/org/repo-name`).
4. You can keep other columns (name, email, etc.); they are preserved in the output.

If the repo includes `input/repos_example.xlsx`, copy it to `input/repos.xlsx` and replace the example URLs with your own.

### Step 4: Build the Docker image

From the project root:

```bash
docker compose build
```

This builds the evaluator image (Python 3.12, dependencies from `requirements.txt`).

### Step 5: Run the evaluation

```bash
docker compose run --rm evaluator
```

This uses the default input `input/repos.xlsx` and writes **`output/repos_evaluated.xlsx`**. The tool will, for each row:

- Clone the repo into `temp_repos/`,
- Run its pipeline inside a Docker container,
- Collect context and call the LLM for scores,
- Append scores and summary to the row.

No manual steps per repo; one command processes the whole list.

To use a different input or output file:

```bash
docker compose run --rm evaluator evaluate --file input/my_repos.xlsx --output my_results.xlsx
```

### Step 6 (optional): Run tests

To run the test suite in the same environment as CI (inside Docker):

```bash
docker compose build
docker compose run --rm -T --entrypoint pytest evaluator tests/ -v --cov=evaluator --cov-report=term-missing
```

See [Testing](#testing) for host-based pytest as well.

### Step 7 (optional): Enable automated evaluation in CI

If you use GitHub Actions and want to run a full evaluation on demand:

1. In your GitHub repo: **Settings → Secrets and variables → Actions** → add the **secrets** and **variables** you need (see [GitHub Actions: secrets and variables](#github-actions-secrets-and-variables)). At minimum, add repository secret **`OPENAI_API_KEY`** for LLM scoring. If candidate repos use Azure Blob or a specific input file, add the Azure secrets and variables listed there.
2. Go to **Actions → Build, test & evaluate → Run workflow** and click **Run workflow** (choose the branch that has your `input/repos.xlsx` if needed).
3. The workflow will build, test, then run evaluation on all repos in `input/repos.xlsx` (or a default list if that file is missing). Download the result Excel from the run page: **Artifacts → evaluation-results**.

The workflow runs only when you trigger it; it does not run on push.

---

## Usage

**Default:** reads `input/repos.xlsx` and writes `output/repos_evaluated.xlsx`. To use another file or output name:

```bash
docker compose run --rm evaluator evaluate --file input/my_repos.xlsx --output my_results.xlsx
```

**Run the evaluator locally** (Docker still required on the host for pipeline runs):

```bash
pip install -r requirements.txt
# Set OPENAI_API_KEY in .env or: export OPENAI_API_KEY=sk-...
python main.py evaluate --file input/repos.xlsx --output repos_evaluated.xlsx
```

- `--file` / `-f`: input Excel path (default: `input/repos.xlsx`).
- `--output` / `-o`: output filename (default: `repos_evaluated.xlsx`). The input file is never overwritten.

---

## Design decisions

These choices keep the project production-like, reproducible, and easy to run without manual per-repo steps.

| Decision | Rationale |
|----------|-----------|
| **Docker mandatory for pipeline runs** | Every candidate repo runs inside a `python:3.12-slim` container. This matches a production-style environment, avoids “works on my machine” (same Python and OS everywhere), and isolates untrusted code. There is no local/venv fallback. |
| **Tests run in Docker in CI** | The test suite runs inside the same image that is used for evaluation. So we validate the exact runtime (dependencies, paths). CI does not run tests on the host. |
| **Coverage threshold (55%)** | CI fails if coverage of the `evaluator` package drops below 55%. This keeps a minimum quality bar and encourages tests when adding or changing code. |
| **Retries for clone and LLM** | Git clone and OpenAI API calls are retried a few times with a short delay. Transient network or rate-limit errors are less likely to fail the whole run. |
| **Config-driven scoring** | Weights and max score live in `config/scoring.yaml`, not in code. You can tune scoring without changing the evaluator. |
| **Fully automated evaluation** | One command processes every repo in the input file: clone → run pipeline in Docker → LLM → write row. No manual steps per repository. |
| **Workflow on demand** | The workflow runs only when you trigger it (Actions → Run workflow), not on push. The evaluate job runs when the `OPENAI_API_KEY` secret is set. That keeps the repo usable for forks that don’t have a key, while allowing fully automated runs where the secret is configured. |

---

## Input

- **Format:** Excel (`.xlsx`) with at least a column **`repo_url`** (one URL per row).
- **Location:** Put the file in **`input/`** (e.g. `input/repos.xlsx`).
- **Other columns** (name, email, etc.) are kept in the output.
- **Example:** `input/repos_example.xlsx` – copy it and add your repo URLs.

## Output

All original columns plus:

- **pipeline_runs** – pipeline executed successfully (True/False)
- **gold_generated** – `data/gold` exists and contains at least one CSV
- **medallion_architecture**, **sla_logic**, **pipeline_organization**, **readme_clarity**, **code_quality**, **cloud_ingestion** – LLM scores 0–5 (cloud_ingestion: Azure Service Principal / cloud ingestion = 5, local JSON only = 1–2)
- **final_score** – weighted score (configurable max, default 10)
- **summary** – short technical summary from LLM; when clone or pipeline fails, explains the error so the score is justified (e.g. "Clone failed...", "Pipeline error: ...")

## Config

Edit `config/scoring.yaml` to change weights and max score. Weights are read at runtime; do not hardcode in code.

## Environment

**Required**

- **OPENAI_API_KEY** – set in `.env`; used for LLM scoring.
- **Docker** – must be installed; each repo's pipeline runs in a `python:3.12-slim` container.

**Optional** (in `.env` or shell)

- **USE_README_RUN_COMMAND** – set to `1` (or `true`/`yes`) to have the LLM read each repo's README and use the run command it finds (e.g. `python -m src.main`) instead of auto-detecting `main.py` / `run_pipeline.py`.
- **Azure / input file** – if candidate repos need Azure Blob or a specific input file, set the env vars listed below; they are passed into the pipeline container. For **GitHub Actions**, use [Repository secrets and variables](#github-actions-secrets-and-variables).
- **TEMP_REPOS_DIR** – where to clone repos (default: `temp_repos/`).
- **OUTPUT_DIR** – where to write results (default: `output/`).
- **REPO_EVALUATOR_ROOT** – project root (default: auto).
- **SCORING_CONFIG_PATH** – path to `scoring.yaml` (default: `config/scoring.yaml`).

### GitHub Actions: secrets and variables

When you run the workflow from **Actions → Build, test & evaluate → Run workflow**, the **evaluate** job builds a `.env` from repository **Secrets** and **Variables**. Add them under **Settings → Secrets and variables → Actions**.

| Type | Name | Purpose |
|------|------|---------|
| **Secret** | `OPENAI_API_KEY` | OpenAI API key for LLM scoring. |
| **Secret** | `AZURE_TENANT_ID` | Azure AD tenant (Service Principal). |
| **Secret** | `AZURE_CLIENT_ID` | Azure app (client) ID. |
| **Secret** | `AZURE_CLIENT_SECRET` | Azure client secret. |
| **Variable** | `AZURE_ACCOUNT_URL` | Storage account URL (e.g. `https://<name>.blob.core.windows.net`). |
| **Variable** | `AZURE_CONTAINER_NAME` | Blob container name. |
| **Variable** | `AZURE_BLOB_NAME` | Blob name (if used by the candidate repo). |
| **Variable** | `RAW_INPUT_FILENAME` | Input file path/name for repos that read a local file. |

**Best practice:** use **Secrets** for credentials (API keys, client secrets, tenant/client IDs) so they are masked in logs; use **Variables** for non-sensitive config (URLs, container/blob names, paths). The workflow uses `secrets.*` for the four secrets above and `vars.*` for the four variables.

If a secret or variable is not set, the corresponding line is still written to `.env` with an empty value; the evaluator and pipeline containers receive whatever you configured.

## Testing

Tests run inside Docker in CI (mandatory; same environment as production). Locally you can run them in Docker or on the host. No API key needed (clone, pipeline, and LLM are mocked in the integration test). Coverage is reported for the `evaluator` package; CI fails if coverage drops below 55%.

**In Docker (recommended, matches CI):**
```bash
docker compose build
docker compose run --rm -T --entrypoint pytest evaluator tests/ -v --cov=evaluator --cov-report=term-missing
```

**On the host (optional, for quick iteration):**
```bash
pip install -r requirements.txt
pytest tests/ -v
pytest tests/ -v --cov=evaluator --cov-report=term-missing
pytest tests/ --cov=evaluator --cov-report=html   # then open htmlcov/index.html
```

## Project layout

```
JiraFlowEval/
├── evaluator/
│   ├── cli.py
│   ├── spreadsheet.py
│   ├── repo_cloner.py
│   ├── pipeline_runner.py
│   ├── context_collector.py
│   ├── llm_evaluator.py
│   ├── scoring.py
│   ├── logger.py
│   └── utils.py
├── config/
│   └── scoring.yaml
├── tests/         # pytest unit and integration tests
├── input/         # place your .xlsx here (see repos_example.xlsx)
├── temp_repos/
├── output/
├── main.py           # entry point: python main.py [evaluate --file input/repos.xlsx]
├── Dockerfile
├── docker-compose.yml
├── .coveragerc       # coverage config for pytest-cov
├── .dockerignore
├── .env.example      # copy to .env and set OPENAI_API_KEY
├── requirements.txt
└── README.md
```

## Pipeline behavior

For each repo the tool:

1. Clones into `temp_repos/<repo_name>` (or pulls if present).
2. Runs the pipeline inside a Docker container (`python:3.12-slim`): installs `requirements.txt`, runs `main.py` or `run_pipeline.py` (timeout 180s).
3. Checks that `data/gold` exists and contains at least one CSV.
4. Collects README, project tree (depth 3), `sla_calculation.py`, main pipeline file, and execution summary (file content capped at 4000 chars).
5. Sends context to the LLM for scores and summary.
6. Computes weighted final score from `config/scoring.yaml`.
7. Appends all result columns to the row and writes the new spreadsheet.

If **clone fails** (e.g. broken link), the row is still written with zero scores and a **summary** explaining the failure; pipeline and LLM are skipped for that repo. If the **pipeline fails**, the summary includes the error so the score is justified. Errors for a single repo are logged; evaluation continues for the rest.
