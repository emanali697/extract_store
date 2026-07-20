"""FastAPI backend for the store-extraction project."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import UPLOAD_DIR, ALLOWED_ORIGINS, JOBS_DIR, PIPELINE_DIR, PIPELINE_MAIN


def _pipeline_status() -> dict:
    return {
        "pipeline_dir": str(PIPELINE_DIR),
        "main_exists": PIPELINE_MAIN.exists(),
        "run_v6_exists": (PIPELINE_DIR / "run_v6.py").exists(),
    }

from jobs import manager, Job
from runner import run_pipeline, _read_results
import firebase_service
import traders_firebase_service

app = FastAPI(title="Store Extractor API", version="0.3.0")

# CORS: allow any localhost/127.0.0.1 origin on any port so Vite dev server
# can use fallback ports (5173, 5174, 5175, ...) without manual updates.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobSettings(BaseModel):
    videoPath: str
    streetName: str = ""
    city: str = ""
    district: str = ""
    speedMode: str = "auto"
    enablePlaces: bool = True
    enableStatus: bool = True


class ApproveRequest(BaseModel):
    stores: list[dict]


def _job_to_dict(job: Job) -> dict:
    """Serialize a Job dataclass for the API."""
    return {
        "job_id": job.job_id,
        "video_path": job.video_path,
        "street_name": job.street_name,
        "city": job.city,
        "district": job.district,
        "speed_mode": job.speed_mode,
        "enable_places": job.enable_places,
        "enable_status": job.enable_status,
        "status": job.status,
        "error": job.error,
        "output_dir": job.output_dir,
        "stages": job.stages,
        "results": job.results,
    }


@app.on_event("startup")
def startup():
    manager.hydrate_from_db()
    if not PIPELINE_DIR.is_dir():
        raise RuntimeError(
            f"Invalid PIPELINE_DIR: {PIPELINE_DIR}. "
            "Set it to the directory containing pipeline/main.py, or unset it."
        )


@app.get("/")
def root():
    return {
        "name": "Store Extractor API",
        "version": "0.3.0",
        "status": "ok",
        "firebase": firebase_service.status(),
        "pipeline": _pipeline_status(),
    }


@app.get("/health")
def health():
    return {
        "firebase": firebase_service.status(),
        "traders": traders_firebase_service.status(),
        "pipeline": _pipeline_status(),
    }


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    from pathlib import Path
    safe_name = Path(file.filename).name
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    return {"filename": safe_name, "path": str(file_path)}


@app.post("/jobs")
async def create_job(settings: JobSettings):
    payload = settings.model_dump()
    video_path = payload.pop("videoPath")
    job = manager.create(video_path, payload)
    asyncio.create_task(run_pipeline(job))
    return {"jobId": job.job_id, "status": job.status}


@app.get("/jobs")
def list_jobs(limit: int = 20):
    jobs = manager.all()
    # newest first
    jobs.sort(key=lambda j: j.job_id, reverse=True)
    return {"jobs": [_job_to_dict(j) for j in jobs[:limit]]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _job_to_dict(job)


@app.get("/jobs/{job_id}/results")
def job_results(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not job.results:
        raise HTTPException(404, "results not ready")
    return job.results


@app.get("/jobs/{job_id}/review")
def job_review(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.results:
        return job.results.get("review", [])
    data = asyncio.run(_read_results(job))
    return data.get("review", [])


@app.post("/jobs/{job_id}/approve")
def job_approve(job_id: str, body: ApproveRequest):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not firebase_service.is_ready():
        raise HTTPException(503, f"Firebase not ready: {firebase_service.status().get('error')}")
    result = firebase_service.push_stores(body.stores, job_id)
    return result


@app.post("/jobs/{job_id}/traders/preview")
def job_traders_preview(job_id: str, body: ApproveRequest):
    """Dry run: returns the JSON we would write to traders-data-live, no actual writes."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    docs = traders_firebase_service.preview_push(body.stores, job_id)
    return {"count": len(docs), "documents": docs, "collection": "stores",
            "project": "traders-data-live"}


@app.post("/jobs/{job_id}/traders/push")
def job_traders_push(job_id: str, body: ApproveRequest):
    """Actually write the stores to traders-data-live."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not traders_firebase_service.is_ready():
        raise HTTPException(503, f"traders not ready: {traders_firebase_service.status().get('error')}")
    return traders_firebase_service.push_to_traders(body.stores, job_id)


@app.get("/jobs/{job_id}/export.csv")
def export_csv(job_id: str):
    from pathlib import Path
    import csv
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not job.results:
        raise HTTPException(404, "csv not ready")
    out_path = Path(job.output_dir) / "export.csv"
    stores = job.results.get("stores", [])
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "category", "phone", "status", "lat", "lng", "street", "city", "district"])
        for s in stores:
            writer.writerow([
                s.get("name", ""), s.get("category", ""), s.get("phone", ""),
                s.get("status", ""), s.get("lat", ""), s.get("lng", ""),
                s.get("street", ""), s.get("city", ""), s.get("district", ""),
            ])
    return FileResponse(out_path, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={out_path.name}"})


@app.get("/jobs/{job_id}/excel")
def download_excel(job_id: str):
    from pathlib import Path
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    out = Path(job.output_dir)
    for fname in ("stores_v6_final.xlsx", "stores_final.xlsx"):
        p = out / fname
        if p.exists():
            return FileResponse(p, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                filename=p.name)
    raise HTTPException(404, "excel not ready")


@app.get("/jobs/{job_id}/sign/{filename}")
def serve_sign(job_id: str, filename: str):
    from pathlib import Path
    if not filename.startswith("sign_") or ".." in filename:
        raise HTTPException(400, "invalid filename")
    path = JOBS_DIR / job_id / "signs" / filename
    if not path.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(path)


@app.delete("/jobs/{job_id}/video")
def delete_job_video(job_id: str):
    job = manager.get(job_id)
    if not job or not job.video_path:
        raise HTTPException(404, "video not found")
    import os
    try:
        os.remove(job.video_path)
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.websocket("/ws/progress/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    q = manager.subscribe(job_id)
    try:
        # send current snapshot first
        job = manager.get(job_id)
        if job:
            await websocket.send_text(json.dumps({
                "type": "status",
                "status": job.status,
                "stages": job.stages,
            }))
        while True:
            event = await q.get()
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.unsubscribe(job_id, q)
