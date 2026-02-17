"""Excel input/output. Read spreadsheet with repo_url; write results preserving columns."""

from pathlib import Path
from typing import List, Optional

import pandas as pd

from .logger import get_logger

REPO_URL_COL = "repo_url"
REQUIRED_COLUMNS = [REPO_URL_COL]

RESULT_COLUMNS = [
    "pipeline_runs",
    "gold_generated",
    "medallion_architecture",
    "sla_logic",
    "pipeline_organization",
    "readme_clarity",
    "code_quality",
    "cloud_ingestion",
    "naming_conventions_score",
    "security_practices_score",
    "final_score",
    "summary",
    "evaluation_report",
]

log = get_logger(__name__)


def load_input(file_path: Path) -> pd.DataFrame:
    """Load Excel file; require repo_url column. Raise if missing or empty."""
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    df = pd.read_excel(file_path, engine="openpyxl")
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    return df


def get_repo_rows(df: pd.DataFrame) -> List[dict]:
    """Yield rows as dicts; only rows with non-empty repo_url."""
    out = []
    for _, row in df.iterrows():
        url = row.get(REPO_URL_COL)
        if pd.isna(url) or not str(url).strip():
            continue
        out.append(row.to_dict())
    return out


def build_result_row(original_row: dict, result: dict) -> dict:
    """Merge original row with result columns; result keys override."""
    row = dict(original_row)
    for col in RESULT_COLUMNS:
        row[col] = result.get(col, None)
    return row


def write_results(rows: List[dict], output_path: Path) -> None:
    """Write list of row dicts to Excel. Creates parent dirs if needed."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_excel(output_path, index=False, engine="openpyxl")
    log.info("Wrote results to %s", output_path)
