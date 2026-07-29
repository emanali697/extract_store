"""Adapter for traders-data-live Firestore project (Cloud Functions)."""
from __future__ import annotations

import logging
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore as _fs

from config import TRADERS_COLLECTION, TRADERS_PROJECT_ID

_log = logging.getLogger("traders_firebase")

_app = None
_db = None
_init_error: str | None = None


def _ensure_init() -> bool:
    global _app, _db, _init_error
    if _db is not None:
        return True
    if _init_error:
        return False

    # In Cloud Functions, the second project is initialized via a service-account
    # key stored in a secret. Set TRADERS_SERVICE_ACCOUNT_JSON to the full JSON
    # contents of traders_data_live_key.json (or mount the file and set
    # TRADERS_KEY_PATH).
    import os
    import json

    traders_json = os.environ.get("TRADERS_SERVICE_ACCOUNT_JSON")
    traders_path = os.environ.get("TRADERS_KEY_PATH")

    try:
        if traders_json:
            cred_info = json.loads(traders_json)
            cred = credentials.Certificate(cred_info)
        elif traders_path and os.path.exists(traders_path):
            with open(traders_path, encoding="utf-8") as key_file:
                cred_info = json.load(key_file)
            cred = credentials.Certificate(cred_info)
        else:
            _init_error = "TRADERS_SERVICE_ACCOUNT_JSON or TRADERS_KEY_PATH not provided"
            return False

        credential_project = cred_info.get("project_id")
        if credential_project != TRADERS_PROJECT_ID:
            _init_error = (
                "traders credentials project mismatch: "
                f"expected {TRADERS_PROJECT_ID}, got {credential_project or 'missing'}"
            )
            return False

        existing = {a.name for a in firebase_admin._apps.values()}
        if "traders" not in existing:
            _app = firebase_admin.initialize_app(
                cred,
                {"projectId": TRADERS_PROJECT_ID},
                name="traders",
            )
        else:
            _app = firebase_admin.get_app("traders")
        if _app.project_id != TRADERS_PROJECT_ID:
            _init_error = (
                "traders Firebase app project mismatch: "
                f"expected {TRADERS_PROJECT_ID}, got {_app.project_id}"
            )
            _app = None
            return False
        _db = _fs.client(_app)
        return True
    except Exception as e:
        _init_error = f"traders init failed: {e}"
        _log.exception(_init_error)
        return False


def is_ready() -> bool:
    return _ensure_init()


def status() -> dict:
    ok = _ensure_init()
    return {
        "ready": ok,
        "error": _init_error,
        "collection": TRADERS_COLLECTION,
        "project_id": (_app.project_id if _app else None),
    }


STATUS_MAP = {
    "نشط": "نشط",
    "مقفول": "مغلق نهائيا",
    "غير محدد": "",
}


def _normalize(s: str) -> str:
    return (s or "").strip()


def _city_map(value: str) -> dict:
    v = _normalize(value)
    return {"id": "", "value": v, "valueLower": v.lower() if v else ""}


def _neighborhood_map(value: str) -> dict:
    v = _normalize(value)
    return {"id": "", "value": v, "valueLower": v.lower() if v else ""}


def _street_map(value: str) -> dict:
    v = _normalize(value)
    return {"id": "", "value": v, "valueLower": v.lower() if v else ""}


def _phones_to_array(phone_str: str) -> list[str]:
    if not phone_str:
        return []
    raw = [p.strip() for p in phone_str.replace("،", ",").split(",")]
    return [p for p in raw if p]


def _build_geo_link(lat, lng) -> str:
    if lat is None or lng is None:
        return ""
    return f"https://www.google.com/maps?q={lat},{lng}"


def map_store(s: dict, order_idx: int, source_job_id: str) -> dict:
    name = s.get("name_ar") or s.get("name") or ""
    status_word = ""
    sc = s.get("status_check") or {}
    if sc.get("status"):
        status_word = STATUS_MAP.get(sc["status"], sc["status"])

    lat = s.get("lat") or ""
    lng = s.get("lng") or ""

    return {
        "VideoMin": "",
        "adminPhones": [],
        "campaignInteractionList": [],
        "categories": [s.get("category")] if s.get("category") else [],
        "city": _city_map(s.get("city") or ""),
        "completionPercentage": 50,
        "copy": {"commercialName": "", "id": "", "internalName": "", "label": "", "releaseLink": ""},
        "customerPhones": _phones_to_array(s.get("phone") or ""),
        "dataCompleted": False,
        "geoLocationLink": _build_geo_link(lat, lng),
        "hasDelivery": "",
        "hasWhatsApp": "",
        "isForRent": False,
        "latitude": str(lat) if lat else "",
        "longitude": str(lng) if lng else "",
        "neighborhood": _neighborhood_map(s.get("district") or ""),
        "notes": s.get("notes") or "",
        "numberOfRentals": "",
        "offersData": [],
        "operatingHours": "",
        "order": order_idx,
        "socialMedia": [],
        "storeImageUrl": "",
        "storeLink": "",
        "storeName": name,
        "storeStatus": status_word,
        "street": _street_map(s.get("street") or ""),
        "subscriptionRenewalMonth": "",
        "technicalSupportData": {},
        "updateNotes": f"تم الاستخراج تلقائياً من فيديو داش كاميرا (job {source_job_id})",
        "videoSec": "",
        "videoUrl": "",
    }


def preview_push(stores: list[dict], source_job_id: str) -> list[dict]:
    return [map_store(s, idx, source_job_id) for idx, s in enumerate(stores, start=1)]


def push_to_traders(stores: list[dict], source_job_id: str) -> dict:
    if not _ensure_init():
        return {"written": 0, "error": _init_error}

    coll = _db.collection(TRADERS_COLLECTION)
    server_ts = _fs.SERVER_TIMESTAMP

    written = 0
    errors: list[str] = []

    for idx, s in enumerate(stores, start=1):
        try:
            doc = map_store(s, idx, source_job_id)
            doc["createdAt"] = server_ts
            doc["updatedAt"] = server_ts
            doc_ref = coll.document()
            doc["id"] = doc_ref.id
            doc_ref.set(doc)
            written += 1
        except Exception as e:
            errors.append(f"{s.get('name_ar', '?')}: {e}")

    return {
        "written": written,
        "skipped": len(stores) - written,
        "errors": errors[:5],
        "collection": TRADERS_COLLECTION,
        "project": "traders-data-live",
    }
