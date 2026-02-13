"""Run pipeline in repo: venv or Docker, install deps, run entrypoint; verify data/gold has CSV."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger(__name__)

PIPELINE_TIMEOUT = 180
MAX_FILE_SIZE = 4000
DOCKER_IMAGE = "python:3.12-slim"

# Env vars to pass into the container when running in Docker (e.g. Azure Service Principal for read-only access).
# Set these on the host (or in .env) so the pipeline can authenticate to Azure Blob etc.
AZURE_ENV_VARS = (
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_CLIENT_CERTIFICATE_PATH",
    "AZURE_USE_IDENTITY",
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


def _venv_python(repo_path: Path) -> Optional[Path]:
    """Path to venv python (Windows or Unix)."""
    for rel in ["venv/Scripts/python.exe", "venv/bin/python", ".venv/Scripts/python.exe", ".venv/bin/python"]:
        p = repo_path / rel
        if p.exists():
            return p
    return None


def _create_venv_and_install(repo_path: Path) -> tuple[bool, str]:
    """Create venv and pip install -r requirements.txt. Return (success, error_message)."""
    venv_dir = repo_path / "venv"
    if venv_dir.exists():
        py = _venv_python(repo_path)
        if py:
            req = repo_path / "requirements.txt"
            if req.exists():
                try:
                    subprocess.run(
                        [str(py), "-m", "pip", "install", "-q", "-r", str(req)],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                except subprocess.TimeoutExpired:
                    return False, "pip install timed out"
                except Exception as e:
                    return False, str(e)
            return True, ""
        return False, "venv exists but python not found"

    try:
        subprocess.run(
            [sys.executable, "-m", "venv", "venv"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        return False, f"venv creation failed: {e}"

    py = _venv_python(repo_path)
    if not py:
        return False, "venv created but python not found"

    req = repo_path / "requirements.txt"
    if req.exists():
        try:
            r = subprocess.run(
                [str(py), "-m", "pip", "install", "-q", "-r", str(req)],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode != 0:
                return False, r.stderr or "pip install failed"
        except subprocess.TimeoutExpired:
            return False, "pip install timed out"
        except Exception as e:
            return False, str(e)
    return True, ""


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
        return (-1, "", "Docker not found. Install Docker or unset RUN_IN_DOCKER.")
    except Exception as e:
        return (-1, "", str(e))


def run_pipeline(
    repo_path: Path,
    run_command_override: Optional[str] = None,
    run_in_docker: Optional[bool] = None,
) -> dict:
    """
    Run the repo pipeline (venv or Docker), then verify data/gold has CSV.
    run_command_override: if set, use this command (e.g. from README via LLM) instead of auto-discovery.
    run_in_docker: if True (or RUN_IN_DOCKER=1), run inside a Docker container.
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

    use_docker = run_in_docker if run_in_docker is not None else (
        os.environ.get("RUN_IN_DOCKER", "").strip().lower() in ("1", "true", "yes")
    )

    # Resolve command string (for Docker) or (py, args) for local
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

    if use_docker:
        code, out, err = _run_in_docker(repo_path, cmd_str)
        result["return_code"] = code
        result["stdout"] = (out or "")[:MAX_FILE_SIZE]
        result["stderr"] = (err or "")[:MAX_FILE_SIZE]
        result["pipeline_runs"] = code == 0
        if code != 0 and not result["error"]:
            result["error"] = err or f"Exit code {code}"
        result["gold_generated"] = _gold_has_csv(repo_path)
        return result

    # Local: venv + subprocess
    ok, err = _create_venv_and_install(repo_path)
    if not ok:
        result["error"] = err
        return result

    py = _venv_python(repo_path)
    if not py:
        result["error"] = "venv python not found"
        return result

    # Build run_cmd: replace "python" with venv python
    parts = cmd_str.split()
    if parts and parts[0].lower() == "python":
        run_cmd = [str(py)] + parts[1:]
    else:
        run_cmd = [str(py), cmd_str]

    try:
        proc = subprocess.run(
            run_cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=PIPELINE_TIMEOUT,
        )
        result["stdout"] = (proc.stdout or "")[:MAX_FILE_SIZE]
        result["stderr"] = (proc.stderr or "")[:MAX_FILE_SIZE]
        result["return_code"] = proc.returncode
        result["pipeline_runs"] = proc.returncode == 0
    except subprocess.TimeoutExpired:
        result["error"] = "Pipeline execution timed out (180s)"
        result["stderr"] = "Timeout"
        return result
    except Exception as e:
        result["error"] = str(e)
        return result

    result["gold_generated"] = _gold_has_csv(repo_path)
    if result["error"] is None and not result["pipeline_runs"]:
        result["error"] = result["stderr"] or f"Exit code {result['return_code']}"
    return result
