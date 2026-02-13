# Repository Evaluator (JiraFlowEval)

Evaluates multiple Python Data Engineering challenge repositories: clone, run pipeline, run deterministic checks, evaluate with an LLM, and produce a scored Excel report.

## Project Status

🚧 This project is under active development and continuously evolving.

## Reproducible setup with Docker (recommended)

Use Docker for the same Python version and dependencies on any machine:

```bash
# 1. Copy env template and set your OpenAI API key
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...

# 2. Build the image
docker compose build

# 3. Put your Excel in input/ and run
docker compose run --rm evaluator
```

Output appears in `output/repos_evaluated.xlsx`. To use a different input file or output name:

```bash
docker compose run --rm evaluator evaluate --file input/my_repos.xlsx --output my_results.xlsx
```

Cloned repos are stored in `temp_repos/` (mounted from the host).

## Local setup (without Docker)

```bash
pip install -r requirements.txt
```

Set your OpenAI API key (required for LLM evaluation):

```bash
export OPENAI_API_KEY=sk-...
# or create a .env file with OPENAI_API_KEY=...
```

## Usage

Place your Excel file (e.g. `repos.xlsx`) in the **input/** folder, then run:

**With Docker:**
```bash
docker compose run --rm evaluator
```

**Without Docker:**
```bash
python main.py
```
Or with a specific file: `python main.py evaluate --file input/repos.xlsx`

You can also run the CLI module directly: `python -m evaluator.cli evaluate --file input/repos.xlsx`. Pass any path with `--file path/to/your.xlsx`. Output is written to `output/repos_evaluated.xlsx` (the input file is never overwritten).

Optional:

- `--output` / `-o`: output filename (default: `repos_evaluated.xlsx`)

## Input

- Put your spreadsheet in the **input/** folder (e.g. `input/repos.xlsx`).
- Excel (`.xlsx`) with at least a column **repo_url**.
- Other columns (name, email, etc.) are preserved in the output.

An example file is provided: **`input/repos_example.xlsx`**. It shows the required `repo_url` column plus optional `name` and `email` columns. Copy and edit it for your repos.

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

- **OPENAI_API_KEY** – required for LLM evaluation
- **TEMP_REPOS_DIR** – where to clone repos (default: `temp_repos/`)
- **OUTPUT_DIR** – where to write results (default: `output/`)
- **REPO_EVALUATOR_ROOT** – project root (default: auto)
- **SCORING_CONFIG_PATH** – path to `scoring.yaml` (default: `config/scoring.yaml`)

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
2. Creates a venv, installs `requirements.txt`, runs `main.py` or `run_pipeline.py` (timeout 180s).
3. Checks that `data/gold` exists and contains at least one CSV.
4. Collects README, project tree (depth 3), `sla_calculation.py`, main pipeline file, and execution summary (file content capped at 4000 chars).
5. Sends context to the LLM for scores and summary.
6. Computes weighted final score from `config/scoring.yaml`.
7. Appends all result columns to the row and writes the new spreadsheet.

Errors for a single repo are logged; evaluation continues for the rest.
