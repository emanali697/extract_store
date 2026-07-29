"""Backend configuration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Load environment variables from backend/.env if present.
load_dotenv(BASE_DIR / ".env")


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if not value:
        return default
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


# Where uploaded videos are stored — co-located with this backend folder
UPLOAD_DIR = _env_path("UPLOAD_DIR", BASE_DIR / "uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Where pipeline writes per-job output
JOBS_DIR = _env_path("JOBS_DIR", BASE_DIR / "jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)


# Pipeline lives outside the backend now (after the user moved backend/frontend
# into an `extract stores/` folder). Walk up the tree to locate it so this
# config keeps working regardless of where the backend ends up.
# Override with PIPELINE_DIR environment variable.
def _find_pipeline_dir():
    env_value = os.environ.get("PIPELINE_DIR")
    if env_value:
        path = Path(env_value)
        if path.is_absolute():
            return path
        return BASE_DIR / path

    # Firebase Functions contains the deployable pipeline copy. Reuse it for
    # local development when the former external ../pipeline folder is absent.
    bundled_pipeline = PROJECT_ROOT / "functions" / "pipeline"
    if (bundled_pipeline / "main.py").exists():
        return bundled_pipeline

    here = BASE_DIR
    for _ in range(4):  # walk up at most 4 levels
        candidate = here / "pipeline" / "main.py"
        if candidate.exists():
            return here / "pipeline"
        here = here.parent
    return PROJECT_ROOT / "pipeline"


PIPELINE_DIR = _find_pipeline_dir()
if not PIPELINE_DIR.is_dir():
    raise RuntimeError(
        f"PIPELINE_DIR is not a valid directory: {PIPELINE_DIR}. "
        "Set it to the directory containing pipeline/main.py, or unset it."
    )
PIPELINE_MAIN = PIPELINE_DIR / "main.py"
PIPELINE_RUN_V6 = PIPELINE_DIR / "run_v6.py"

# Python interpreter used to run the pipeline subprocesses.
# The pipeline often has its own dependency set (opencv-python, google-cloud-vision,
# etc.) that may not be installed in the backend virtualenv. Point this at the
# Python executable that has those packages installed. Defaults to the same Python
# running the backend so existing setups keep working.
PIPELINE_PYTHON = Path(os.environ.get("PIPELINE_PYTHON", sys.executable)).resolve()

# Firebase default project
FIREBASE_KEY_PATH = _env_path("FIREBASE_KEY_PATH", BASE_DIR / "firebase_key.json")
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "stores")

# traders-data-live project
TRADERS_KEY_PATH = _env_path("TRADERS_KEY_PATH", BASE_DIR / "traders_data_live_key.json")
TRADERS_COLLECTION = os.environ.get("TRADERS_COLLECTION", "stores")
TRADERS_PROJECT_ID = os.environ.get("TRADERS_PROJECT_ID", "traders-data-live")
TRADERS_WRITES_ENABLED = (
    os.environ.get("TRADERS_WRITES_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)

# CORS — Vite dev server (covers common Vite ports in case 5173 is taken)
_allowed = os.environ.get("ALLOWED_ORIGINS")
if _allowed:
    ALLOWED_ORIGINS = [origin.strip() for origin in _allowed.split(",") if origin.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5176",
    ]
