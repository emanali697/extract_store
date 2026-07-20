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
import sys
from pathlib import Path

from config import PIPELINE_MAIN, PIPELINE_DIR
from jobs import Job, manager
from stages import parse_stage_line, parse_progress_hint

PIPELINE_MAIN_V5 = PIPELINE_DIR / "main_v5.py"
PIPELINE_RUN_V6 = PIPELINE_DIR / "run_v6.py"
NUM_UI_STAGES = 9


async def _emit(job: Job, event: dict) -> None:
    await manager.publish(job.job_id, event)


async def _mark_stage(job: Job, ui_idx: int, status: str,
                      current: int | None = None, total: int | None = None) -> None:
    entry = job.stages.get(ui_idx, {})
    entry["status"] = status
    if current is not None:
        entry["current"] = current
    if total is not None:
        entry["total"] = total
    job.stages[ui_idx] = entry
    manager.persist(job)
    await _emit(job, {
        "type": "stage",
        "stage": ui_idx,
        "status": status,
        "current": entry.get("current"),
        "total": entry.get("total"),
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
    """
    job.log_lines.append(f"$ {' '.join(cmd)}")
    await _emit(job, {"type": "log", "line": f"$ {' '.join(cmd)}"})

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PIPELINE_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )

    current_ui_stage: int | None = None

    while True:
        raw_line = await proc.stdout.readline()
        if not raw_line:
            break
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        if not line:
            continue

        job.log_lines.append(line)
        await _emit(job, {"type": "log", "line": line})

        new_stage = parse_stage_line(line)
        if new_stage is not None:
            if current_ui_stage is not None and current_ui_stage != new_stage:
                await _mark_stage(job, current_ui_stage, "done")
            current_ui_stage = new_stage
            await _mark_stage(job, new_stage, "active", current=0, total=0)
            continue

        if current_ui_stage is not None:
            hint = parse_progress_hint(line)
            if hint:
                cur, tot = hint
                await _mark_stage(job, current_ui_stage, "active", current=cur, total=tot)

    rc = await proc.wait()
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
    cmd_v3 = [sys.executable, str(PIPELINE_MAIN), job.video_path, job.output_dir]
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

        cmd_v5 = [sys.executable, str(PIPELINE_MAIN_V5), job.output_dir, job.output_dir]
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
        cmd_v6 = [sys.executable, str(PIPELINE_RUN_V6), job.output_dir]
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

    job.status = "done"
    job.results = await _read_results(job)
    manager.persist(job)
    await _emit(job, {"type": "status", "status": "done"})
    await _emit(job, {"type": "results", "results": job.results})
