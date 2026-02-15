"""Clone repositories into temp_repos/<repo_name>. Skip or pull if exists."""

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from .logger import get_logger
from .utils import get_temp_repos_dir

log = get_logger(__name__)

CLONE_MAX_RETRIES = 3
CLONE_RETRY_DELAY_SEC = 2


def repo_name_from_url(url: str) -> str:
    """Derive a safe directory name from repo URL (e.g. user/project1 -> user_project1)."""
    url = str(url).strip().rstrip("/")
    # https://github.com/user/repo or git@github.com:user/repo.git
    match = re.search(r"(?:/|:)([^/]+)/([^/]+?)(?:\.git)?$", url)
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    # fallback: sanitize last segment
    name = url.split("/")[-1].replace(".git", "")
    return re.sub(r"[^\w\-.]", "_", name) or "repo"


def clone_repo(repo_url: str, pull_if_exists: bool = True) -> Optional[Path]:
    """
    Clone repo into temp_repos/<repo_name>. If directory exists, pull latest when pull_if_exists.
    Return local path or None on error.
    """
    base = get_temp_repos_dir()
    base.mkdir(parents=True, exist_ok=True)
    name = repo_name_from_url(repo_url)
    dest = base / name

    if dest.exists() and (dest / ".git").exists():
        if pull_if_exists:
            try:
                subprocess.run(
                    ["git", "pull", "--quiet"],
                    cwd=dest,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                log.warning("git pull timed out for %s", dest)
            except Exception as e:
                log.warning("git pull failed for %s: %s", dest, e)
        return dest

    last_error = None
    for attempt in range(1, CLONE_MAX_RETRIES + 1):
        try:
            subprocess.run(
                ["git", "clone", "--quiet", repo_url, str(dest)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return dest
        except subprocess.CalledProcessError as e:
            last_error = e
            log.warning("clone attempt %s/%s failed url=%s stderr=%s", attempt, CLONE_MAX_RETRIES, repo_url, (e.stderr or "")[:200])
            if attempt < CLONE_MAX_RETRIES:
                if dest.exists():
                    try:
                        shutil.rmtree(dest)
                    except Exception as rm_e:
                        log.warning("could not remove partial clone %s: %s", dest, rm_e)
                time.sleep(CLONE_RETRY_DELAY_SEC)
        except subprocess.TimeoutExpired:
            log.error("clone timed out url=%s (attempt %s/%s)", repo_url, attempt, CLONE_MAX_RETRIES)
            return None
        except Exception as e:
            last_error = e
            log.warning("clone attempt %s/%s error url=%s: %s", attempt, CLONE_MAX_RETRIES, repo_url, e)
            if attempt < CLONE_MAX_RETRIES:
                time.sleep(CLONE_RETRY_DELAY_SEC)

    if last_error:
        stderr = getattr(last_error, "stderr", None) or str(last_error)
        log.error("clone failed after %s attempts url=%s last_error=%s", CLONE_MAX_RETRIES, repo_url, stderr[:300])
    return None
