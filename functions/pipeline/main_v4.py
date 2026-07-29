"""
v4 Pipeline - استخراج بيانات المتاجر بأعلى دقة ممكنة.

التحسينات على v3:
1. Per-frame GPS (median من كل فريمات المتجر)
2. Multi-frame voting للتليفونات (دقة OCR أعلى)
3. Saudi phone validator + corrector
4. Multi-source matching (Google + OSM)
5. locationRestriction صارم (مفيش مطابقات في مدن بعيدة)
6. بحث بالتليفون في Places (الأدق)
7. Reverse geocoding على إحداثية المتجر الدقيقة
8. Gemini Vision Judge لاختيار الـ candidate الأفضل
9. (اختياري) Street View للتأكيد البصري

Usage:
    python main_v4.py <video_path> <output_dir>
                      [--from-cache] [--from-v3 <v3_dir>]
                      [--no-vision] [--with-street-view]
"""
import os
import sys
import json
import argparse
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import GCP_CREDENTIALS, VISION_JUDGE_ENABLED, STREET_VIEW_ENABLED
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GCP_CREDENTIALS

from extractor import extract_frames_pass1, filter_frames_by_speed, process_selected_frames
from ocr import read_gps_from_images, batch_ocr
from analyzer import run_analysis
from multi_frame import enrich_stores_with_aggregates
from aggregator import adjudicate_all_stores
from exporter_v4 import export_excel_v4


def log(msg):
    print(msg, flush=True)


def load_v3_state(v3_dir):
    """
    استرجاع المتاجر من v3 (تخطّي مراحل extraction/OCR/Gemini الثقيلة).
    """
    json_path = os.path.join(v3_dir, "stores_raw.json")
    if not os.path.exists(json_path):
        return None, None, None, None

    with open(json_path, 'r', encoding='utf-8') as f:
        stores = json.load(f)

    # نظف بيانات Places القديمة (هنعيد المطابقة من الصفر)
    for s in stores:
        s.pop('places', None)

    # حاول نلاقي مسارات الـ frames الموجودة من v3
    raw_dir = os.path.join(v3_dir, "raw_frames")
    signs_dir = os.path.join(v3_dir, "signs")
    gps_dir = os.path.join(v3_dir, "gps")

    if not os.path.exists(signs_dir):
        log(f"WARNING: signs dir not found in {v3_dir}")
        return stores, [], [], []

    # نبني processed_frames من الملفات الموجودة
    processed = []
    sign_files = sorted([f for f in os.listdir(signs_dir) if f.endswith('.jpg')])
    for f in sign_files:
        idx = int(f.replace('sign_', '').replace('.jpg', ''))
        processed.append({
            'final_idx': idx,
            'sign_path': os.path.join(signs_dir, f),
            'gps_final_path': os.path.join(gps_dir, f.replace('sign_', 'gps_')),
        })

    return stores, processed, None, None


