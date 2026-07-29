"""
v6 orchestrator — wires the existing pipeline modules into a single, repeatable
chain that can run for ANY job directory (no hard-coded street paths).

Inputs:
    <output_dir>/stores_v5_raw.json   (produced by main_v5.py)

Outputs (all in <output_dir>):
    stores_merged.json         after advanced dedupe
    stores_with_status.json    after Tier 1 (Google Places Details)
    stores_v6_final.json       after additional merges + Tier 2 + Tier 3
    stores_v6_final.xlsx       formatted Excel (uses exporter_v6.export_excel_v6)

The script emits __PROGRESS__ markers + STAGE 13/14/15/16 boundaries so the
FastAPI runner can drive the UI's "تحديد الحالة" + "إنتاج Excel" rows.

Usage:
    python run_v6.py <output_dir>
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import GCP_CREDENTIALS
if GCP_CREDENTIALS and os.path.exists(GCP_CREDENTIALS):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GCP_CREDENTIALS

from progress import emit_progress
from dedupe import dedupe_stores
from status_check import run_tier1
# NOTE: We deliberately DO NOT import apply_additional_merges or apply_tier2_status
# from finalize_v6. Those two helpers reference hard-coded data discovered manually
# on the original شارع النسيم run (ADDITIONAL_MERGES, TIER2_RESULTS). Auto-applying
# them to other streets would falsely promote stores that just share a name. Only
# `apply_tier3` (which is generic — flags every still-unclassified store as
# "يحتاج تحقق ميداني") is safe to reuse across jobs.
from finalize_v6 import apply_tier3
from auto_review import auto_review
from exporter_v6 import export_excel_v6


# Distance helper (haversine) for accuracy approximation.
def _haversine_m(lat1, lng1, lat2, lng2):
    from math import asin, cos, radians, sin, sqrt
    try:
        lat1, lng1, lat2, lng2 = map(float, (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    R = 6_371_000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * R * asin(sqrt(a))


def enrich_location_meta(stores):
    """
    For each store, decide:
      location_source        google_places | dashcam_frame
      location_accuracy_m    estimate in meters (lower = more precise)
      lat / lng              the location we trust most
      google_place_id        from v5.candidate.place_id if present
    """
    for s in stores:
        v5 = s.get('v5') or {}
        cand = v5.get('candidate') or {}

        gp_lat = cand.get('lat')
        gp_lng = cand.get('lng')
        f_lat = s.get('lat')
        f_lng = s.get('lng')

        if gp_lat and gp_lng:
            s['location_source'] = 'google_places'
            s['lat'] = gp_lat
            s['lng'] = gp_lng
            s['google_place_id'] = cand.get('place_id')
            # If we have both Google + dashcam coords, accuracy ≈ their distance
            if f_lat and f_lng:
                d = _haversine_m(gp_lat, gp_lng, f_lat, f_lng)
                # Google itself is ~5m; widen if dashcam disagrees a lot
                s['location_accuracy_m'] = max(5, int(d)) if d is not None else 10
            else:
                s['location_accuracy_m'] = 10
        elif f_lat and f_lng:
            s['location_source'] = 'dashcam_frame'
            s['location_accuracy_m'] = 30  # typical dashcam GPS overlay error
            s['google_place_id'] = None
        else:
            s['location_source'] = 'unknown'
            s['location_accuracy_m'] = None
            s['google_place_id'] = None
    return stores


def _save(path: Path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )


def log(msg):
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output_dir')
    parser.add_argument('--skip-status', action='store_true',
                        help='تخطّي تحديد الحالة (Tier 1 — نشط/مغلق من Google). '
                             'بيوفّر وقت ومكالمات Google لو محتاجين الاسم/التليفون/الموقع بس.')
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    v5_path = out_dir / 'stores_v5_raw.json'

    if not v5_path.exists():
        # Fall back to v3 raw if v5 hasn't run
        v5_path = out_dir / 'stores_raw.json'
    if not v5_path.exists():
        log(f"ERROR: no input found in {out_dir}")
        sys.exit(2)

    log(f"v6 orchestrator — input: {v5_path.name}")
    stores = json.loads(v5_path.read_text(encoding='utf-8'))
    log(f"loaded {len(stores)} stores")

    # ---- STAGE 13: Advanced dedupe ----
    log("\n--- STAGE 13: Advanced dedupe ---")
    emit_progress(0, max(1, len(stores)))
    stores = dedupe_stores(stores, log_fn=log)
    emit_progress(len(stores), max(1, len(stores)))
    _save(out_dir / 'stores_merged.json', stores)
    log(f"saved stores_merged.json ({len(stores)} unique)")

    # ---- STAGE 14: Tier 1 — Google Places Details ----
    log("\n--- STAGE 14: Tier 1 status check ---")
    if args.skip_status:
        log("  ⏭️ تخطّي تحديد الحالة (--skip-status) — هنكتفي بالاسم/التليفون/الموقع")
        emit_progress(1, 1)
    else:
        eligible = [s for s in stores if ((s.get('v5') or {}).get('candidate') or {}).get('place_id')]
        emit_progress(0, max(1, len(eligible)))
        stores = run_tier1(stores, log_fn=log)
        emit_progress(len(eligible), max(1, len(eligible)))
    _save(out_dir / 'stores_with_status.json', stores)

    # ---- STAGE 15: Tier 3 fallback ----
    # apply_additional_merges + apply_tier2_status intentionally skipped —
    # they hold project-specific hardcoded data from the original شارع النسيم run.
    log("\n--- STAGE 15: Tier 3 fallback ---")
    emit_progress(0, 1)
    stores = apply_tier3(stores, log_fn=log)
    emit_progress(1, 1)

    # ---- STAGE 17: Auto-review of Tier 3 ----
    log("\n--- STAGE 17: Auto-Review ---")
    signs_dir = out_dir / "signs"
    stores = auto_review(stores, log_fn=log, signs_dir=signs_dir)

    # ---- Location enrichment (source, accuracy, place_id) ----
    log("\n--- Enriching location metadata ---")
    stores = enrich_location_meta(stores)

    final_json = out_dir / 'stores_v6_final.json'
    _save(final_json, stores)
    log(f"saved {final_json.name} ({len(stores)} stores)")

    # ---- STAGE 16: Excel v6 ----
    log("\n--- STAGE 16: Excel v6 export ---")
    emit_progress(0, 1)
    excel_path = out_dir / 'stores_v6_final.xlsx'
    export_excel_v6(stores, str(excel_path))
    emit_progress(1, 1)
    log(f"saved {excel_path.name}")

    # ---- Summary ----
    counts_tier = {}
    counts_status = {}
    for s in stores:
        sc = s.get('status_check') or {}
        t = sc.get('tier', '?')
        st = sc.get('status', '?')
        counts_tier[t] = counts_tier.get(t, 0) + 1
        counts_status[st] = counts_status.get(st, 0) + 1

    log("\n=== ملخص v6 ===")
    log(f"  إجمالي المتاجر: {len(stores)}")
    log(f"  Tiers: {counts_tier}")
    log(f"  Statuses: {counts_status}")


if __name__ == '__main__':
    main()
