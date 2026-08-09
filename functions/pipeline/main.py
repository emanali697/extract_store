"""
Main Pipeline - استخراج بيانات المتاجر من فيديو داش كام

Usage:
    python main.py <video_path> <output_dir> [--center-lat LAT --center-lng LNG] [--skip-places]

Example:
    python main.py "d:/sharea elnassim/الشارع الجديد/2026_0414_130334_000001F.MP4" \\
        "d:/sharea elnassim/الشارع الجديد/output_v3"
"""
import os
import sys
import json
import argparse
from datetime import datetime

# Fix Windows encoding
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import GCP_CREDENTIALS
# Only point to a service-account file if one was explicitly provided. In
# Cloud Functions the runtime credentials are used automatically.
if GCP_CREDENTIALS and os.path.exists(GCP_CREDENTIALS):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GCP_CREDENTIALS

from extractor import extract_frames_pass1, filter_frames_by_speed, process_selected_frames
from ocr import read_gps_from_images
from analyzer import run_analysis
from exporter import export_excel


def log(msg):
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser(description="Extract stores from dashcam video")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("output", help="Output directory")
    parser.add_argument("--center-lat", type=float, default=None,
                        help="Center latitude for Places search (default: average from video GPS)")
    parser.add_argument("--center-lng", type=float, default=None,
                        help="Center longitude for Places search")
    parser.add_argument("--skip-places", action="store_true",
                        help="Skip Places API enrichment")
    parser.add_argument("--from-cache", action="store_true",
                        help="Skip frame extraction, use existing frames in output dir")
    parser.add_argument("--start-seconds", type=float, default=0,
                        help="Start frame extraction from this second (seek). "
                             "Useful for large videos where the start isn't relevant.")
    parser.add_argument("--speed-mode", choices=("auto", "fast", "precise"),
                        default="auto", help="Frame selection density")
    args = parser.parse_args()

    video_path = args.video
    output_dir = args.output

    log("=" * 70)
    log(f"  Store Extraction Pipeline")
    log(f"  Video: {video_path}")
    log(f"  Output: {output_dir}")
    log("=" * 70)

    # === Stage 1: Frame Extraction (Pass 1 - raw) ===
    if not args.from_cache:
        log("\n--- STAGE 1: Raw frame extraction ---")
        raw_frames = extract_frames_pass1(video_path, output_dir,
                                          start_seconds=args.start_seconds, log_fn=log)
    else:
        log("\n--- STAGE 1: Loading cached raw frames ---")
        raw_dir = os.path.join(output_dir, "raw_frames")
        gps_dir = os.path.join(output_dir, "raw_gps")
        raw_frames = []
        for f in sorted(os.listdir(raw_dir)):
            if f.endswith('.jpg'):
                idx = int(f.replace("frame_", "").replace(".jpg", ""))
                raw_frames.append({
                    'idx': idx,
                    'timestamp': idx * 0.25,  # approx
                    'frame_path': os.path.join(raw_dir, f),
                    'gps_path': os.path.join(gps_dir, f.replace("frame_", "gps_")),
                })
        log(f"Loaded {len(raw_frames)} cached frames")

    if not raw_frames:
        log("ERROR: No frames extracted")
        return 1

    # === Stage 2: Read GPS from raw frames ===
    log("\n--- STAGE 2: Reading GPS + speed from raw frames ---")
    gps_image_paths = [f['gps_path'] for f in raw_frames]
    gps_data = read_gps_from_images(gps_image_paths, log_fn=log)

    speeds = [g.get('speed', 0) for g in gps_data]
    avg_speed = sum(speeds) / len(speeds) if speeds else 0
    max_speed = max(speeds) if speeds else 0
    log(f"Speeds: avg={avg_speed:.1f} km/h, max={max_speed} km/h")

    # === Stage 3: Smart filtering by speed ===
    log("\n--- STAGE 3: Smart frame filtering by speed ---")
    selected = filter_frames_by_speed(
        raw_frames,
        gps_data,
        speed_mode=args.speed_mode,
        log_fn=log,
    )

    # === Stage 4: Process selected frames (crop signs) ===
    log("\n--- STAGE 4: Processing selected frames ---")
    processed = process_selected_frames(selected, output_dir, log_fn=log)

    # GPS for processed frames
    gps_for_processed = [{'speed': p.get('speed'), 'lat': p.get('lat'), 'lng': p.get('lng')}
                         for p in processed]

    # === Stage 5: Direct visual reading with Gemini ===
    # Cloud Vision OCR remains limited to the GPS overlay above. Store names
    # and phone numbers are read directly from adjacent sign images by Gemini.
    log("\n--- STAGE 5: Gemini visual sign reading ---")
    stores = run_analysis(processed, [], gps_for_processed, log_fn=log)

    # === Stage 6: Evidence validation ===
    log("\n--- STAGE 6: Gemini evidence validation ---")
    stores = [
        store for store in stores
        if (store.get('visual_evidence') or {}).get('verified')
        and store.get('source_visible_in_video') is True
    ]
    log(f"Visually verified stores: {len(stores)}")

    # === Stage 7: Determine center coordinates for Places ===
    center_lat = args.center_lat
    center_lng = args.center_lng
    if center_lat is None or center_lng is None:
        valid_coords = [(g['lat'], g['lng']) for g in gps_data
                        if g.get('lat') and g.get('lng')]
        if valid_coords:
            center_lat = sum(c[0] for c in valid_coords) / len(valid_coords)
            center_lng = sum(c[1] for c in valid_coords) / len(valid_coords)
            log(f"\nAuto-detected center: {center_lat:.4f}, {center_lng:.4f}")
        else:
            log("WARNING: No GPS data found, skipping Places")
            args.skip_places = True

    # === Stage 8: Places enrichment ===
    # The strict v5 matcher runs immediately after this stage. Do not run the
    # legacy broad-radius matcher here: it adds cost and can attach unrelated
    # nearby businesses to an otherwise valid visual candidate.
    if not args.skip_places and center_lat and center_lng:
        log(f"\n--- STAGE 8: Places API enrichment ---")
        log("Places matching deferred to the strict v5 name/distance matcher")

    # === Stage 9: Save raw JSON (for further processing) ===
    json_path = os.path.join(output_dir, "stores_raw.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(stores, f, ensure_ascii=False, indent=2)
    log(f"\nJSON saved: {json_path}")

    # === Stage 10: Export Excel ===
    log("\n--- STAGE 10: Exporting Excel ---")
    xlsx_path = os.path.join(output_dir, "stores_final.xlsx")
    export_excel(stores, xlsx_path)
    log(f"Excel saved: {xlsx_path}")

    # === Summary ===
    total = len(stores)
    flagged = sum(1 for s in stores if s.get('needs_review'))
    with_phone = sum(1 for s in stores
                     if s.get('phone') or (s.get('places', {}) or {}).get('phone'))
    matched = sum(1 for s in stores
                  if (s.get('places', {}) or {}).get('match_status') == 'مطابق')

    log("\n" + "=" * 70)
    log(f"SUMMARY:")
    log(f"  Total stores: {total}")
    log(f"  Need review: {flagged}")
    log(f"  With phone: {with_phone}")
    log(f"  Matched in Places (nearby): {matched}")
    log(f"\nFiles:")
    log(f"  Excel: {xlsx_path}")
    log(f"  JSON: {json_path}")
    log("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