def main():
    parser = argparse.ArgumentParser(description="v4 store extraction")
    parser.add_argument("video", help="Path to video (or 'cached' if --from-v3 used)", nargs='?')
    parser.add_argument("output", help="Output directory", nargs='?')
    parser.add_argument("--from-v3", help="Reuse stores_raw.json from v3 directory")
    parser.add_argument("--from-cache", action="store_true",
                        help="Reuse extracted frames in output dir")
    parser.add_argument("--no-vision", action="store_true",
                        help="Disable Gemini Vision Judge (cheaper, less accurate)")
    parser.add_argument("--with-street-view", action="store_true",
                        help="Enable Street View verification (needs GOOGLE_MAPS_API_KEY)")
    parser.add_argument("--reocr", action="store_true",
                        help="Re-run OCR for multi-frame voting (slower, fuller). "
                             "Default: trust v3 phones + just validate them")
    args = parser.parse_args()

    use_vision = VISION_JUDGE_ENABLED and not args.no_vision
    use_sv = args.with_street_view or STREET_VIEW_ENABLED

    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    log("=" * 70)
    log("  v4 Store Extraction Pipeline")
    log(f"  Output: {output_dir}")
    log(f"  Vision Judge: {'ON' if use_vision else 'OFF'}")
    log(f"  Street View: {'ON' if use_sv else 'OFF'}")
    log("=" * 70)

    # === المسار 1: استرجاع v3 (سريع) ===
    if args.from_v3:
        log(f"\n--- Loading v3 state from: {args.from_v3} ---")
        stores, processed, _, _ = load_v3_state(args.from_v3)
        if not stores:
            log("ERROR: couldn't load v3 state")
            return 1
        log(f"Loaded {len(stores)} stores, {len(processed)} processed frames")

        if args.reocr:
            # OCR re-run لـ multi-frame voting الكامل
            log(f"\n--- Re-running OCR for multi-frame voting ---")
            sign_paths = [p['sign_path'] for p in processed]
            ocr_texts = batch_ocr(sign_paths, log_fn=log)

            gps_paths = [p['gps_final_path'] for p in processed
                         if os.path.exists(p['gps_final_path'])]
            if gps_paths and len(gps_paths) == len(processed):
                log(f"\n--- Reading GPS from frames for multi-frame median ---")
                gps_data = read_gps_from_images(gps_paths, log_fn=log)
            else:
                gps_data = [{} for _ in processed]
        else:
            # Quick mode: استخدم phones اللي طلعت من Gemini وصلحها بالـ validator
            log(f"\n--- Quick mode: trusting v3 phones (use --reocr for full multi-frame voting) ---")
            ocr_texts = []
            gps_data = []
            for s in stores:
                # ocr_text بسيط لكل متجر = الأسماء + التليفون اللي طلعهم Gemini
                t = ' '.join([str(s.get(k, '') or '') for k in ('name_ar', 'name_en', 'phone', 'notes')])
                ocr_texts.append(t)
                gps_data.append({
                    'lat': float(s['lat']) if s.get('lat') else None,
                    'lng': float(s['lng']) if s.get('lng') else None,
                })
            # في quick mode، نخلي processed_frames مساوية لعدد المتاجر (1:1 mapping)
            # عشان aggregate_store_signals يلاقي الـ frames بسهولة
            quick_processed = []
            for i, s in enumerate(stores, 1):
                # نضع final_idx كأنه نفس الـ frame اللي تخزن في store['frame']
                # multi_frame.aggregate_store_signals بيقرا frame_indices من store['frame']
                quick_processed.append({
                    'final_idx': i,
                    'sign_path': '',
                })
            # نعدل store['frame'] لكل واحد يبقى نفس i (عشان يلاقي ocr_texts[i-1])
            for i, s in enumerate(stores, 1):
                s['_orig_frame'] = s.get('frame', '')
                s['frame'] = str(i)
            processed = quick_processed

    # === المسار 2: من الفيديو من الصفر ===
    else:
        if not args.video or not args.output:
            log("ERROR: video and output required (or use --from-v3)")
            return 1

        video_path = args.video
        log(f"  Video: {video_path}")

        if not args.from_cache:
            log("\n--- STAGE 1: Raw frame extraction ---")
            raw_frames = extract_frames_pass1(video_path, output_dir, log_fn=log)
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
                        'timestamp': idx * 0.25,
                        'frame_path': os.path.join(raw_dir, f),
                        'gps_path': os.path.join(gps_dir, f.replace("frame_", "gps_")),
                    })
            log(f"Loaded {len(raw_frames)} cached frames")

        if not raw_frames:
            log("ERROR: No frames")
            return 1

        log("\n--- STAGE 2: GPS + speed ---")
        gps_image_paths = [f['gps_path'] for f in raw_frames]
        gps_raw = read_gps_from_images(gps_image_paths, log_fn=log)

        log("\n--- STAGE 3: Filter by speed ---")
        selected = filter_frames_by_speed(raw_frames, gps_raw, log_fn=log)

        log("\n--- STAGE 4: Process (sign crops) ---")
        processed = process_selected_frames(selected, output_dir, log_fn=log)

        log("\n--- STAGE 5: OCR signs ---")
        sign_paths = [p['sign_path'] for p in processed]
        ocr_texts = batch_ocr(sign_paths, log_fn=log)

        gps_data = [{'speed': p.get('speed'), 'lat': p.get('lat'), 'lng': p.get('lng')}
                    for p in processed]

        log("\n--- STAGE 6: Gemini analysis ---")
        stores = run_analysis(processed, ocr_texts, gps_data, log_fn=log)

    # === STAGE 7: Multi-frame voting + Saudi phone validation ===
    log(f"\n--- STAGE 7: Multi-frame voting (OCR + GPS) ---")
    stores = enrich_stores_with_aggregates(stores, ocr_texts, gps_data, processed)
    with_phone = sum(1 for s in stores if s.get('phone'))
    log(f"  Stores with validated Saudi phone: {with_phone}/{len(stores)}")

    # نرجع الـ frame الأصلي لو كنا في quick mode
    for s in stores:
        if '_orig_frame' in s:
            s['frame'] = s.pop('_orig_frame')

    # === STAGE 8: Multi-source adjudication (Places + OSM + Vision Judge) ===
    log(f"\n--- STAGE 8: Multi-source adjudication ---")
    stores = adjudicate_all_stores(
        stores, output_dir,
        use_vision=use_vision,
        use_street_view=use_sv,
        log_fn=log,
    )

    # === STAGE 9: Save raw JSON (نحذف الـ binary keys للحفاظ على JSON صالح) ===
    save_path = os.path.join(output_dir, "stores_v4_raw.json")
    clean_stores = []
    for s in stores:
        c = {k: v for k, v in s.items() if not k.startswith('_')}
        clean_stores.append(c)
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(clean_stores, f, ensure_ascii=False, indent=2, default=str)
    log(f"\nJSON: {save_path}")

    # === STAGE 10: Excel ===
    xlsx_path = os.path.join(output_dir, "stores_v4_final.xlsx")
    export_excel_v4(stores, xlsx_path)
    log(f"Excel: {xlsx_path}")

    # === Summary ===
    total = len(stores)
    matched = sum(1 for s in stores if (s.get('v4') or {}).get('final_match'))
    high_conf = sum(1 for s in stores if (s.get('v4') or {}).get('confidence', 0) >= 0.7)
    flagged = sum(1 for s in stores
                  if (s.get('v4') or {}).get('confidence', 0) < 0.7
                  or not (s.get('v4') or {}).get('final_match'))
    with_phone_final = sum(1 for s in stores if s.get('phone'))

    log("\n" + "=" * 70)
    log(f"v4 SUMMARY:")
    log(f"  Total stores: {total}")
    log(f"  Matched (any source): {matched}")
    log(f"  High confidence (≥70%): {high_conf}")
    log(f"  With validated phone: {with_phone_final}")
    log(f"  Flagged for review: {flagged}")
    log(f"\nFiles:")
    log(f"  Excel: {xlsx_path}")
    log(f"  JSON: {save_path}")
    log("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
