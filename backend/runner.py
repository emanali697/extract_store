"""
Runs the Python pipeline as a subprocess and translates its stdout
into structured progress events that are pushed through JobManager.publish.

Pipeline chain (Windows-safe via Proactor loop set in app.py):
    1) pipeline/main.py     → raw extraction (v3) → stores_raw.json
    2) pipeline/main_v5.py  → Google candidate matching → stores_v5_raw.json

v6 (finalize_v6 + exporter_v6) is NOT chained yet — those scripts have
hard-coded paths and an incomplete handoff from v5; will wire once the
intermediate `stores_with_status.json` script is identified.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

from config import PIPELINE_MAIN, PIPELINE_DIR, PIPELINE_PYTHON
from jobs import Job, manager
from stages import parse_progress_hint, parse_stage_marker

PIPELINE_MAIN_V5 = PIPELINE_DIR / "main_v5.py"
PIPELINE_RUN_V6 = PIPELINE_DIR / "run_v6.py"
NUM_UI_STAGES = 9


async def _emit(job: Job, event: dict) -> None:
    await manager.publish(job.job_id, event)


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
    manager.persist(job)
    await _emit(job, {
        "type": "stage",
        "stage": ui_idx,
        "status": status,
        "current": entry.get("current"),
        "total": entry.get("total"),
        "phase": entry.get("phase"),
    })


def _pick_input_json(job: Job) -> tuple[Path, str]:
    """Pick the most-complete JSON output present in the job dir."""
    out = Path(job.output_dir)
    for fname, src in (
        ("stores_v6_final.json", "v6"),
        ("stores_v5_raw.json", "v5"),
        ("stores_raw.json", "v3"),
    ):
        p = out / fname
        if p.exists():
            return p, src
    return out / "stores_raw.json", "missing"


def _store_status_label(tier: int, status_word: str | None = None) -> str:
    if status_word:
        if "نشط" in status_word:
            return "✅ نشط"
        if "مغلق" in status_word or "مقفل" in status_word:
            return "🚫 مقفول"
        if "غير محدد" in status_word:
            return "⚪ غير محدد"
    return "✅ نشط" if tier == 1 else ("⚠️ غير مؤكد" if tier == 2 else "⚪ يحتاج تحقق")


async def _read_results(job: Job) -> dict:
    """Build UI-shaped summary. Prefers v6 > v5 > v3."""
    json_path, source = _pick_input_json(job)

    if not json_path.exists():
        return {"summary": {"total": 0, "active": 0, "phones": 0, "precise": 0,
                            "source": source},
                "stores": [], "review": []}

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"summary": {"total": 0, "active": 0, "phones": 0, "precise": 0,
                            "source": source},
                "stores": [], "review": [], "error": str(exc)}

    stores = []
    review_items = []
    active_count = 0
    phones_count = 0
    precise_count = 0
    auto_passed = 0
    auto_rejected = 0
    needs_human = 0

    for i, s in enumerate(raw, start=1):
        has_visual_contract = (
            "visual_evidence" in s or "source_visible_in_video" in s
        )
        if s.get("excluded_from_results") or (
            has_visual_contract and (
                s.get("source_visible_in_video") is not True
                or not (s.get("visual_evidence") or {}).get("verified")
            )
        ):
            continue
        places = s.get("places") or {}
        v5 = s.get("v5") or {}
        candidate = v5.get("candidate") or {}
        status_check = s.get("status_check") or {}
        auto_rev = s.get("auto_review") or {}
        ar_decision = auto_rev.get("decision")
        if ar_decision == "auto_rejected":
            auto_rejected += 1
            continue
        if ar_decision == "auto_passed":
            auto_passed += 1
        elif ar_decision == "needs_human":
            needs_human += 1

        phone = s.get("phone") or ""

        # Prefer Tier from status_check (v6), else v5, else heuristic
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

        # Location source / accuracy — from v6 enrichment if present
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
            "phone_source": s.get("phone_source") or ("gemini_visual" if phone else "not_visible"),
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

        # Only route to human review queue if the auto-reviewer flagged it,
        # OR if there's no auto_review result and the store is Tier 3.
        if ar_decision == "needs_human" or (
            ar_decision is None and (bool(s.get("needs_review")) or tier == 3)
        ):
            mm_raw = auto_rev.get("multimodal_raw") or ""
            mm_name = auto_rev.get("multimodal_name") or ""
            evidence_images = (s.get("visual_evidence") or {}).get("sign_images") or []
            sign_image = auto_rev.get("sign_image") or (evidence_images[0] if evidence_images else "")
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
    """
    Spawn a pipeline subprocess, stream its stdout, route STAGE markers and
    structured progress to the UI. Returns (return_code, last_ui_stage).

    The subprocess runs via a blocking subprocess.Popen inside a dedicated OS
    thread. This avoids asyncio event loop limitations on Windows where uvicorn's
    --reload mode can leave the server with a loop that does not support
    subprocesses (NotImplementedError from create_subprocess_exec).
    """
    import queue as _queue
    import subprocess
    import threading

    job.log_lines.append(f"$ {' '.join(cmd)}")
    await _emit(job, {"type": "log", "line": f"$ {' '.join(cmd)}"})

    if not PIPELINE_DIR.is_dir():
        raise RuntimeError(f"Cannot run pipeline: cwd is not a directory: {PIPELINE_DIR}")

    stdout_q: _queue.Queue[str | None] = _queue.Queue(maxsize=1000)
    result_q: _queue.Queue[int] = _queue.Queue(maxsize=1)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

    def _reader() -> None:
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
        try:
            for line in proc.stdout:
                stdout_q.put(line.rstrip())
        finally:
            proc.stdout.close()
            rc = proc.wait()
            stdout_q.put(None)  # sentinel so the async loop stops cleanly
            result_q.put(rc)

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
            # Process finished without more output?
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

    rc = result_q.get() if not result_q.empty() else 0
    thread.join(timeout=5.0)
    return rc, current_ui_stage


async def run_pipeline(job: Job) -> None:
    """v3 (main.py) → v5 (main_v5.py) → UI events + final results."""
    job.status = "running"
    manager.persist(job)
    await _emit(job, {"type": "status", "status": "running"})

    # mark all stages pending
    for i in range(NUM_UI_STAGES):
        job.stages[i] = {"status": "pending"}

    # ---------- v3 ----------
    cmd_v3 = [str(PIPELINE_PYTHON), str(PIPELINE_MAIN), job.video_path, job.output_dir]
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
        manager.persist(job)
        await _emit(job, {"type": "status", "status": "error", "error": job.error})
        return
    if last_stage is not None:
        await _mark_stage(job, last_stage, "done")

    # ---------- v5 (optional) ----------
    v5_ok = False
    if PIPELINE_MAIN_V5.exists() and (Path(job.output_dir) / "stores_raw.json").exists():
        # Emit a fake stage marker so the UI shows "تحديد الحالة" (stage 7) as active.
        await _emit(job, {"type": "log", "line": "--- STAGE 11: v5 matching ---"})
        await _mark_stage(job, 7, "active", current=0, total=0)

        cmd_v5 = [str(PIPELINE_PYTHON), str(PIPELINE_MAIN_V5), job.output_dir, job.output_dir]
        rc5, _ = await _run_subprocess(job, cmd_v5)
        if rc5 == 0:
            v5_ok = True
        else:
            job.log_lines.append(f"⚠️ v5 returned {rc5}, continuing with v3 results")
            await _emit(job, {
                "type": "log",
                "line": f"⚠️ v5 returned {rc5}, continuing with v3 results",
            })

    # ---------- v6 (optional, needs v5 output) ----------
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
            await _mark_stage(job, 7, "error")
            job.log_lines.append(f"⚠️ v6 returned {rc6}, falling back to v5 results")
            await _emit(job, {
                "type": "log",
                "line": f"⚠️ v6 returned {rc6}, falling back to v5 results",
            })
    elif v5_ok:
        await _mark_stage(job, 7, "done")

    # mark any remaining stages as done so the bar reaches 100%
    for i in range(NUM_UI_STAGES):
        if job.stages.get(i, {}).get("status") not in ("done", "error"):
            await _mark_stage(job, i, "done")

    job.results = await _read_results(job)
    if job.results.get("summary", {}).get("total", 0) == 0:
        job.status = "partial"
        warning = (
            "اكتمل خط التحليل بدون استخراج متاجر. "
            "راجع سجل OCR والفلترة قبل اعتماد النتيجة."
        )
        job.results.setdefault("warnings", []).append(warning)
        job.log_lines.append(f"WARNING: {warning}")
    else:
        job.status = "done"
    manager.persist(job)
    await _emit(job, {"type": "status", "status": job.status})
    await _emit(job, {"type": "results", "results": job.results})
