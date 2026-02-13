"""LLM evaluation using OpenAI. Uses OPENAI_API_KEY from environment."""

import json
import os
import re
from typing import Any, Optional

from openai import OpenAI

from .context_collector import context_to_string
from .logger import get_logger

log = get_logger(__name__)

LLM_KEYS = [
    "medallion_architecture",
    "sla_logic",
    "pipeline_organization",
    "readme_clarity",
    "code_quality",
]
SUMMARY_KEY = "summary"

SYSTEM_PROMPT = """You are a senior Data Engineering reviewer.
Evaluate this Python repository implementing a Medallion Architecture pipeline.
Use only the provided evidence.

Score against these expected output rules (Gold layer and reports):

## Expected Output – Gold Layer

### Final table – SLA per ticket
The final table must contain at least these fields:
- Ticket ID
- Ticket type
- Responsible analyst
- Priority
- Open date
- Resolution date
- Resolution time in business hours
- Expected SLA (in hours)
- Indicator of SLA met or not met

Only tickets with status **Done** or **Resolved** must be in this table.

---

## Required simple reports
From the Gold layer, the following aggregated reports must be produced:

### Average SLA by analyst
- Analyst
- Number of tickets
- Average SLA (in hours)

### Average SLA by ticket type
- Ticket type
- Number of tickets
- Average SLA (in hours)

Reports may be delivered in `.CSV` or `.XLSX` format.

Use these rules to score medallion_architecture, sla_logic, and code_quality (0–5)."""

USER_PROMPT_TEMPLATE = """Use only the provided evidence below.
Score according to the Gold layer and report rules given in the system prompt.

Return ONLY valid JSON with no other text:
{
  "medallion_architecture": 0-5,
  "sla_logic": 0-5,
  "pipeline_organization": 0-5,
  "readme_clarity": 0-5,
  "code_quality": 0-5,
  "summary": "short technical summary"
}

Evidence:

{evidence}
"""

README_RUN_COMMAND_PROMPT = """From the README below, extract the exact command to run the data pipeline.

Look for sections like "How to Run", "Quick start", "Usage", or similar. The command is usually something like:
- python main.py
- python -m src.main
- python run_pipeline.py

Reply with ONLY the command line, nothing else. Use a single line. If the README mentions Docker, you may reply with the command that would be run inside the container (e.g. python -m src.main). If not found or unclear, reply exactly: UNKNOWN

README:

{readme}
"""


def _extract_json(text: str) -> Optional[dict]:
    """Try to parse JSON from model output (allow markdown code block)."""
    text = text.strip()
    # Strip optional markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def get_run_command_from_readme(readme: str) -> Optional[str]:
    """
    Ask the LLM to extract the pipeline run command from the README.
    Returns e.g. "python -m src.main" or None if unclear / API error.
    """
    if not readme or not readme.strip():
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set, cannot get run command from README")
        return None
    # Limit size to avoid token overflow
    readme_trimmed = readme[:8000].strip()
    prompt = README_RUN_COMMAND_PROMPT.format(readme=readme_trimmed)
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
        )
        content = (response.choices[0].message.content or "").strip()
        if not content or content.upper() == "UNKNOWN":
            return None
        # Basic sanity: should look like a python command
        if "python" not in content.lower():
            return None
        return content
    except Exception as e:
        log.warning("get_run_command_from_readme failed: %s", e)
        return None


def evaluate_with_llm(context: dict[str, Any]) -> dict[str, Any]:
    """
    Send context to OpenAI; return dict with medallion_architecture, sla_logic,
    pipeline_organization, readme_clarity, code_quality (0-5), and summary.
    On error return dict with zero scores and error summary.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.error("OPENAI_API_KEY not set")
        return _default_llm_result("OPENAI_API_KEY not set")

    evidence = context_to_string(context)
    user_prompt = USER_PROMPT_TEMPLATE.format(evidence=evidence)

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return _default_llm_result("Empty LLM response")
        parsed = _extract_json(content)
        if not parsed:
            return _default_llm_result(f"Invalid JSON in response: {content[:200]}")
        return _normalize_llm_result(parsed)
    except Exception as e:
        log.exception("LLM call failed")
        return _default_llm_result(str(e))


def _default_llm_result(error_message: str) -> dict[str, Any]:
    out = {k: 0 for k in LLM_KEYS}
    out[SUMMARY_KEY] = f"LLM evaluation failed: {error_message}"
    return out


def _normalize_llm_result(parsed: dict) -> dict[str, Any]:
    """Ensure all keys are 0-5 and summary is string."""
    out = {}
    for k in LLM_KEYS:
        v = parsed.get(k)
        if isinstance(v, (int, float)):
            out[k] = max(0, min(5, int(round(v))))
        else:
            out[k] = 0
    out[SUMMARY_KEY] = str(parsed.get(SUMMARY_KEY, ""))[:500]
    return out
