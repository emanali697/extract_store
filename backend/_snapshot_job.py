"""One-off: snapshot a live job from the running backend into state.db."""
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from jobs import Job
import db

JOB_ID = "29f2c13926b3"

status_data = json.loads(
    urllib.request.urlopen(f"http://127.0.0.1:8000/jobs/{JOB_ID}").read()
)
results = json.loads(
    urllib.request.urlopen(f"http://127.0.0.1:8000/jobs/{JOB_ID}/results").read()
)

video_path = r"D:\sharea elnassim\backend\uploads\الشارع الاول.MP4"
output_dir = r"D:\sharea elnassim\backend\jobs" + "\\" + JOB_ID

job = Job(
    job_id=JOB_ID,
    video_path=video_path,
    street_name="",
    city="",
    district="",
    speed_mode="auto",
    enable_places=True,
    enable_status=True,
    status=status_data["status"],
    output_dir=output_dir,
    stages={int(k): v for k, v in status_data["stages"].items()},
    results=results,
)

db.init()
db.upsert_job(job)
print("OK — saved", JOB_ID, "to state.db")
print("Stores in results:", len(results.get("stores", [])))
