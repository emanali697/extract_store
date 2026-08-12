"""Firestore persistence for jobs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone
import hashlib
import hmac

from firebase_admin import firestore
from google.cloud import firestore as firestore_client

from config import JOBS_COLLECTION

_db = None


def get_db() -> firestore_client.Client:
    global _db
    if _db is None:
        _db = firestore.client()
    return _db


@dataclass
class Job:
    job_id: str
    video_storage_path: str = ""
    video_name: str = ""
    street_name: str = ""
    city: str = ""
    district: str = ""
    speed_mode: str = "auto"
    enable_places: bool = True
    enable_status: bool = True
    start_seconds: float = 0
    status: str = "uploading"
    error: str | None = None
    stages: dict[int, dict] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)
    results: dict | None = None
    review_token_hash: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_to_doc(job: Job) -> dict[str, Any]:
    """Serialize a Job to a Firestore document."""
    return {
        "job_id": job.job_id,
        "video_storage_path": job.video_storage_path,
        "video_name": job.video_name,
        "street_name": job.street_name,
        "city": job.city,
        "district": job.district,
        "speed_mode": job.speed_mode,
        "enable_places": job.enable_places,
        "enable_status": job.enable_status,
        "start_seconds": job.start_seconds,
        "status": job.status,
        "error": job.error,
        "stages": {str(k): v for k, v in job.stages.items()},
        "log_lines": job.log_lines[-500:] if job.log_lines else [],  # keep last 500
        "results": job.results,
        "review_token_hash": job.review_token_hash,
        "created_at": job.created_at or _now(),
        "updated_at": _now(),
    }


def _doc_to_job(doc: dict[str, Any]) -> Job:
    """Deserialize a Firestore document to a Job."""
    stages = doc.get("stages", {})
    return Job(
        job_id=doc.get("job_id", ""),
        video_storage_path=doc.get("video_storage_path", ""),
        video_name=doc.get("video_name", ""),
        street_name=doc.get("street_name", ""),
        city=doc.get("city", ""),
        district=doc.get("district", ""),
        speed_mode=doc.get("speed_mode", "auto"),
        enable_places=bool(doc.get("enable_places", True)),
        enable_status=bool(doc.get("enable_status", True)),
        start_seconds=float(doc.get("start_seconds", 0) or 0),
        status=doc.get("status", "queued"),
        error=doc.get("error"),
        stages={int(k): v for k, v in stages.items()} if stages else {},
        log_lines=list(doc.get("log_lines", [])),
        results=doc.get("results"),
        review_token_hash=doc.get("review_token_hash", ""),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


def create_job(job: Job) -> None:
    """Create a new job document in Firestore."""
    db = get_db()
    now = _now()
    job.created_at = now
    job.updated_at = now
    db.collection(JOBS_COLLECTION).document(job.job_id).set(_job_to_doc(job))


def persist_job(job: Job) -> None:
    """Update an existing job document."""
    db = get_db()
    job.updated_at = _now()
    db.collection(JOBS_COLLECTION).document(job.job_id).set(
        _job_to_doc(job), merge=True
    )


def get_job(job_id: str) -> Job | None:
    """Fetch a job by ID."""
    db = get_db()
    doc = db.collection(JOBS_COLLECTION).document(job_id).get()
    if not doc.exists:
        return None
    return _doc_to_job(doc.to_dict())


def save_review_decision(
    job_id: str,
    review_id: str,
    action: str,
    review_token: str,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist a human review decision in the canonical job results.

    The review queue and results table live in the same Firestore document, so
    changing both in one transaction prevents the old extracted value from
    reappearing after a refresh.
    """
    db = get_db()
    ref = db.collection(JOBS_COLLECTION).document(job_id)
    transaction = db.transaction()

    @firestore_client.transactional
    def _save(txn):
        snapshot = ref.get(transaction=txn)
        if not snapshot.exists:
            return None

        document = snapshot.to_dict() or {}
        expected_token_hash = str(document.get("review_token_hash") or "")
        supplied_token_hash = hashlib.sha256(review_token.encode("utf-8")).hexdigest()
        if not expected_token_hash or not hmac.compare_digest(
            expected_token_hash,
            supplied_token_hash,
        ):
            raise PermissionError("invalid review authorization")

        results = dict(document.get("results") or {})
        stores = [dict(store) for store in (results.get("stores") or [])]
        review = [dict(item) for item in (results.get("review") or [])]

        review_item = next(
            (item for item in review if str(item.get("id")) == review_id),
            None,
        )
        store_id = (review_item or {}).get("storeId")
        if store_id is None and review_id.startswith("r") and review_id[1:].isdigit():
            store_id = int(review_id[1:])
        if store_id is None:
            raise ValueError("review item is not linked to a result store")

        matching_index = next(
            (
                index for index, store in enumerate(stores)
                if str(store.get("id")) == str(store_id)
            ),
            None,
        )
        if matching_index is None and action == "approve":
            raise ValueError("result store not found")

        if action == "approve" and matching_index is not None:
            values = updates or {}
            name = str(values.get("name") or "").strip()
            if not name:
                raise ValueError("store name is required")
            store = stores[matching_index]
            store.update({
                "name": name,
                "name_ar": name,
                "category": str(values.get("category") or "").strip(),
                "phone": str(values.get("phone") or "").strip(),
                "approved": True,
                "edited": True,
                "review_status": "approved",
            })
        elif action == "reject" and matching_index is not None:
            stores.pop(matching_index)

        review = [item for item in review if str(item.get("id")) != review_id]
        summary = dict(results.get("summary") or {})
        summary.update({
            "total": len(stores),
            "active": sum(
                1 for store in stores
                if int(store.get("tier") or 0) == 1
                or "نشط" in str(store.get("status") or "")
            ),
            "phones": sum(1 for store in stores if str(store.get("phone") or "").strip()),
            "precise": sum(
                1 for store in stores
                if store.get("lat") is not None or store.get("lng") is not None
            ),
            "needs_human": len(review),
        })
        results.update({"stores": stores, "review": review, "summary": summary})
        txn.update(ref, {"results": results, "updated_at": _now()})
        return results

    return _save(transaction)


