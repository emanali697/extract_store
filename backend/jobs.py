"""In-memory job manager + SQLite persistence + WebSocket fan-out."""
from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict

from config import JOBS_DIR
import db


@dataclass
class Job:
    job_id: str
    video_path: str
    street_name: str
    city: str
    district: str = ""
    speed_mode: str = "auto"
    enable_places: bool = True
    enable_status: bool = True
    start_seconds: float = 0         # seek N seconds into the video before extracting
    status: str = "queued"           # queued | running | done | error
    error: str | None = None
    output_dir: str = ""
    stages: dict[int, dict] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)
    results: dict | None = None


def _job_from_row(d: dict) -> Job:
    return Job(
        job_id=d["job_id"],
        video_path=d["video_path"] or "",
        street_name=d["street_name"] or "",
        city=d["city"] or "",
        district=d["district"] or "",
        speed_mode=d["speed_mode"] or "auto",
        enable_places=bool(d.get("enable_places", True)),
        enable_status=bool(d.get("enable_status", True)),
        status=d["status"] or "queued",
        error=d.get("error"),
        output_dir=d["output_dir"] or "",
        stages=d.get("stages") or {},
        results=d.get("results"),
    )


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._loaded = False

    def hydrate_from_db(self) -> int:
        """Load all previously-persisted jobs into memory. Call once on startup."""
        if self._loaded:
            return 0
        db.init()
        rows = db.load_all_jobs()
        for row in rows:
            job = _job_from_row(row)
            # Crashed-mid-run jobs surface as "interrupted" so the UI can show that
            if job.status == "running":
                job.status = "interrupted"
            self._jobs[job.job_id] = job
        self._loaded = True
        return len(rows)

    def create(self, video_path: str, settings: dict) -> Job:
        job_id = uuid.uuid4().hex[:12]
        out_dir = JOBS_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        job = Job(
            job_id=job_id,
            video_path=video_path,
            street_name=settings.get("streetName", ""),
            city=settings.get("city", ""),
            district=settings.get("district", ""),
            speed_mode=settings.get("speedMode", "auto"),
            enable_places=settings.get("enablePlaces", True),
            enable_status=settings.get("enableStatus", True),
            start_seconds=settings.get("startSeconds", 0),
            output_dir=str(out_dir),
        )
        self._jobs[job_id] = job
        db.upsert_job(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())

    def persist(self, job: Job) -> None:
        """Save current job state to SQLite."""
        try:
            db.upsert_job(job)
        except Exception:
            # never let persistence break the running pipeline
            pass

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers[job_id].append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        if q in self._subscribers[job_id]:
            self._subscribers[job_id].remove(q)

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subscribers.get(job_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


manager = JobManager()
