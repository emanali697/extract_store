"""Cloud Functions configuration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Firestore collections
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "stores")
TRADERS_COLLECTION = os.environ.get("TRADERS_COLLECTION", "stores")
TRADERS_PROJECT_ID = os.environ.get("TRADERS_PROJECT_ID", "traders-data-live")
JOBS_COLLECTION = os.environ.get("JOBS_COLLECTION", "jobs")
TRADERS_WRITES_ENABLED = (
    os.environ.get("TRADERS_WRITES_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)

# Cloud Storage bucket (new Firebase projects use firebasestorage.app)
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "store-extract")
STORAGE_BUCKET = os.environ.get(
    "STORAGE_BUCKET",
    f"{PROJECT_ID}.firebasestorage.app",
)

# Pub/Sub topic name for pipeline trigger
PIPELINE_TOPIC = os.environ.get("PIPELINE_TOPIC", "run-pipeline")

# Pipeline runtime
PIPELINE_DIR = Path(__file__).resolve().parent / "pipeline"
PIPELINE_MAIN = PIPELINE_DIR / "main.py"
PIPELINE_PYTHON = Path(os.environ.get("PIPELINE_PYTHON", sys.executable)).resolve()

# CORS allowed origins (comma-separated)
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
