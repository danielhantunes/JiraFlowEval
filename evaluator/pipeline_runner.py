"""Run pipeline in repo: Docker only (production-like), install deps, run entrypoint; verify data/gold has CSV."""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger(__name__)

PIPELINE_TIMEOUT = 180
MAX_FILE_SIZE = 4000
DOCKER_IMAGE = "python:3.12-slim"
DEFAULT_RAW_INPUT_FILENAME = "tickets_raw.json"

# Env vars to pass into the pipeline container. Main set: Azure credentials + blob config (see .env.example).
# Optional: RAW_INPUT_FILENAME. Only vars that are set and non-empty are passed.
AZURE_ENV_VARS = (
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_CLIENT_CERTIFICATE_PATH",
    "AZURE_USE_IDENTITY",
    "AZURE_ACCOUNT_URL",
    "AZURE_CONTAINER_NAME",
    "AZURE_BLOB_NAME",
    "AZURE_BLOB_PREFIX",
    "RAW_INPUT_FILENAME",
)

# Root entry points (run as script: python main.py)
ROOT_ENTRYPOINTS = ["main.py", "run_pipeline.py"]
# Module entry points (run as module: python -m src.main)
MODULE_ENTRYPOINTS = ["src/main.py", "src/run_pipeline.py"]
GOLD_DIR = Path("data/gold")

# Patterns to detect Azure/cloud ingestion in repo code
AZURE_INGESTION_MARKERS = (
    "azure",
    "AZURE_ACCOUNT_URL",
    "BlobServiceClient",
    "DefaultAzureCredential",
    "azure-storage-blob",
)


def _repo_uses_azure_ingestion(repo_path: Path) -> bool:
    """Return True if the repo appears to use Azure/cloud ingestion (so raw file check is skipped)."""
    search_dirs = [
        repo_path / "src" / "ingestion",
        repo_path / "ingestion",
        repo_path / "src",
    ]
    search_files = [repo_path / ".env.example", repo_path / "config.py", repo_path / "src" / "utils" / "config.py"]
    paths_to_check = []
    for d in search_dirs:
        if d.is_dir():
            paths_to_check.extend(d.rglob("*.py"))
    for f in search_files:
        if f.is_file():
            paths_to_check.append(f)
    for path in paths_to_check:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            continue
        for marker in AZURE_INGESTION_MARKERS:
            if marker.lower() in text:
                return True
    return False


def _get_repo_raw_input_filename(repo_path: Path) -> str:
    """Resolve expected raw input filename: .env.example, then Python getenv default, then evaluator env, then default."""
    # .env.example: RAW_INPUT_FILENAME=...
    for env_name in [".env.example", ".env.sample"]:
        p = repo_path / env_name
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith("RAW_INPUT_FILENAME="):
                        value = line.split("=", 1)[1].strip().strip("'\"").split("#")[0].strip()
                        if value:
                            return value
            except Exception:
                pass
    # Python: getenv("RAW_INPUT_FILENAME", "something")
    getenv_re = re.compile(r'getenv\s*\(\s*["\']RAW_INPUT_FILENAME["\']\s*,\s*["\']([^"\']+)["\']\s*\)', re.IGNORECASE)
    for base in (repo_path / "src", repo_path / "ingestion", repo_path):
        if not base.is_dir():
            continue
        for f in base.rglob("*.py"):
            try:
                m = getenv_re.search(f.read_text(encoding="utf-8", errors="replace"))
                if m:
                    return m.group(1).strip()
            except Exception:
                pass
    # Evaluator env override
    ev = os.environ.get("RAW_INPUT_FILENAME", "").strip()
    if ev:
        return ev
    return DEFAULT_RAW_INPUT_FILENAME


# Minimal raw JSON so pipelines that expect tickets_raw.json can run when file is missing in clone (e.g. CI).
# Schema: must have "issues" list (jiraflow-sample1 and similar); empty list is valid.
_MINIMAL_RAW_JSON = b'{"issues": []}'


def _seed_minimal_raw_file(repo_path: Path, filename: str) -> bool:
    """Write a minimal raw JSON file at repo root so the pipeline can run. Returns True if written."""
    raw_path = repo_path / filename
    try:
        raw_path.write_bytes(_MINIMAL_RAW_JSON)
        log.info("Seeded minimal raw input %s for pipeline run (file was missing in clone).", filename)
        return True
    except Exception as e:
        log.warning("Could not seed %s: %s", filename, e)
        return False


