"""
Firebase Admin SDK wrapper. Lazy-initialised so the backend boots even if the
key is missing or invalid — callers can check `is_ready()` first.

Schema (collection = config.FIRESTORE_COLLECTION, default "stores"):
    name_ar, name_en, category, phone, status, tier,
    location: GeoPoint, location_source, location_accuracy_m,
    google_place_id, rating, review_count,
    street, city, district,
    extracted_from_job, extracted_at (server timestamp),
    approved_by_user.
"""
from __future__ import annotations
import logging
from typing import Any
from pathlib import Path

from config import FIREBASE_KEY_PATH, FIRESTORE_COLLECTION

_log = logging.getLogger("firebase_service")

_app = None
_db = None
_init_error: str | None = None


def _ensure_init() -> bool:
    global _app, _db, _init_error
    if _db is not None:
        return True
    if _init_error:
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as e:
        _init_error = f"firebase-admin not installed: {e}"
        _log.warning(_init_error)
        return False

    if not Path(FIREBASE_KEY_PATH).exists():
        _init_error = f"firebase key not found at {FIREBASE_KEY_PATH}"
        _log.warning(_init_error)
        return False

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(str(FIREBASE_KEY_PATH))
            _app = firebase_admin.initialize_app(cred)
        else:
            _app = firebase_admin.get_app()
        _db = firestore.client()
        _log.info("Firebase initialised (project=%s)", _app.project_id)
        return True
    except Exception as e:
        _init_error = f"firebase init failed: {e}"
        _log.exception(_init_error)
        return False


def is_ready() -> bool:
    return _ensure_init()


def status() -> dict:
    ok = _ensure_init()
    return {
        "ready": ok,
        "error": _init_error,
        "collection": FIRESTORE_COLLECTION,
        "project_id": (_app.project_id if _app else None),
    }


def push_stores(stores: list[dict], job_id: str) -> dict:
    """
    Write approved stores to Firestore. Returns counts.

    Each store dict is expected to follow the schema documented at module top.
    Documents are upserted by a deterministic id when `google_place_id` is set,
    otherwise auto-id is used.
    """
    if not _ensure_init():
        return {"written": 0, "error": _init_error}

    from firebase_admin import firestore as _fs
    coll = _db.collection(FIRESTORE_COLLECTION)
    server_ts = _fs.SERVER_TIMESTAMP

    written = 0
    skipped = 0
    errors: list[str] = []

    for s in stores:
        try:
            doc = _store_to_doc(s, job_id, server_ts)
            place_id = s.get("google_place_id")
            if place_id:
                coll.document(place_id).set(doc, merge=True)
            else:
                coll.add(doc)
            written += 1
        except Exception as e:
            skipped += 1
            errors.append(str(e))

    return {
        "written": written,
        "skipped": skipped,
        "errors": errors[:5],
        "collection": FIRESTORE_COLLECTION,
    }


def _store_to_doc(s: dict, job_id: str, server_ts: Any) -> dict:
    """Map app-layer store dict → Firestore document."""
    from firebase_admin import firestore as _fs

    lat = s.get("lat")
    lng = s.get("lng")
    location = None
    if lat is not None and lng is not None:
        try:
            location = _fs.GeoPoint(float(lat), float(lng))
        except (TypeError, ValueError):
            location = None

    doc: dict = {
        "name_ar": s.get("name_ar") or s.get("name") or "",
        "name_en": s.get("name_en") or "",
        "category": s.get("category") or "",
        "phone": s.get("phone") or "",
        "status": s.get("status") or "غير محدد",
        "tier": s.get("tier") or 3,
        "location_source": s.get("location_source") or "dashcam_frame",
        "location_accuracy_m": s.get("location_accuracy_m"),
        "google_place_id": s.get("google_place_id") or None,
        "rating": s.get("rating"),
        "review_count": s.get("review_count"),
        "street": s.get("street") or "",
        "city": s.get("city") or "",
        "district": s.get("district") or "",
        "extracted_from_job": job_id,
        "extracted_at": server_ts,
        "approved_by_user": True,
    }
    if location is not None:
        doc["location"] = location
    return doc
