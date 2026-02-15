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
}
DEFAULT_MAX_SCORE = 10

# All metrics are 0-5 scale; booleans mapped to 0 or 5
BOOL_METRICS = ("pipeline_runs", "gold_generated")


def load_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load scoring.yaml; return weights and normalization. Use defaults if missing."""
    path = config_path or get_config_path()
    if not path.exists():
        return {"weights": dict(DEFAULT_WEIGHTS), "normalization": {"max_score": DEFAULT_MAX_SCORE}}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        weights = data.get("weights") or {}
        norm = data.get("normalization") or {}
        return {
            "weights": {**DEFAULT_WEIGHTS, **weights},
            "normalization": {"max_score": norm.get("max_score", DEFAULT_MAX_SCORE)},
        }
    except Exception:
        return {"weights": dict(DEFAULT_WEIGHTS), "normalization": {"max_score": DEFAULT_MAX_SCORE}}


def metric_value(raw: Any, key: str) -> float:
    """Convert raw value to 0-5 scale. Booleans -> 0 or 5."""
    if key in BOOL_METRICS:
        if isinstance(raw, bool):
            return 5.0 if raw else 0.0
        if raw in (1, "true", "True", "yes"):
            return 5.0
        return 0.0
    if isinstance(raw, (int, float)):
        return max(0.0, min(5.0, float(raw)))
    return 0.0


def compute_final_score(
    metrics: dict[str, Any],
    weights: dict[str, float],
    max_score: float = 10.0,
) -> float:
    """
    final_score = sum(metric * weight) / sum(weights), then normalize to max_score.
    Metrics are 0-5; result is scaled so max is max_score.
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
