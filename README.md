# Repository Evaluator (JiraFlowEval)

**What it does:** Takes an Excel list of repository URLs, clones each repo, runs its pipeline in Docker, and uses an LLM to score it (architecture, SLA logic, code quality, etc.). **What you get:** One Excel file with original columns plus scores and a short summary per repo.

🚧 *Under active development.*

On every push to **main**, GitHub Actions runs `docker compose build` and a container smoke test (see `.github/workflows/main.yml`).

---

## Prerequisites

- **Docker** – required (each candidate repo's pipeline runs in a container; no local fallback).
- **Git** – used to clone repos.
- **OpenAI API key** – required for LLM scoring (set in `.env`).

---

## Quick start (replicate in 4 steps)

1. **Clone this repo** and go to its directory.

2. **Create `.env`** from the template and set your OpenAI API key:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and set `OPENAI_API_KEY=sk-your-key`.
   *(Windows: `copy .env.example .env` then edit in Notepad or your editor.)*

3. **Add your input Excel** to the `input/` folder with a **`repo_url`** column. Copy `input/repos_example.xlsx` to `input/repos.xlsx` and add your repo URLs (or use another filename and pass `--file input/yourfile.xlsx` in step 4).

4. **Build and run:**
   ```bash
   docker compose build
   docker compose run --rm evaluator
   ```

Results are written to **`output/repos_evaluated.xlsx`**. Cloned repos are in **`temp_repos/`**.

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

## Input

- **Format:** Excel (`.xlsx`) with at least a column **`repo_url`** (one URL per row).
- **Location:** Put the file in **`input/`** (e.g. `input/repos.xlsx`).
- **Other columns** (name, email, etc.) are kept in the output.
- **Example:** `input/repos_example.xlsx` – copy it and add your repo URLs.

## Output

All original columns plus:

- **pipeline_runs** – pipeline executed successfully (True/False)
- **gold_generated** – `data/gold` exists and contains at least one CSV
- **medallion_architecture**, **sla_logic**, **pipeline_organization**, **readme_clarity**, **code_quality** – LLM scores 0–5
- **final_score** – weighted score (configurable max, default 10)
- **summary** – short technical summary from LLM

## Config

Edit `config/scoring.yaml` to change weights and max score. Weights are read at runtime; do not hardcode in code.

## Environment

**Required**

- **OPENAI_API_KEY** – set in `.env`; used for LLM scoring.
- **Docker** – must be installed; each repo's pipeline runs in a `python:3.12-slim` container.

**Optional** (in `.env` or shell)

- **USE_README_RUN_COMMAND** – set to `1` (or `true`/`yes`) to have the LLM read each repo's README and use the run command it finds (e.g. `python -m src.main`) instead of auto-detecting `main.py` / `run_pipeline.py`.
- **Azure** – if candidate repos need Azure Blob (e.g. Service Principal), set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` (and optionally `AZURE_SUBSCRIPTION_ID`); they are passed into the pipeline container.
- **TEMP_REPOS_DIR** – where to clone repos (default: `temp_repos/`).
- **OUTPUT_DIR** – where to write results (default: `output/`).
- **REPO_EVALUATOR_ROOT** – project root (default: auto).
- **SCORING_CONFIG_PATH** – path to `scoring.yaml` (default: `config/scoring.yaml`).

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
├── input/          # place your .xlsx here (see repos_example.xlsx)
├── temp_repos/
├── output/
├── main.py           # entry point: python main.py [evaluate --file input/repos.xlsx]
├── Dockerfile
├── docker-compose.yml
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

Errors for a single repo are logged; evaluation continues for the rest.