def claim_queued_job(job_id: str) -> Job | None:
    """Atomically move one queued job to running and return it.

    Pub/Sub is at-least-once, so two deliveries must never start the same
    video pipeline concurrently.
    """
    db = get_db()
    ref = db.collection(JOBS_COLLECTION).document(job_id)
    transaction = db.transaction()

    @firestore_client.transactional
    def _claim(txn):
        snapshot = ref.get(transaction=txn)
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        if data.get("status") != "queued":
            return None
        txn.update(ref, {
            "status": "running",
            "error": None,
            "updated_at": _now(),
        })
        return data

    data = _claim(transaction)
    if not data:
        return None
    job = _doc_to_job(data)
    job.status = "running"
    job.error = None
    return job


def list_jobs(limit: int = 20) -> list[Job]:
    """Return recent jobs, newest first."""
    db = get_db()
    query = (
        db.collection(JOBS_COLLECTION)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [_doc_to_job(d.to_dict()) for d in query.stream()]


def job_to_dict(job: Job, include_results: bool = True) -> dict[str, Any]:
    """Return a JSON-serializable dict for API responses."""
    data = {
        "job_id": job.job_id,
        "video_storage_path": job.video_storage_path,
        "video_name": job.video_name,
        "street_name": job.street_name,
        "city": job.city,
        "district": job.district,
        "speed_mode": job.speed_mode,
        "enable_places": job.enable_places,
        "enable_status": job.enable_status,
        "status": job.status,
        "error": job.error,
        "stages": job.stages,
        "has_results": bool(job.results),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
    if include_results:
        data["results"] = job.results
    return data


def update_job_status(job_id: str, status: str, error: str | None = None) -> None:
    """Fast status update helper."""
    db = get_db()
    db.collection(JOBS_COLLECTION).document(job_id).update(
        {"status": status, "error": error, "updated_at": _now()}
    )


def append_log(job_id: str, line: str) -> None:
    """Append a single log line to the job document."""
    db = get_db()
    db.collection(JOBS_COLLECTION).document(job_id).update(
        {"log_lines": firestore.ArrayUnion([line]), "updated_at": _now()}
    )


def set_log_lines(job_id: str, lines: list[str], limit: int = 200) -> None:
    """Replace the bounded UI log snapshot instead of growing it forever."""
    get_db().collection(JOBS_COLLECTION).document(job_id).update({
        "log_lines": list(lines[-limit:]),
        "updated_at": _now(),
    })


def update_stage(job_id: str, stage_idx: int, status: str,
                 current: int | None = None, total: int | None = None,
                 phase: str | None = None) -> None:
    """Update a single stage entry."""
    db = get_db()
    entry = {"status": status}
    if current is not None:
        entry["current"] = current
    if total is not None:
        entry["total"] = total
    if phase:
        entry["phase"] = phase
    db.collection(JOBS_COLLECTION).document(job_id).update(
        {f"stages.{stage_idx}": entry, "updated_at": _now()}
    )
