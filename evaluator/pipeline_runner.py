"""Run pipeline in repo: Docker only (production-like), install deps, run entrypoint; verify data/gold has CSV."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger(__name__)

PIPELINE_TIMEOUT = 180
MAX_FILE_SIZE = 4000
DOCKER_IMAGE = "python:3.12-slim"

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
        module_name = str(rel).replace("\\", ".")
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
    repo_abs = repo_path.resolve()
    # Docker on Windows may need the path in a specific form; use as-is and let Docker handle it
    mount = f"{repo_abs}:/app"
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

    code, out, err = _run_in_docker(repo_path, cmd_str)
    result["return_code"] = code
    result["stdout"] = (out or "")[:MAX_FILE_SIZE]
    result["stderr"] = (err or "")[:MAX_FILE_SIZE]
    result["pipeline_runs"] = code == 0
    if code != 0 and not result["error"]:
        result["error"] = err or f"Exit code {code}"
    result["gold_generated"] = _gold_has_csv(repo_path)
    return result
