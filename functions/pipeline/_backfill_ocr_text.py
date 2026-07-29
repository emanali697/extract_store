"""
One-off: backfill `ocr_text` onto stores in an existing job's
stores_v6_final.json by re-running OCR on signs/ folder.

Usage:
    python _backfill_ocr_text.py <output_dir>
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import GCP_CREDENTIALS
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GCP_CREDENTIALS

from ocr import batch_ocr


def parse_frames(s):
    if not s:
        return []
    out = []
    for part in str(s).split(','):
        part = part.strip()
        if '-' in part:
            try:
                a, b = part.split('-')
                out.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return sorted(set(out))


def main():
    if len(sys.argv) != 2:
        print("usage: _backfill_ocr_text.py <output_dir>")
        sys.exit(2)

    out = Path(sys.argv[1])
    signs_dir = out / "signs"
    final_path = out / "stores_v6_final.json"

    if not signs_dir.exists() or not final_path.exists():
        print(f"missing required files in {out}")
        sys.exit(2)

    sign_files = sorted(signs_dir.glob("sign_*.jpg"))
    # frame index from filename "sign_0042.jpg" → 42
    sign_paths = []
    sign_frame_nums = []
    for sp in sign_files:
        m = re.search(r"sign_(\d+)\.jpg$", sp.name)
        if not m:
            continue
        sign_paths.append(str(sp))
        sign_frame_nums.append(int(m.group(1)))

    print(f"re-OCR on {len(sign_paths)} sign images...")
    # Sequential single-thread to avoid the race I keep hitting
    texts = batch_ocr(sign_paths, log_fn=print, workers=1)
    frame_to_text = dict(zip(sign_frame_nums, texts))
    non_empty = sum(1 for t in texts if (t or "").strip())
    print(f"OCR done: {non_empty} / {len(texts)} non-empty")

    stores = json.loads(final_path.read_text(encoding="utf-8"))
    print(f"backfilling ocr_text on {len(stores)} stores...")

    filled = 0
    for s in stores:
        if s.get("ocr_text"):  # already has it
            continue
        frame_nums = parse_frames(s.get("frame", ""))
        parts = []
        seen = set()
        for n in frame_nums:
            t = (frame_to_text.get(n) or "").strip()
            if t and t not in seen:
                seen.add(t)
                parts.append(t)
        if parts:
            s["ocr_text"] = " | ".join(parts)
            filled += 1

    final_path.write_text(
        json.dumps(stores, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"OK — filled ocr_text for {filled} / {len(stores)} stores")


if __name__ == "__main__":
    main()
