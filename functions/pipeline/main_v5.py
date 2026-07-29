"""
v5 - الـ pipeline الواقعي.

بياخد stores_raw.json (من v3 cache) ويبني Excel نظيف:
- متاجر مؤكدة من Google → إحداثيات Google
- متاجر غير ممسوحة → إحداثيات الفريم من الداش كام (مع flag "تقريبي")

Usage:
    python main_v5.py <v3_dir> <output_dir>

مثال:
    python main_v5.py "d:/sharea elnassim/الشارع الجديد/output_v3" "d:/sharea elnassim/الشارع الجديد/output_v5"
"""
import os
import sys
import json
import argparse
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import GCP_CREDENTIALS
if GCP_CREDENTIALS and os.path.exists(GCP_CREDENTIALS):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GCP_CREDENTIALS

from places_v5 import match_all_stores
from exporter_v5 import export_excel_v5


def log_to_file(log_path):
    log_lines = []

    def _log(msg):
        print(msg, flush=True)
        log_lines.append(str(msg))

    def _flush():
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(log_lines))

    return _log, _flush


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('v3_dir', help='مجلد فيه stores_raw.json')
    parser.add_argument('output_dir', help='مجلد نتايج v5')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    log_path = os.path.join(args.output_dir, 'run_v5.log')
    log, flush = log_to_file(log_path)

    log(f"=" * 60)
    log(f"v5 pipeline | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  input: {args.v3_dir}")
    log(f"  output: {args.output_dir}")
    log(f"=" * 60)

    raw_path = os.path.join(args.v3_dir, 'stores_raw.json')
    if not os.path.exists(raw_path):
        log(f"❌ ما لقيتش stores_raw.json في {args.v3_dir}")
        flush()
        sys.exit(1)

    with open(raw_path, 'r', encoding='utf-8') as f:
        stores = json.load(f)
    log(f"✅ قريت {len(stores)} متجر من v3")

    # match
    match_all_stores(stores, log_fn=log)

    # save raw v5
    raw_out = os.path.join(args.output_dir, 'stores_v5_raw.json')
    with open(raw_out, 'w', encoding='utf-8') as f:
        json.dump(stores, f, ensure_ascii=False, indent=2, default=str)
    log(f"\n💾 raw → {raw_out}")

    # export Excel
    excel_out = os.path.join(args.output_dir, 'stores_v5_final.xlsx')
    export_excel_v5(stores, excel_out)
    log(f"📊 Excel → {excel_out}")

    flush()
    print(f"\n✅ تمام")


if __name__ == '__main__':
    main()
