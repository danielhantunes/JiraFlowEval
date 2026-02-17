"""LLM evaluation using OpenAI. Uses OPENAI_API_KEY from environment."""

import json
import os
import re
import time
from typing import Any, Optional

from openai import OpenAI

LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY_SEC = 2

from .context_collector import context_to_string
from .logger import get_logger

log = get_logger(__name__)

LLM_KEYS = [
    "medallion_architecture",
    "sla_logic",
    "pipeline_organization",
    "readme_clarity",
    "code_quality",
    "cloud_ingestion",
    "naming_conventions_score",
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

Use these rules to score medallion_architecture, sla_logic, and code_quality (0–5).

---

## Cloud ingestion (Azure Service Principal vs local file only)
- **5**: Ingestion supports (or documents) Azure Blob / cloud storage via Service Principal (e.g. AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_ACCOUNT_URL). Pipeline can pull raw data from cloud.
- **3–4**: Partial cloud support (e.g. config present but optional, or similar cloud auth).
- **1–2**: Local file only: ingestion expects only a local JSON (or file path); no Azure/cloud integration. Acceptable for local/dev but not production-style cloud ingestion.
- **0**: No clear ingestion path or no evidence.

Score cloud_ingestion (0–5) based on the evidence (README, ingestion code, config).

---

## Naming conventions (Python, folders, data, columns) – score naming_conventions_score (0–5)

Evaluate using the "Naming audit" and code in the evidence. Total 100 points, map to 0–5 (e.g. 80–100 → 5, 60–79 → 4, 40–59 → 3, 20–39 → 2, 0–19 → 1).

**Python coding standards (PEP8):**
- snake_case for files, functions, variables
- Functions start with verbs (e.g. read_json_file, calculate_resolution_hours, check_sla_compliance)
- No camelCase; no generic names (data, temp, test, x)
→ Weight in sub-score: Python file naming 20, Function naming 20, Variable naming 20

**Folder naming:**
- Lowercase, snake_case; expected: src, data, config, tests
→ Weight: 15

**Data file naming:**
- Format <layer>_<entity>.<format> (e.g. bronze_issues.json, silver_issues.parquet, gold_sla.csv, gold_sla_by_analyst.csv)
→ Weight: 15

**Column naming:**
- snake_case; timestamps end with _at (created_at, resolved_at); booleans start with is_ (is_sla_met)
→ Weight: 10

Use the Naming audit section and the provided code (main pipeline, sla_calculation) to score naming_conventions_score (0–5)."""

USER_PROMPT_TEMPLATE = """Use only the provided evidence below.
Score according to the Gold layer and report rules given in the system prompt.

Return ONLY valid JSON with no other text:
{{
  "medallion_architecture": 0-5,
  "sla_logic": 0-5,
  "pipeline_organization": 0-5,
  "readme_clarity": 0-5,
  "code_quality": 0-5,
  "cloud_ingestion": 0-5,
  "naming_conventions_score": 0-5,
  "summary": "short technical summary"
}}

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

# --- Detailed technical evaluation report (senior data engineer code review) ---
REPORT_SYSTEM_PROMPT = """You are a senior Data Engineering lead writing a detailed technical evaluation report for a repository that implements a Medallion Architecture pipeline (e.g. for Jira/ticket data).

Your report will be read by technical stakeholders. Write in a clear, professional tone. Use the provided evidence and the scores already assigned to produce a structured review that:

1. **Executive summary** – 2–3 sentences on overall assessment and final score.
2. **Architecture decisions** – How the repo is structured (e.g. raw → bronze → silver → gold), entrypoints, separation of concerns. Justify whether choices are appropriate.
3. **Data format choices** – Which formats are used (JSON, Parquet, CSV, etc.) at each layer and why that is good or could be improved.
4. **Medallion structure** – How well Raw/Bronze/Silver/Gold layers are implemented; what is normalized, what is enriched, what is aggregated. Reference actual paths or file names from the evidence.
5. **Best practices and issues** – What is done well (e.g. config via env, tests, README) and what is missing or problematic (e.g. hardcoded paths, no tests, unclear SLA logic).
6. **Score justification** – For each scored dimension (medallion architecture, SLA logic, pipeline organization, readme clarity, code quality, cloud ingestion, naming conventions, security practices), briefly explain why the repository received that score based on the evidence. Use the exact score values provided.

Use markdown-style headers (##, ###) and short paragraphs. Be specific: cite file names, function names, or snippets from the evidence where relevant. Total length: roughly 400–800 words."""

REPORT_USER_TEMPLATE = """Based on the repository evidence below and the scores already assigned, write the detailed technical evaluation report as specified in the system prompt.

**Scores assigned (0–100 scale):**
{scores_text}

**Evidence:**
{evidence}
"""

REPORT_MAX_TOKENS = 2500
REPORT_MAX_CHARS = 12000  # cap for Excel cell

# --- Evaluation summary (Excel-safe; limit enforced in prompt, no truncation) ---
SUMMARY_DEFAULT_MAX_CHARS = 1800

SUMMARY_SYSTEM_PROMPT = """You are generating a technical evaluation summary for a data engineering repository.

Your response MUST include two parts:

1. **Evaluation summary** – Explain why the repository received these scores and include a short Docker validation section. Use only the provided docker_results data. Do not change any numeric scores or invent test results.

2. **Suggested Improvements** – A section headed "## Suggested Improvements". Based ONLY on the Detected flags (checks that show "Fail"), list actionable, specific recommendations. You must NOT invent problems: only suggest improvements for failed checks. Be concise; mention exact files or paths when the evidence supports it (e.g. "Rename file 'X' to snake_case", "Add data/raw layer", "Move credentials in config.py to environment variables"). If no checks failed, write "No suggested improvements based on the evaluation." Keep each suggestion to one line.

IMPORTANT:
- Do not change any numeric scores
- Do not invent test results or issues
- Suggested Improvements must be derived only from failed flags in the list provided
- Limit the response to {max_chars} characters
- Use line breaks for readability"""

SUMMARY_USER_TEMPLATE = """Scores:
{scores}

Detected flags:
{flags}

Docker results:
{docker_results}

Write the evaluation summary (with a short Docker validation section) and then a "## Suggested Improvements" section based only on the failed flags above. Maximum {max_chars} characters. Do not change any scores or invent results."""


def _format_scores_for_prompt(scores: dict[str, Any]) -> str:
    lines = []
    for k in ["final_score", "medallion_architecture", "sla_logic", "pipeline_organization", "readme_clarity", "code_quality", "naming_conventions_score", "cloud_ingestion", "security_practices_score", "sensitive_data_exposure_score"]:
        if k in scores:
            lines.append(f"- {k}: {scores[k]}")
    lines.append(f"- pipeline_runs: {'Yes' if scores.get('pipeline_runs') in (True, 100) else 'No'}")
    lines.append(f"- gold_generated: {'Yes' if scores.get('gold_generated') in (True, 100) else 'No'}")
    return "\n".join(lines) if lines else "(none)"


def _format_flags_for_prompt(check_results: dict[str, bool]) -> str:
    return "\n".join(f"- {k}: {'Pass' if v else 'Fail'}" for k, v in sorted(check_results.items())) or "(none)"


def format_docker_results_for_summary(run_result: dict[str, Any] | None, max_len: int = 1500) -> str:
    """Format pipeline run result (Docker execution) for the summary prompt. Only use provided data; do not invent."""
    if not run_result:
        return "No Docker run performed."
    parts = [
        f"Pipeline ran: {'Yes' if run_result.get('pipeline_runs') else 'No'}",
        f"Return code: {run_result.get('return_code', 'N/A')}",
        f"Gold/reports generated: {'Yes' if run_result.get('gold_generated') else 'No'}",
    ]
    if run_result.get("error"):
        parts.append(f"Error: {(run_result['error'] or '')[:400]}")
    if run_result.get("stderr"):
        parts.append(f"Stderr: {(run_result['stderr'] or '')[:400]}")
    if run_result.get("stdout"):
        parts.append(f"Stdout: {(run_result['stdout'] or '')[:400]}")
    text = "\n".join(parts)
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _format_docker_results(run_result: dict[str, Any] | None, max_len: int = 1500) -> str:
    return format_docker_results_for_summary(run_result, max_len)


def _summary_system_prompt(max_chars: int) -> str:
    return SUMMARY_SYSTEM_PROMPT.format(max_chars=max_chars)


def _summary_user_prompt(
    check_results: dict[str, bool],
    scores: dict[str, Any],
    max_chars: int,
    docker_results: str,
) -> str:
    return SUMMARY_USER_TEMPLATE.format(
        max_chars=max_chars,
        scores=_format_scores_for_prompt(scores),
        flags=_format_flags_for_prompt(check_results),
        docker_results=docker_results,
    )


def generate_evaluation_summary_llm(
    check_results: dict[str, bool],
    scores: dict[str, Any],
    max_chars: int = SUMMARY_DEFAULT_MAX_CHARS,
    docker_results: str | None = None,
) -> Optional[str]:
    """
    Generate a short technical summary via LLM. The character limit is enforced only in the prompt;
    we do not truncate the response. The LLM must explain the given scores and checks, not modify them.
    Include a short Docker validation section using only the provided docker_results.
    Returns None if API key missing or on error (caller should fall back to deterministic summary).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set, skipping LLM evaluation summary")
        return None

    docker_text = docker_results if docker_results is not None else _format_docker_results(None)
    system_prompt = _summary_system_prompt(max_chars)
    user_prompt = _summary_user_prompt(check_results, scores, max_chars, docker_text)
    # ~4 chars per token; cap tokens so model is unlikely to exceed limit
    max_tokens = min(2048, (max_chars // 3) + 50)

    client = OpenAI(api_key=api_key)
    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=max_tokens,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                return None
            # Do not slice: limit is enforced by prompt only
            return content
        except Exception as e:
            last_error = e
            if _is_retryable_error(e) and attempt < LLM_MAX_RETRIES:
                log.warning("generate_evaluation_summary_llm attempt %s/%s failed (retrying): %s", attempt, LLM_MAX_RETRIES, e)
                time.sleep(LLM_RETRY_DELAY_SEC)
            else:
                log.warning("generate_evaluation_summary_llm failed: %s", e)
                return None
    return None


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


def _is_retryable_error(e: Exception) -> bool:
    """True for rate limit, server errors, timeouts, connection issues."""
    err_str = str(e).lower()
    if "429" in err_str or "rate" in err_str:
        return True
    if "503" in err_str or "502" in err_str or "500" in err_str:
        return True
    if "timeout" in err_str or "timed out" in err_str:
        return True
    if "connection" in err_str or "connect" in err_str:
        return True
    return False


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
    readme_trimmed = readme[:8000].strip()
    prompt = README_RUN_COMMAND_PROMPT.format(readme=readme_trimmed)
    client = OpenAI(api_key=api_key)
    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content or content.upper() == "UNKNOWN":
                return None
            if "python" not in content.lower():
                return None
            return content
        except Exception as e:
            last_error = e
            if _is_retryable_error(e) and attempt < LLM_MAX_RETRIES:
                log.warning("get_run_command_from_readme attempt %s/%s failed (retrying): %s", attempt, LLM_MAX_RETRIES, e)
                time.sleep(LLM_RETRY_DELAY_SEC)
            else:
                log.warning("get_run_command_from_readme failed: %s", e)
                return None
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
    client = OpenAI(api_key=api_key)
    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
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
            last_error = e
            if _is_retryable_error(e) and attempt < LLM_MAX_RETRIES:
                log.warning("evaluate_with_llm attempt %s/%s failed (retrying): %s", attempt, LLM_MAX_RETRIES, e)
                time.sleep(LLM_RETRY_DELAY_SEC)
            else:
                log.exception("LLM call failed")
                return _default_llm_result(str(e))
    return _default_llm_result(str(last_error) if last_error else "Unknown error")


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


def generate_detailed_report(context: dict[str, Any], scores: dict[str, Any]) -> str:
    """
    Generate a detailed technical evaluation report (senior data engineer code review style).
    Uses the same evidence as scoring plus the assigned scores to produce a structured report
    covering architecture, data formats, medallion structure, practices, and score justification.
    On failure or missing API key, returns a short fallback message.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set, skipping detailed report")
        return "Detailed report not generated (OPENAI_API_KEY not set)."

    evidence = context_to_string(context)
    if len(evidence) > 28000:
        evidence = evidence[:28000] + "\n\n... [evidence truncated for report]"

    lines = []
    for k, v in sorted(scores.items()):
        if k == "summary" or k == "evaluation_report":
            continue
        if isinstance(v, bool):
            lines.append(f"- {k}: {'Yes' if v else 'No'}")
        elif isinstance(v, (int, float)):
            lines.append(f"- {k}: {v}")
        else:
            lines.append(f"- {k}: {v}")
    scores_text = "\n".join(lines) if lines else "(no scores)"

    user_prompt = REPORT_USER_TEMPLATE.format(evidence=evidence, scores_text=scores_text)
    client = OpenAI(api_key=api_key)
    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=REPORT_MAX_TOKENS,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                return "Detailed report could not be generated (empty model response)."
            if len(content) > REPORT_MAX_CHARS:
                content = content[:REPORT_MAX_CHARS] + "\n\n... [report truncated]"
            return content
        except Exception as e:
            last_error = e
            if _is_retryable_error(e) and attempt < LLM_MAX_RETRIES:
                log.warning("generate_detailed_report attempt %s/%s failed (retrying): %s", attempt, LLM_MAX_RETRIES, e)
                time.sleep(LLM_RETRY_DELAY_SEC)
            else:
                log.warning("generate_detailed_report failed: %s", e)
                return f"Detailed report could not be generated: {str(e)[:200]}."
    return f"Detailed report could not be generated: {str(last_error)[:200]}." if last_error else "Detailed report could not be generated."
