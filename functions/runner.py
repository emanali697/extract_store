"""Pipeline runner adapted for Firebase Functions.

The pipeline runs in a Cloud Function environment:
- Video is downloaded from Cloud Storage to /tmp.
- Pipeline outputs are written to /tmp.
- Progress is written to Firestore.
- Final outputs are uploaded back to Cloud Storage.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue as _queue
import subprocess
import threading
from pathlib import Path

from db import Job, persist_job, set_log_lines, update_stage
from config import PIPELINE_DIR, PIPELINE_PYTHON

PIPELINE_MAIN = PIPELINE_DIR / "main.py"
PIPELINE_MAIN_V5 = PIPELINE_DIR / "main_v5.py"
PIPELINE_RUN_V6 = PIPELINE_DIR / "run_v6.py"
NUM_UI_STAGES = 9

from stages import parse_progress_hint, parse_stage_marker


async def _emit(job: Job, event: dict) -> None:
    """Write a progress event to Firestore."""
    if event.get("type") == "log":
        line = event.get("line", "")
        if not job.log_lines or job.log_lines[-1] != line:
            job.log_lines.append(line)
        should_flush = (
            len(job.log_lines) % 10 == 0
            or "--- STAGE" in line
            or "ERROR" in line
        )
        if should_flush:
            set_log_lines(job.job_id, job.log_lines)
    elif event.get("type") == "stage":
        update_stage(
            job.job_id,
            event["stage"],
            event["status"],
            event.get("current"),
            event.get("total"),
            event.get("phase"),
        )
    elif event.get("type") in ("status", "results"):
        # status/results are persisted when the job is persisted explicitly
        pass


async def _mark_stage(job: Job, ui_idx: int, status: str,
                      current: int | None = None, total: int | None = None,
                      phase: str | None = None) -> None:
    entry = job.stages.get(ui_idx, {})
    entry["status"] = status
    if current is not None:
        entry["current"] = current
    if total is not None:
        entry["total"] = total
    if phase:
        entry["phase"] = phase
    job.stages[ui_idx] = entry
    await _emit(job, {
        "type": "stage",
        "stage": ui_idx,
        "status": status,
        "current": entry.get("current"),
        "total": entry.get("total"),
        "phase": entry.get("phase"),
    })


def _pick_input_json(output_dir: Path) -> tuple[Path, str]:
    """Pick the most-complete JSON output present in the job dir."""
    for fname, src in (
        ("stores_v6_final.json", "v6"),
        ("stores_v5_raw.json", "v5"),
        ("stores_raw.json", "v3"),
    ):
        p = output_dir / fname
        if p.exists():
            return p, src
    return output_dir / "stores_raw.json", "missing"


def _store_status_label(tier: int, status_word: str | None = None) -> str:
    if status_word:
        if "نشط" in status_word:
            return "✅ نشط"
        if "مغلق" in status_word or "مقفول" in status_word:
            return "🚫 مقفول"
        if "غير محدد" in status_word:
            return "⚪ غير محدد"
    return "✅ نشط" if tier == 1 else ("⚠️ غير مؤكد" if tier == 2 else "⚪ يحتاج تحقق")


async def _read_results(job: Job) -> dict:
    """Build UI-shaped summary. Prefers v6 > v5 > v3."""
    output_dir = Path(job.output_dir)
    json_path, source = _pick_input_json(output_dir)

    if not json_path.exists():
        return {
            "summary": {"total": 0, "active": 0, "phones": 0, "precise": 0, "source": source},
            "stores": [],
            "review": [],
        }

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "summary": {"total": 0, "active": 0, "phones": 0, "precise": 0, "source": source},
            "stores": [],
            "review": [],
            "error": str(exc),
        }

    stores = []
    review_items = []
    active_count = 0
    phones_count = 0
    precise_count = 0
    auto_passed = 0
    auto_rejected = 0
    needs_human = 0

    for i, s in enumerate(raw, start=1):
        places = s.get("places") or {}
        v5 = s.get("v5") or {}
        candidate = v5.get("candidate") or {}
        status_check = s.get("status_check") or {}
        auto_rev = s.get("auto_review") or {}
        ar_decision = auto_rev.get("decision")
        if ar_decision == "auto_passed":
            auto_passed += 1
        elif ar_decision == "auto_rejected":
            auto_rejected += 1
        elif ar_decision == "needs_human":
            needs_human += 1

        phone = s.get("phone") or places.get("phone") or candidate.get("phone") or ""

        if status_check.get("tier") in (1, 2, 3):
            tier = int(status_check["tier"])
        elif v5:
            vs = v5.get("status", "frame_only")
            tier = 1 if vs == "confirmed_high" else (2 if vs == "confirmed_medium" else 3)
        else:
            match_status = places.get("match_status") or ""
            tier = 1 if match_status == "مطابق" else (2 if places.get("name") else 3)

        status_word = status_check.get("status")
        status_label = _store_status_label(tier, status_word)

        if status_word == "نشط" or tier == 1:
            active_count += 1
        if phone:
            phones_count += 1
        if s.get("lat") or candidate.get("lat") or places.get("lat"):
            precise_count += 1

        name = (
            s.get("name_ar") or s.get("name")
            or candidate.get("name") or places.get("name") or "—"
        )
        category = s.get("category") or candidate.get("category") or places.get("category") or "—"

        loc_source = s.get("location_source") or (
            "google_places" if candidate.get("lat") else
            ("dashcam_frame" if s.get("lat") else "unknown")
        )
        loc_accuracy = s.get("location_accuracy_m")
        if loc_accuracy is None:
            loc_accuracy = 5 if loc_source == "google_places" else (30 if loc_source == "dashcam_frame" else None)

        store_obj = {
            "id": i,
            "name": name,
            "category": category,
            "phone": phone,
            "status": status_label,
            "tier": tier,
            "lat": s.get("lat") or candidate.get("lat"),
            "lng": s.get("lng") or candidate.get("lng"),
            "location_source": loc_source,
            "location_accuracy_m": loc_accuracy,
            "google_place_id": s.get("google_place_id") or candidate.get("place_id"),
            "rating": status_check.get("rating"),
            "review_count": status_check.get("review_count"),
            "evidence": status_check.get("evidence"),
            "source": status_check.get("source"),
            "distance": f"{int(loc_accuracy)}م" if loc_accuracy else "—",
            "name_ar": s.get("name_ar") or name,
            "name_en": s.get("name_en") or "",
            "street": job.street_name,
            "city": job.city,
            "district": job.district,
            "auto_review_decision": ar_decision,
            "auto_review_confidence": auto_rev.get("gemini_confidence"),
        }
        stores.append(store_obj)

        if ar_decision == "needs_human" or (
            ar_decision is None and (bool(s.get("needs_review")) or tier == 3)
        ):
            mm_raw = auto_rev.get("multimodal_raw") or ""
            mm_name = auto_rev.get("multimodal_name") or ""
            sign_image = auto_rev.get("sign_image") or ""
            review_items.append({
                "id": f"r{i}",
                "suggestedName": name,
                "rawOcr": mm_raw or s.get("ocr_text") or s.get("raw_text") or "",
                "multimodalName": mm_name,
                "category": category,
                "phone": phone,
                "confidence": auto_rev.get("gemini_confidence")
                              or s.get("confidence")
                              or (v5.get("score") if v5 else None)
                              or 0.5,
                "tier": tier,
                "signImageUrl": f"/jobs/{job.job_id}/sign/{sign_image}" if sign_image else "",
                "signImageFilename": sign_image,
                "note": auto_rev.get("gemini_reason") or s.get("review_note") or "",
            })

    return {
        "summary": {
            "total": len(stores),
            "active": active_count,
            "phones": phones_count,
            "precise": precise_count,
            "source": source,
            "auto_passed": auto_passed,
            "auto_rejected": auto_rejected,
            "needs_human": needs_human,
        },
        "stores": stores,
        "review": review_items,
    }


async def _run_subprocess(job: Job, cmd: list[str]) -> tuple[int, int | None]:
    """Run a pipeline subprocess and stream progress to Firestore."""
    job.log_lines.append(f"$ {' '.join(cmd)}")
    await _emit(job, {"type": "log", "line": f"$ {' '.join(cmd)}"})

    if not PIPELINE_DIR.is_dir():
        raise RuntimeError(f"Cannot run pipeline: cwd is not a directory: {PIPELINE_DIR}")

    stdout_q: _queue.Queue[str | None] = _queue.Queue(maxsize=1000)
    result_q: _queue.Queue[tuple[int | None, str | None]] = _queue.Queue(maxsize=1)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

    def _reader() -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PIPELINE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if proc.stdout is None:
                raise RuntimeError("pipeline stdout pipe was not created")
            try:
                for line in proc.stdout:
                    stdout_q.put(line.rstrip())
            finally:
                proc.stdout.close()
            result_q.put((proc.wait(), None))
        except Exception as exc:
            result_q.put((None, f"{type(exc).__name__}: {exc}"))
        finally:
            stdout_q.put(None)

    def _get_line(q: _queue.Queue[str | None], timeout: float = 0.2) -> str | None:
        try:
            return q.get(timeout=timeout)
        except _queue.Empty:
            return "__EMPTY__"

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    current_ui_stage: int | None = None
    current_phase: str | None = None

    while True:
        line = await asyncio.to_thread(_get_line, stdout_q)
        if line == "__EMPTY__":
            if not result_q.empty():
                break
            continue
        if line is None:
            break

        job.log_lines.append(line)
        await _emit(job, {"type": "log", "line": line})

        marker = parse_stage_marker(line)
        if marker is not None:
            new_stage, new_phase = marker
            if current_ui_stage is not None and current_ui_stage != new_stage:
                await _mark_stage(
                    job, current_ui_stage, "done", phase=current_phase
                )
            current_ui_stage = new_stage
            current_phase = new_phase
            await _mark_stage(
                job, new_stage, "active", current=0, total=0,
                phase=current_phase,
            )
            continue

        if current_ui_stage is not None:
            hint = parse_progress_hint(line)
            if hint:
                cur, tot = hint
                await _mark_stage(
                    job, current_ui_stage, "active", current=cur, total=tot,
                    phase=current_phase,
                )

    rc, launch_error = result_q.get()
    thread.join(timeout=5.0)
    set_log_lines(job.job_id, job.log_lines)
    if launch_error:
        raise RuntimeError(f"failed to start pipeline subprocess: {launch_error}")
    if rc is None:
        raise RuntimeError("pipeline subprocess ended without an exit code")
    return rc, current_ui_stage


async def run_pipeline(job: Job) -> None:
    """Run v3 -> v5 -> v6 and update Firestore."""
    job.status = "running"
    persist_job(job)
    partial_warnings: list[str] = []

    for i in range(NUM_UI_STAGES):
        job.stages[i] = {"status": "pending"}

    # v3
    cmd_v3 = [str(PIPELINE_PYTHON), str(PIPELINE_MAIN), job.video_path, job.output_dir]
    cmd_v3 += ["--speed-mode", job.speed_mode]
    if not job.enable_places:
        cmd_v3.append("--skip-places")
    if getattr(job, "start_seconds", 0):
        cmd_v3 += ["--start-seconds", str(job.start_seconds)]

    rc, last_stage = await _run_subprocess(job, cmd_v3)
    if rc != 0:
        if last_stage is not None:
            await _mark_stage(job, last_stage, "error")
        job.status = "error"
        job.error = f"v3 (main.py) exited with code {rc}"
        persist_job(job)
        return
    if last_stage is not None:
        await _mark_stage(job, last_stage, "done")

    # v5 (optional)
    v5_ok = False
    if (
        job.enable_places
        and PIPELINE_MAIN_V5.exists()
        and (Path(job.output_dir) / "stores_raw.json").exists()
    ):
        # v3 creates an intermediate Excel file, but the user-facing final
        # export must wait until v5/v6 finish.
        await _mark_stage(job, 8, "pending", current=0, total=0)
        await _emit(job, {"type": "log", "line": "--- STAGE 11: v5 matching ---"})
        await _mark_stage(job, 7, "active", current=0, total=0)

        cmd_v5 = [str(PIPELINE_PYTHON), str(PIPELINE_MAIN_V5), job.output_dir, job.output_dir]
        rc5, _ = await _run_subprocess(job, cmd_v5)
        if rc5 == 0:
            v5_ok = True
        else:
            partial_warnings.append(f"Google Places matching failed with code {rc5}")
            await _mark_stage(job, 7, "error")
            await _mark_stage(job, 8, "done")
            await _emit(job, {
                "type": "log",
                "line": f"⚠️ v5 returned {rc5}, continuing with v3 results",
            })

    # v6 (optional)
    v6_ok = False
    v5_json = Path(job.output_dir) / "stores_v5_raw.json"
    if PIPELINE_RUN_V6.exists() and v5_json.exists():
        await _emit(job, {"type": "log", "line": "--- STAGE 12: v6 orchestrator ---"})
        cmd_v6 = [str(PIPELINE_PYTHON), str(PIPELINE_RUN_V6), job.output_dir]
        if not job.enable_status:
            cmd_v6.append("--skip-status")
        rc6, _ = await _run_subprocess(job, cmd_v6)
        if rc6 == 0:
            v6_ok = True
            await _mark_stage(job, 7, "done")
            await _mark_stage(job, 8, "done")
        else:
            partial_warnings.append(f"Status/final review failed with code {rc6}")
            await _mark_stage(job, 7, "error")
            await _mark_stage(job, 8, "done")
            await _emit(job, {
                "type": "log",
                "line": f"⚠️ v6 returned {rc6}, falling back to v5 results",
            })
    elif v5_ok:
        await _mark_stage(job, 7, "done")
        await _mark_stage(job, 8, "done")

    if not job.enable_places:
        await _mark_stage(job, 6, "skipped")
        await _mark_stage(job, 7, "skipped")
    elif not v5_ok and not partial_warnings:
        partial_warnings.append("Google Places matching did not produce v5 results")
        await _mark_stage(job, 7, "error")

    for i in range(NUM_UI_STAGES):
        if job.stages.get(i, {}).get("status") not in ("done", "error", "skipped"):
            await _mark_stage(job, i, "skipped")

    job.status = "finalizing"
    job.results = await _read_results(job)
    if partial_warnings:
        job.results["warnings"] = partial_warnings
    persist_job(job)
