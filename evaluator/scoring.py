"""Load scoring config from YAML; compute weighted final score. No hardcoded weights."""

from pathlib import Path
from typing import Any, Optional

import yaml

from .utils import get_config_path

DEFAULT_WEIGHTS = {
    "pipeline_runs": 3,
    "gold_generated": 2,
    "medallion_architecture": 3,
    "sla_logic": 3,
    "pipeline_organization": 2,
    "readme_clarity": 2,
    "code_quality": 2,
    "cloud_ingestion": 2,
    "naming_conventions_score": 2,
    "security_practices_score": 2,
    "sensitive_data_exposure_score": 2,
}
DEFAULT_MAX_SCORE = 100
DEFAULT_SUMMARY_MAX_CHARS = 1800
# Per-dimension scores from LLM are 0-5; we scale to 0-100 for output
SCORE_SCALE_0_5_TO_100 = 20  # 5 * 20 = 100

# All metrics are 0-5 scale internally; booleans mapped to 0 or 5
BOOL_METRICS = ("pipeline_runs", "gold_generated")

# Column scores in the final output (0-100 each). Final score = average of these.
FINAL_SCORE_AVERAGE_KEYS = (
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
    "sensitive_data_exposure_score",
)


def load_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load scoring.yaml; return weights and normalization. Use defaults if missing."""
    path = config_path or get_config_path()
    if not path.exists():
        return {
            "weights": dict(DEFAULT_WEIGHTS),
            "normalization": {"max_score": DEFAULT_MAX_SCORE, "summary_max_chars": DEFAULT_SUMMARY_MAX_CHARS},
        }
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        weights = data.get("weights") or {}
        norm = data.get("normalization") or {}
        return {
            "weights": {**DEFAULT_WEIGHTS, **weights},
            "normalization": {
                "max_score": norm.get("max_score", DEFAULT_MAX_SCORE),
                "summary_max_chars": norm.get("summary_max_chars", DEFAULT_SUMMARY_MAX_CHARS),
            },
        }
    except Exception:
        return {
            "weights": dict(DEFAULT_WEIGHTS),
            "normalization": {"max_score": DEFAULT_MAX_SCORE, "summary_max_chars": DEFAULT_SUMMARY_MAX_CHARS},
        }


def metric_value(raw: Any, key: str) -> float:
    """
    Convert raw value to 0-5 scale for weighted average.
    Booleans -> 0 or 5. Dimension scores may be 0-100 (stored directly); >5 treated as 0-100 and scaled to 0-5.
    """
    if key in BOOL_METRICS:
        if isinstance(raw, bool):
            return 5.0 if raw else 0.0
        if raw in (1, "true", "True", "yes"):
            return 5.0
        return 0.0
    if isinstance(raw, (int, float)):
        v = float(raw)
        if v > 5:
            return max(0.0, min(5.0, v / 20.0))
        return max(0.0, min(5.0, v))
    return 0.0


def compute_final_score(
    metrics: dict[str, Any],
    weights: dict[str, float],
    max_score: float = 100.0,
) -> float:
    """
    final_score = sum(metric * weight) / sum(weights), then normalize to max_score.
    Metrics are 0-5 internally; result is in [0, max_score] (default 0-100).
    """
    weighted_sum = 0.0
    total_weight = 0.0
    for key, w in weights.items():
        if key not in metrics:
            continue
        v = metric_value(metrics[key], key)
        weighted_sum += v * w
        total_weight += w
    if total_weight <= 0:
        return 0.0
    # Average is in [0, 5]; scale to [0, max_score]
    avg_5 = weighted_sum / total_weight
    return round(avg_5 * (max_score / 5.0), 2)


def compute_final_score_as_average(metrics: dict[str, Any], max_score: float = 100.0) -> float:
    """
    Final score as the arithmetic mean of the output score columns (0-100 each).
    So the final score equals the average of the column scores shown in the report.
    """
    total = 0.0
    count = 0
    for key in FINAL_SCORE_AVERAGE_KEYS:
        if key not in metrics:
            continue
        raw = metrics[key]
        if key in BOOL_METRICS:
            v = max_score if raw in (True, 1, "true", "True", "yes") else 0.0
        else:
            v = float(raw) if isinstance(raw, (int, float)) else 0.0
            v = max(0.0, min(max_score, v))
        total += v
        count += 1
    if count == 0:
        return 0.0
    return round(total / count, 2)
