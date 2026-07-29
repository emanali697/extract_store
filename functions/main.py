"""Firebase Functions entry points for Store Extractor backend."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import tempfile
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import firestore, functions as admin_functions
from firebase_functions import https_fn, pubsub_fn, tasks_fn, options, params

TRADERS_SECRET = params.SecretParam("TRADERS_SERVICE_ACCOUNT_JSON")
from google.cloud import pubsub_v1

from config import (
    ALLOWED_ORIGINS,
    FIRESTORE_COLLECTION,
    JOBS_COLLECTION,
    PIPELINE_TOPIC,
    PROJECT_ID,
    STORAGE_BUCKET,
    TRADERS_COLLECTION,
    TRADERS_WRITES_ENABLED,
)
from db import (
    Job,
    claim_queued_job,
    create_job as db_create_job,
    get_job,
    list_jobs,
    persist_job,
    job_to_dict,
)
from storage import (
    download_file,
    exists,
    job_output_prefix,
    signed_url,
    upload_dir,
    upload_file,
    video_path,
)
from runner import run_pipeline as run_pipeline_async

# Initialize Firebase Admin SDK once using the runtime service account.
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


def _cors_headers(origin: str | None) -> dict[str, str]:
    allowed = ALLOWED_ORIGINS or ["*"]
    if origin and origin in allowed:
        ao = origin
    elif "*" in allowed:
        ao = "*"
    else:
        ao = allowed[0] if allowed else ""
    return {
        "Access-Control-Allow-Origin": ao,
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }


def _json_response(data: Any, status: int = 200, origin: str | None = None) -> https_fn.Response:
    headers = {"Content-Type": "application/json; charset=utf-8", **_cors_headers(origin)}
    return https_fn.Response(
        json.dumps(data, ensure_ascii=False, default=str),
        status=status,
        headers=headers,
    )


def _error_response(message: str, status: int = 400, origin: str | None = None) -> https_fn.Response:
    return _json_response({"detail": message}, status=status, origin=origin)


def _get_origin(req: https_fn.Request) -> str | None:
    return req.headers.get("Origin")


def _get_json(req: https_fn.Request) -> dict:
    try:
        return json.loads(req.get_data(as_text=True)) or {}
    except Exception:
        return {}


def _reconcile_stale_job(job: Job) -> Job:
    """Turn abandoned queue/worker states into a visible, retryable error."""
    if job.status not in ("queued", "running", "finalizing") or not job.updated_at:
        return job
    updated_at = job.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    max_age = 300 if job.status == "queued" else 660
    if age_seconds <= max_age:
        return job
    previous = job.status
    job.status = "error"
    job.error = f"job became stale while {previous}; it can be started again"
    persist_job(job)
    return job


# ---------------------------------------------------------------------------
# HTTP functions
# ---------------------------------------------------------------------------

@https_fn.on_request()
def create_job(req: https_fn.Request) -> https_fn.Response:
    """Create a new job and return its ID."""
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    if req.method != "POST":
        return _error_response("method not allowed", status=405, origin=origin)

    payload = _get_json(req)
    job = Job(
        job_id=firestore.client().collection(JOBS_COLLECTION).document().id[:12],
        video_name=payload.get("videoName", ""),
        street_name=payload.get("streetName", ""),
        city=payload.get("city", ""),
        district=payload.get("district", ""),
        speed_mode=payload.get("speedMode", "auto"),
        enable_places=payload.get("enablePlaces", True),
        enable_status=payload.get("enableStatus", True),
        status="uploading",
    )
    db_create_job(job)
    return _json_response({"jobId": job.job_id, "status": job.status}, origin=origin)


@https_fn.on_request()
def start_job(req: https_fn.Request) -> https_fn.Response:
    """Trigger the pipeline for an existing job."""
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    if req.method != "POST":
        return _error_response("method not allowed", status=405, origin=origin)

    payload = _get_json(req)
    job_id = payload.get("jobId")
    if not job_id:
        return _error_response("jobId is required", origin=origin)

    job = get_job(job_id)
    if not job:
        return _error_response("job not found", status=404, origin=origin)
    if job.status in ("queued", "running"):
        return _error_response("job already started", status=409, origin=origin)
    if job.status == "done":
        return _error_response("job already completed", status=409, origin=origin)

    storage_path = video_path(job_id)
    if not exists(storage_path):
        return _error_response("video not found in storage", origin=origin)

    job.video_storage_path = storage_path
    job.status = "queued"
    job.error = None
    persist_job(job)

    # Enqueue the long-running worker only after the complete video exists.
    # Cloud Tasks supports a 30-minute dispatch deadline, unlike Pub/Sub event
    # functions which are capped at 9 minutes.
    try:
        queue = admin_functions.task_queue("runpipelinetask")
        target_uri = (
            f"https://us-central1-{PROJECT_ID}.cloudfunctions.net/"
            "runpipelinetask"
        )
        queue.enqueue(
            {"data": {"job_id": job_id}},
            admin_functions.TaskOptions(
                dispatch_deadline_seconds=1800,
                uri=target_uri,
            ),
        )
    except Exception as exc:
        job.status = "error"
        job.error = f"failed to queue pipeline: {exc}"
        persist_job(job)
        return _error_response(job.error, status=503, origin=origin)

    return _json_response({"jobId": job_id, "status": "queued"}, origin=origin)


@https_fn.on_request()
def list_jobs_fn(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    try:
        limit = max(1, min(int(req.args.get("limit", 20)), 100))
    except (TypeError, ValueError):
        return _error_response("limit must be an integer", origin=origin)
    jobs = []
    for job in list_jobs(limit):
        job = _reconcile_stale_job(job)
        item = job_to_dict(job)
        item["has_results"] = bool(job.results)
        item["results"] = None
        jobs.append(item)
    return _json_response({"jobs": jobs}, origin=origin)


@https_fn.on_request()
def get_job_fn(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    job_id = req.path.split("/")[-1]
    job = get_job(job_id)
    if not job:
        return _error_response("job not found", status=404, origin=origin)
    job = _reconcile_stale_job(job)
    return _json_response(job_to_dict(job, include_results=False), origin=origin)


@https_fn.on_request()
def get_results(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    job_id = req.path.split("/")[-1]
    job = get_job(job_id)
    if not job:
        return _error_response("job not found", status=404, origin=origin)
    if not job.results:
        return _error_response("results not ready", status=404, origin=origin)
    return _json_response(job.results, origin=origin)


@https_fn.on_request()
def get_review(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    job_id = req.path.split("/")[-1]
    job = get_job(job_id)
    if not job:
        return _error_response("job not found", status=404, origin=origin)
    if job.results:
        return _json_response(job.results.get("review", []), origin=origin)
    return _json_response([], origin=origin)


@https_fn.on_request()
def approve_stores(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    if req.method != "POST":
        return _error_response("method not allowed", status=405, origin=origin)

    job_id = req.path.split("/")[-1]
    payload = _get_json(req)
    stores = payload.get("stores", [])

    from firebase_service import push_stores
    result = push_stores(stores, job_id)
    return _json_response(result, origin=origin)


@https_fn.on_request()
def traders_preview(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    if req.method != "POST":
        return _error_response("method not allowed", status=405, origin=origin)

    job_id = req.path.split("/")[-1]
    payload = _get_json(req)
    stores = payload.get("stores", [])

    from traders_firebase_service import preview_push
    docs = preview_push(stores, job_id)
    return _json_response({
        "count": len(docs),
        "documents": docs,
        "collection": TRADERS_COLLECTION,
        "project": "traders-data-live",
    }, origin=origin)


@https_fn.on_request(secrets=[TRADERS_SECRET])
def traders_push(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    if req.method != "POST":
        return _error_response("method not allowed", status=405, origin=origin)
    if not TRADERS_WRITES_ENABLED:
        return _error_response(
            "الكتابة إلى traders-data-live معطلة حالياً",
            status=403,
            origin=origin,
        )

    job_id = req.path.split("/")[-1]
    payload = _get_json(req)
    stores = payload.get("stores", [])

    from traders_firebase_service import push_to_traders
    result = push_to_traders(stores, job_id)
    return _json_response(result, origin=origin)


@https_fn.on_request()
def export_csv(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)

    job_id = req.path.split("/")[-1]
    job = get_job(job_id)
    if not job or not job.results:
        return _error_response("results not ready", status=404, origin=origin)

    stores = job.results.get("stores", [])
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", delete=False, suffix=".csv") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "category", "phone", "status", "lat", "lng", "street", "city", "district"])
        for s in stores:
            writer.writerow([
                s.get("name", ""), s.get("category", ""), s.get("phone", ""),
                s.get("status", ""), s.get("lat", ""), s.get("lng", ""),
                s.get("street", ""), s.get("city", ""), s.get("district", ""),
            ])
        tmp_path = f.name

    storage_path = f"jobs/{job_id}/outputs/export.csv"
    upload_file(tmp_path, storage_path, content_type="text/csv; charset=utf-8")
    os.unlink(tmp_path)
    url = signed_url(storage_path, expiration=3600)
    return _json_response({
        "downloadUrl": url,
        "filename": f"stores_{job_id}.csv",
    }, origin=origin)


@https_fn.on_request()
def export_excel(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)

    job_id = req.path.split("/")[-1]
    for fname in ("stores_v6_final.xlsx", "stores_final.xlsx"):
        storage_path = f"jobs/{job_id}/outputs/{fname}"
        if exists(storage_path):
            url = signed_url(storage_path, expiration=3600)
            return _json_response({"downloadUrl": url, "filename": fname}, origin=origin)
    return _error_response("excel not ready", status=404, origin=origin)


@https_fn.on_request()
def get_sign(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)

    parts = req.path.split("/")
    if len(parts) < 3:
        return _error_response("invalid path", status=400, origin=origin)
    job_id = parts[-2]
    filename = parts[-1]
    if not filename.startswith("sign_") or ".." in filename:
        return _error_response("invalid filename", status=400, origin=origin)

    storage_path = f"jobs/{job_id}/outputs/signs/{filename}"
    if not exists(storage_path):
        return _error_response("image not found", status=404, origin=origin)

    url = signed_url(storage_path, expiration=3600, response_type="image/jpeg")
    return _json_response({"imageUrl": url}, origin=origin)


@https_fn.on_request()
def delete_video(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    if req.method != "DELETE":
        return _error_response("method not allowed", status=405, origin=origin)

    job_id = req.path.split("/")[-1]
    job = get_job(job_id)
    if not job:
        return _error_response("job not found", status=404, origin=origin)

    try:
        from storage import delete
        delete(job.video_storage_path)
        return _json_response({"deleted": True}, origin=origin)
    except Exception as e:
        return _error_response(str(e), status=500, origin=origin)


@https_fn.on_request(secrets=[TRADERS_SECRET])
def health(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)

    from firebase_service import status as fb_status
    from traders_firebase_service import status as traders_status
    from config import PIPELINE_DIR, PIPELINE_MAIN

    traders = traders_status()
    traders["writes_enabled"] = TRADERS_WRITES_ENABLED

    return _json_response({
        "firebase": fb_status(),
        "traders": traders,
        "pipeline": {
            "pipeline_dir": str(PIPELINE_DIR),
            "main_exists": PIPELINE_MAIN.exists(),
            "run_v6_exists": (PIPELINE_DIR / "run_v6.py").exists(),
        },
    }, origin=origin)


# ---------------------------------------------------------------------------
# Long-running pipeline workers
# ---------------------------------------------------------------------------


def _execute_pipeline_job(job_id: str) -> None:
    """Claim and execute one queued job, persisting progress and outputs."""
    job = claim_queued_job(job_id)
    if not job:
        return
    if not job.video_storage_path:
        job.status = "error"
        job.error = "video storage path is missing"
        persist_job(job)
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"job_{job_id}_"))
    video_local = tmp_dir / "video.mp4"
    output_dir = tmp_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs_uploaded = False

    try:
        download_file(job.video_storage_path, video_local)
        job.video_path = str(video_local)
        job.output_dir = str(output_dir)
        job.status = "running"
        persist_job(job)

        asyncio.run(run_pipeline_async(job))
        if job.status == "error":
            return

        upload_dir(output_dir, job_output_prefix(job_id))
        outputs_uploaded = True
        job.status = "partial" if job.results and job.results.get("warnings") else "done"
        job.error = None
        persist_job(job)

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        persist_job(job)
    finally:
        if not outputs_uploaded and output_dir.exists():
            try:
                upload_dir(output_dir, job_output_prefix(job_id))
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


@tasks_fn.on_task_dispatched(
    memory=options.MemoryOption.GB_4,
    timeout_sec=1800,
    concurrency=1,
    max_instances=3,
    retry_config=options.RetryConfig(max_attempts=1),
    rate_limits=options.RateLimits(max_concurrent_dispatches=3),
)
def runpipelinetask(request: tasks_fn.CallableRequest) -> dict:
    """Primary long-running pipeline executor, dispatched by Cloud Tasks."""
    data = request.data or {}
    if isinstance(data.get("data"), dict):
        data = data["data"]
    job_id = data.get("job_id")
    if not job_id:
        return {"status": "ignored", "reason": "job_id is required"}
    _execute_pipeline_job(job_id)
    return {"status": "completed", "job_id": job_id}


# Keep the previous Pub/Sub consumer during migration so a message that was
# already accepted before this deployment is not abandoned.
@pubsub_fn.on_message_published(
    topic=PIPELINE_TOPIC,
    memory=options.MemoryOption.GB_4,
    timeout_sec=540,
    concurrency=1,
    max_instances=1,
    retry=False,
)
def run_pipeline(event) -> None:
    """Compatibility consumer for already-published Pub/Sub messages."""
    try:
        msg = event.data["message"]
        payload = base64.b64decode(msg["data"]).decode("utf-8")
        data = json.loads(payload)
    except Exception:
        return

    job_id = data.get("job_id")
    if not job_id:
        return
    _execute_pipeline_job(job_id)


# ---------------------------------------------------------------------------
# Root / info
# ---------------------------------------------------------------------------

@https_fn.on_request()
def root(req: https_fn.Request) -> https_fn.Response:
    origin = _get_origin(req)
    if req.method == "OPTIONS":
        return _json_response({}, origin=origin)
    return _json_response({
        "name": "Store Extractor Firebase Functions",
        "version": "0.4.0",
        "status": "ok",
    }, origin=origin)
