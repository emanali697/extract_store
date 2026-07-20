"""
Batch-runner: pushes the 4 dashcam videos through the pipeline one at a time.

- Talks to the running backend over HTTP (stdlib only, no `requests` needed).
- Points each job straight at the file in Downloads — no 4 GB HTTP upload.
- Runs sequentially (waits for each job to finish) so the network isn't
  hammered by parallel Cloud Vision OCR calls.
- Prints a per-video summary at the end (stores / phones / tiers).

Usage (backend must be running on :8000):
    python _batch_run.py
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
import urllib.error

# Windows console defaults to cp1256 here — force UTF-8 so Arabic/emoji print.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
VIDEO_DIR = r"C:\Users\Admin\Downloads\video"

# label = same number as the video file (000001F → "1", ...)
ALL_VIDEOS = [
    {"num": "1", "file": r"2026_0414_130334_000001F (1).MP4"},
    {"num": "2", "file": r"2026_0414_132148_000002F.MP4"},
    {"num": "3", "file": r"2026_0414_132300_000003F.MP4"},
    {"num": "4", "file": r"2026_0414_132911_000004F.MP4"},
]

# Video 4 (2.6 GB) — the large one. Videos 2/3 done, video 1 skipped.
RUN_NUMS = ["4"]
VIDEOS = [v for n in RUN_NUMS for v in ALL_VIDEOS if v["num"] == n]

POLL_SECONDS = 10
# generous ceiling per video (the 2.6 GB one is the slow case)
MAX_WAIT_SECONDS = 3 * 60 * 60


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _wait_for_backend() -> None:
    for _ in range(30):
        try:
            _get("/health")
            return
        except Exception:
            time.sleep(2)
    raise SystemExit("Backend not reachable on :8000 — start it first.")


def run_one(num: str, video_path: str) -> dict:
    print(f"\n{'='*60}\n▶ Video {num}: {video_path}\n{'='*60}", flush=True)

    settings = {
        "streetName": f"فيديو {num}",
        "city": "",
        "district": "",
        "speedMode": "auto",
        "enablePlaces": True,    # Google Places matching (location) — needed
        "enableStatus": False,   # skip Tier 1 status check (نشط/مغلق) per user
        # Video 4 is large; start from minute 3 (skip the irrelevant start).
        "startSeconds": 180 if num == "4" else 0,
        "videoPath": video_path,
    }
    resp = _post("/jobs", settings)
    job_id = resp["jobId"]
    print(f"  job_id = {job_id}  (status={resp['status']})", flush=True)

    started = time.time()
    last_status = ""
    while True:
        time.sleep(POLL_SECONDS)
        try:
            snap = _get(f"/jobs/{job_id}")
        except Exception as e:
            print(f"  ...poll error: {e}", flush=True)
            continue

        status = snap.get("status")
        if status != last_status:
            print(f"  status → {status}", flush=True)
            last_status = status

        if status in ("done", "error", "interrupted"):
            break
        if time.time() - started > MAX_WAIT_SECONDS:
            print("  ⏱ timed out waiting for this job", flush=True)
            break

    summary = {"num": num, "job_id": job_id, "status": last_status}
    if last_status == "done":
        try:
            res = _get(f"/jobs/{job_id}/results")
            s = res.get("summary", {})
            summary.update({
                "total": s.get("total"),
                "phones": s.get("phones"),
                "precise": s.get("precise"),
                "auto_passed": s.get("auto_passed"),
                "needs_human": s.get("needs_human"),
            })
            print(f"  ✅ {s.get('total')} متجر | {s.get('phones')} بأرقام | "
                  f"{s.get('precise')} بموقع دقيق | "
                  f"{s.get('needs_human')} محتاج مراجعة", flush=True)
        except Exception as e:
            print(f"  could not fetch results: {e}", flush=True)
    else:
        print(f"  ⚠ ended with status={last_status} "
              f"(error={snap.get('error')})", flush=True)
    return summary


def main() -> None:
    _wait_for_backend()
    results = []
    for v in VIDEOS:
        path = f"{VIDEO_DIR}\\{v['file']}"
        results.append(run_one(v["num"], path))

    print(f"\n\n{'#'*60}\n# الملخص النهائي\n{'#'*60}")
    for r in results:
        if r["status"] == "done":
            print(f"  فيديو {r['num']}: {r.get('total')} متجر، "
                  f"{r.get('phones')} رقم، {r.get('needs_human')} للمراجعة "
                  f"— job {r['job_id']}")
        else:
            print(f"  فيديو {r['num']}: ❌ {r['status']} — job {r['job_id']}")
    # machine-readable copy
    print("\nJSON:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
