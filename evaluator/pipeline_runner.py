"""Run pipeline in repo: venv, install deps, run entrypoint; verify data/gold has CSV."""

import subprocess
import sys
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger(__name__)

PIPELINE_TIMEOUT = 180
MAX_FILE_SIZE = 4000

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


def run_pipeline(repo_path: Path) -> dict:
    """
    Create venv, install requirements, run main.py or run_pipeline.py (timeout 180s).
    Return dict: pipeline_runs (bool), gold_generated (bool), error (str|None),
    stdout (str), stderr (str), return_code (int).
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

    entry_result = _find_entrypoint(repo_path)
    if not entry_result:
        result["error"] = "No main.py, run_pipeline.py, or src/main.py found"
        return result

    entry_path, is_module = entry_result

    ok, err = _create_venv_and_install(repo_path)
    if not ok:
        result["error"] = err
        return result

    py = _venv_python(repo_path)
    if not py:
        result["error"] = "venv python not found"
        return result

    if is_module:
        # e.g. src/main.py -> python -m src.main
        rel = entry_path.relative_to(repo_path).with_suffix("")
        module_name = str(rel).replace("\\", ".")
        run_cmd = [str(py), "-m", module_name]
    else:
        run_cmd = [str(py), entry_path.name]

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