def _require_raw_input_file_exists(repo_path: Path) -> Optional[str]:
    """
    If repo does not use Azure ingestion, require that the raw input file exists at repo root.
    If missing, try to seed a minimal file so the pipeline can run (e.g. in CI); only return error if seed fails.
    Returns None if ok (file existed or was seeded), or an error message string if the file is missing and seed failed.
    """
    if _repo_uses_azure_ingestion(repo_path):
        return None
    filename = _get_repo_raw_input_filename(repo_path)
    raw_path = repo_path / filename
    if raw_path.is_file():
        return None
    if _seed_minimal_raw_file(repo_path, filename):
        return None
    return (
        f"Repo uses local file ingestion but required input file is missing: {filename} "
        f"(expected at repo root). Add the file or use Azure/cloud ingestion."
    )


def _find_entrypoint(repo_path: Path) -> Optional[tuple[Path, bool]]:
    """Return (entry_path, is_module). is_module True => run with python -m <module>."""
    for name in ROOT_ENTRYPOINTS:
        p = repo_path / name
        if p.is_file():
            return (p, False)
    for rel in MODULE_ENTRYPOINTS:
        p = repo_path / rel
        if p.is_file():
            return (p, True)
    return None


def _gold_has_csv(repo_path: Path) -> bool:
    gold = repo_path / GOLD_DIR
    if not gold.is_dir():
        return False
    for f in gold.rglob("*.csv"):
        if f.is_file():
            return True
    return False


def _entrypoint_to_cmd_string(entry_path: Path, repo_path: Path, is_module: bool) -> str:
    """Build the command string as the user would run it (e.g. python -m src.main)."""
    if is_module:
        rel = entry_path.relative_to(repo_path).with_suffix("")
        module_name = ".".join(rel.parts)
        return f"python -m {module_name}"
    return f"python {entry_path.name}"


def _docker_env_args() -> list[str]:
    """Build -e VAR=value args for Azure (and similar) env vars set on the host."""
    args = []
    for name in AZURE_ENV_VARS:
        value = os.environ.get(name)
        if value is not None and value.strip():
            args.extend(["-e", f"{name}={value}"])
    return args


def _run_in_docker(repo_path: Path, cmd_str: str) -> tuple[int, str, str]:
    """Run pip install + cmd_str inside a container with repo mounted. Return (returncode, stdout, stderr)."""
    # When evaluator runs inside Docker (e.g. CI), repo_path is like /app/temp_repos/RepoName; the host path
    # is different. Set HOST_TEMP_REPOS_DIR to the host's temp_repos path so the volume mount is correct.
    host_repos = os.environ.get("HOST_TEMP_REPOS_DIR")
    if host_repos:
        mount_src = Path(host_repos) / repo_path.name
    else:
        mount_src = repo_path.resolve()
    mount = f"{mount_src}:/app"
    script = f"pip install -q -r requirements.txt 2>/dev/null; {cmd_str}"
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        mount,
        "-w",
        "/app",
        "-e",
        "PYTHONUNBUFFERED=1",
    ]
    docker_cmd.extend(_docker_env_args())
    docker_cmd.extend([DOCKER_IMAGE, "bash", "-c", script])
    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=PIPELINE_TIMEOUT,
            cwd=repo_path,
        )
        return (proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        return (-1, "", "Pipeline execution timed out (180s)")
    except FileNotFoundError:
        return (-1, "", "Docker not found. Docker is required to run candidate pipelines; please install Docker.")
    except Exception as e:
        return (-1, "", str(e))


def run_pipeline(
    repo_path: Path,
    run_command_override: Optional[str] = None,
) -> dict:
    """
    Run the repo pipeline in Docker (mandatory for production-like evaluation), then verify data/gold has CSV.
    run_command_override: if set, use this command (e.g. from README via LLM) instead of auto-discovery.
    """
    repo_path = Path(repo_path)
    result = {
        "pipeline_runs": False,
        "gold_generated": False,
        "error": None,
        "stdout": "",
        "stderr": "",
        "return_code": None,
    }

    cmd_str: Optional[str] = None
    entry_result = _find_entrypoint(repo_path)
    if run_command_override:
        cmd_str = run_command_override.strip()
    elif entry_result:
        entry_path, is_module = entry_result
        cmd_str = _entrypoint_to_cmd_string(entry_path, repo_path, is_module)
    if not cmd_str:
        result["error"] = "No main.py, run_pipeline.py, or src/main.py found (and no run command from README)"
        return result

    raw_check_error = _require_raw_input_file_exists(repo_path)
    if raw_check_error:
        log.warning("Skipping pipeline run: %s", raw_check_error)
        result["error"] = raw_check_error
        return result

    code, out, err = _run_in_docker(repo_path, cmd_str)
    result["return_code"] = code
    result["stdout"] = (out or "")[:MAX_FILE_SIZE]
    result["stderr"] = (err or "")[:MAX_FILE_SIZE]
    result["pipeline_runs"] = code == 0
    if code != 0 and not result["error"]:
        result["error"] = err or f"Exit code {code}"
    result["gold_generated"] = _gold_has_csv(repo_path)
    return result
