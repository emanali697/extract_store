"""
v6 finalize: ياخد stores_with_status.json (بعد Tier 1)، يطبّق:
1. الدمج الإضافي اللي اكتشفناه أثناء بحث Tier 2
2. نتايج Tier 2 (3 متاجر مؤكدة نشطة)
3. Tier 3 لكل اللي فاضل (يحتاج تحقق ميداني)
4. توليد Excel نهائي
"""
import os
import sys
import json
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dedupe import merge_group


# ===== الدمج الإضافي اليدوي =====
ADDITIONAL_MERGES = [
    {
        'final_name': 'مطعم ومطبخ الجوهرة الراقي',
        'sources': ['مطعم ومطبخ مظبي', 'الجوهرة الراقي'],
    },
    {
        'final_name': 'محطة أبسكو',
        'sources': ['أيسكو', 'أبسكو', 'أسكو', 'ايسكو'],
    },
]


# ===== نتايج Tier 2 =====
TIER2_RESULTS = {
    'مطاعم تند': {
        'tier': 2,
        'status': 'نشط',
        'source': 'بحث ويب - تطبيقات توصيل',
        'evidence': 'مطعم Tndr موجود على هنقرستيشن وجاهز، عنده Instagram نشط',
        'web_links': [
            'https://hungerstation.com/sa-ar/restaurant/saudi/anak/anak/124540',
            'https://www.instagram.com/tndr.sa/',
        ],
    },
    'مطعم ومطبخ الجوهرة الراقي': {
        'tier': 2,
        'status': 'نشط',
        'source': 'بحث ويب - تطبيقات توصيل',
        'evidence': 'موجود على هنقرستيشن ونينجا في حي الجوهرة، له TikTok نشط',
        'web_links': [
            'https://hungerstation.com/sa-ar/restaurant/al-jawharah-restaurant-and-kitchen/jeddah/ghulail/55410',
            'https://ananinja.com/sa/ar/restaurants/matam-wa-matbakh-aljawhara-22339',
            'https://www.tiktok.com/@aljawhara_restaurant',
        ],
    },
    'محطة أبسكو': {
        'tier': 2,
        'status': 'نشط',
        'source': 'بحث ويب - شركة معروفة',
        'evidence': 'شركة Apsco للوقود، تعمل من 1960، فروع متعددة في جدة (حي الورود، المحمدية)',
        'web_links': [
            'https://apsco.com.sa/ar',
            'https://maps.yango.com/ar-sa/org/13908992345/',
        ],
    },
}


def apply_additional_merges(stores, log_fn=print):
    """دمج إضافي يدوي بناءً على اكتشافات Tier 2."""
    out = list(stores)
    for merge in ADDITIONAL_MERGES:
        final_name = merge['final_name']
        sources = set(merge['sources'])
        members = [s for s in out if s.get('name_ar') in sources]
        if len(members) < 2:
            log_fn(f"  ⚠️ skip merge for {final_name}: لقيت {len(members)} بس")
            continue
        merged = merge_group(members)
        merged['name_ar'] = final_name
        merged['original_names'] = [s.get('name_ar') for s in members]
        merged['merged_from'] = len(members)
        # شيل الـ originals وضيف الـ merged
        out = [s for s in out if s.get('name_ar') not in sources]
        out.append(merged)
        log_fn(f"  ✅ دمجت {len(members)} → {final_name}")
    return out


def apply_tier2_status(stores, log_fn=print):
    """تطبيق نتايج Tier 2 على المتاجر المعروفة."""
    count = 0
    for s in stores:
        name = s.get('name_ar', '')
        if name in TIER2_RESULTS and not s.get('status_check'):
            s['status_check'] = TIER2_RESULTS[name]
            count += 1
            log_fn(f"  ✅ Tier 2: {name} → نشط")
    log_fn(f"  ({count} متجر اتحدد له Tier 2)")
    return stores


def apply_tier3(stores, log_fn=print):
    """كل اللي مش معاه status_check يبقى Tier 3."""
    count = 0
    for s in stores:
        if not s.get('status_check'):
            has_phone = bool((s.get('phone') or '').strip())
            evidence = 'مفيش معلومات إنترنت موثوقة' + (' | معاه تليفون' if has_phone else ' | بدون تليفون')
            s['status_check'] = {
                'tier': 3,
                'status': 'غير محدد',
                'source': 'يحتاج تحقق ميداني',
                'evidence': evidence,
            }
            count += 1
    log_fn(f"  📍 Tier 3: {count} متجر اتحدد له 'يحتاج تحقق ميداني'")
    return stores


def main():
    in_path = r'd:/sharea elnassim/الشارع الجديد/output_v6/stores_with_status.json'
    out_dir = r'd:/sharea elnassim/الشارع الجديد/output_v6'

    print("=" * 60)
    print(f"v6 finalize | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    with open(in_path, 'r', encoding='utf-8') as f:
        stores = json.load(f)
    print(f"\nقريت {len(stores)} متجر")

    print("\n=== 1. الدمج الإضافي ===")
    stores = apply_additional_merges(stores)
    print(f"بعد الدمج: {len(stores)} متجر")

    print("\n=== 2. تطبيق Tier 2 ===")
    stores = apply_tier2_status(stores)

    print("\n=== 3. تطبيق Tier 3 ===")
    stores = apply_tier3(stores)

    # ملخص نهائي
    counts_status = {}
    counts_tier = {}
    for s in stores:
        sc = s.get('status_check') or {}
        st = sc.get('status', '?')
        tr = sc.get('tier', '?')
        counts_status[st] = counts_status.get(st, 0) + 1
        counts_tier[tr] = counts_tier.get(tr, 0) + 1

    print(f"\n=== ملخص نهائي ({len(stores)} متجر) ===")
    print("الحالة:")
    for k, v in counts_status.items():
        print(f"  {k}: {v}")
    print("الطبقة:")
    for k, v in sorted(counts_tier.items()):
        print(f"  Tier {k}: {v}")

    out_path = os.path.join(out_dir, 'stores_v6_final.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(stores, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 حفظت: {out_path}")
    return stores


if __name__ == '__main__':
    main()
