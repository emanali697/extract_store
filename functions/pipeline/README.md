# Store Extraction Pipeline

استخراج بيانات المتاجر من فيديوهات الداش كام مع Cloud Vision + Gemini + Places API + Status Determination.

> **الإصدار الحالي:** v6 (May 2026) — dedup + 3-tier status check
> **الإصدار القديم:** v3 (Sep 2025) — basic pipeline

---

## الإصدارات

```
v3 → v4 → v5 → v6 (الحالي)
```

| Version | الفايدة | الكود |
|---------|---------|-------|
| **v3** | pipeline أساسي (extract → OCR → Gemini → Places) | `main.py` + `places.py` + `exporter.py` |
| **v4** | multi-source matching (مهجور بسبب bugs) | `main_v4.py` + `places_v4.py` + ... |
| **v5** | تطبيع عربي + 3 tiers للموقع | `main_v5.py` + `places_v5.py` + `exporter_v5.py` |
| **v6** ⭐ | dedup + 3-tier status check | `finalize_v6.py` + `dedupe.py` + `status_check.py` + `exporter_v6.py` |

---

## بنية الملفات

### مشترك (كل الإصدارات)
- `config.py` — كل الإعدادات
- `extractor.py` — تقطيع الفيديو + استخراج GPS overlay
- `ocr.py` — Cloud Vision OCR متوازي (20 thread)
- `analyzer.py` — Gemini يحلل ويصنف
- `phone_utils.py` — تنظيف أرقام التليفون السعودية

### v3 (legacy)
- `places.py` — Places API بـ locationBias 500م
- `exporter.py` — Excel v3
- `main.py` — orchestrator v3
- `claude_review.py` — مراجعة Claude

### v4 (legacy)
- `places_v4.py` — multi-strategy Places search
- `osm.py` — OpenStreetMap (مش شغال لمتاجر صغيرة)
- `aggregator.py` — multi-source aggregator
- `vision_judge.py` — Gemini Vision للحكم
- `multi_frame.py` — per-frame GPS aggregation
- `street_view.py` — Street View Static API
- `exporter_v4.py`, `main_v4.py`

### v5 ⭐
- `places_v5.py` — Arabic-normalized matcher مع biased+filter
- `exporter_v5.py` — Excel v5 بألوان مصدر الموقع
- `main_v5.py` — orchestrator v5 (يشتغل من v3 cache)

### v6 ⭐⭐
- `dedupe.py` — دمج المتاجر المكررة (Jaccard + frame proximity)
- `status_check.py` — Tier 1: Google Places Details API
- `finalize_v6.py` — Tier 2 (web search results) + Tier 3 (field verification)
- `exporter_v6.py` — Excel v6 بأعمدة الحالة الكاملة
- `vision_status.py` — (ما اشتغلش) Vision على frames للحالة

---

## الاستخدام

### الـ flow الكامل (لفيديو جديد)

```bash
cd "d:/sharea elnassim/pipeline"

# Step 1: v3 - extract + OCR + Gemini + initial Places matching
python main.py "path/to/video.mp4" "path/to/output_v3"

# Step 2: v5 - clean Arabic-normalized matcher (from v3 cache)
python main_v5.py "path/to/output_v3" "path/to/output_v5"

# Step 3: v6 - dedup + status determination
# (قبل التشغيل، عدّل المسارات في finalize_v6.py)
python finalize_v6.py
python exporter_v6.py
```

النتيجة النهائية: `output_v6/stores_v6_final.xlsx`

### خيارات v3

```bash
# تخطي Places API
python main.py video.mp4 output/ --skip-places

# إعادة تشغيل من cache (تخطي extraction)
python main.py video.mp4 output/ --from-cache
```

---

## Pipeline Flow

### v3 — التقطيع والقراءة
1. **Pass 1** — تقطيع كل 0.25 ثانية
2. **GPS Reading** — قراءة السرعة والإحداثيات
3. **Smart Filter** — اختيار الفريمات حسب السرعة (0-20 km/h → 1s, 20-35 → 0.5s, 35+ → 0.25s)
4. **Sign Cropping** — قص + تكبير + تحسين
5. **OCR** — Cloud Vision على 20 thread
6. **Gemini Analysis** — تحليل وتصنيف + dedup + flag uncertainty
7. **Places API** — بحث بـ locationBias 500م

### v5 — تحسين المطابقة
8. **Arabic Normalization** — ة↔ه, ى↔ي, أ↔ا
9. **Biased + Filter** — radius 300م، ثم distance ≤ 80م، ثم name overlap ≥ 0.3
10. **Multi-variant search** — اسم أصلي + مُطبَّع + بدون كلمات حشو
11. **Phone cross-check** — لو اسم + تليفون يطابقوا نفس place_id → ثقة عالية

### v6 — Dedup والحالة
12. **Dedup** — Union-Find على المتاجر بـ (Jaccard ≥ 0.5 + frame gap ≤ 8)
13. **Tier 1: Google Places Details** — `businessStatus` للمتاجر المؤكدين
14. **Tier 2: Web Search** — تطبيقات توصيل + سوشيال ميديا
15. **Tier 3: Field Verification** — للمتاجر اللي مفيش معلومات إنترنت
16. **Export** — Excel نهائي بألوان الحالة

---

## المخرجات

### لكل version
```
output_v3/
├── raw_frames/         ← الفريمات الخام (224 على فيديو 1)
├── raw_gps/            ← GPS overlay crops
├── signs/              ← اللوحات المقصوصة (124)
├── gps/                ← GPS النهائية
├── stores_raw.json     ← 65 متجر
└── stores_final.xlsx   ← Excel v3

output_v5/
├── stores_v5_raw.json  ← 65 متجر + v5 status (confirmed/frame_only)
└── stores_v5_final.xlsx

output_v6/                        ⭐ الحالي
├── stores_merged.json          ← بعد dedup (50 متجر)
├── stores_with_status.json     ← بعد Tier 1
├── stores_v6_final.json        ← 46 متجر فريد + 3 tiers
└── stores_v6_final.xlsx        ← Excel النهائي
```

---

## نموذج البيانات في v6

```json
{
  "name_ar": "أمانا بروست بوينت",
  "category": "مطعم",
  "phone": "0599232485, ...",
  "frame": "53-67",
  "lat": "21.4380",
  "lng": "39.2498",
  "v5": {
    "status": "confirmed_high",
    "candidate": { "place_id": "ChIJ...", "name": "...", "lat": ..., "lng": ... },
    "score": 0.85
  },
  "status_check": {
    "tier": 1,
    "status": "نشط",
    "source": "Google Places Details",
    "evidence": "Google: OPERATIONAL | 129 تقييم | rating=3.7",
    "rating": 3.7,
    "review_count": 129,
    "open_now": false
  },
  "merged_from": 4,
  "original_names": ["امانا بروست", "كفتيريا وعصيرات الأمانة...", ...]
}
```

---

## التعديل والتحسين

كل الإعدادات في `config.py`:

- **السرعة/الفترة** — `SPEED_TO_INTERVAL`
- **التكبير** — `SIGN_ZOOM_FACTOR`, `GPS_ZOOM_FACTOR`
- **Gemini** — `GEMINI_MODEL`, `GEMINI_BATCH_SIZE`
- **Places** — `PLACES_RADIUS_METERS`, `PLACES_DELAY`
- **Vision Judge** — `VISION_JUDGE_ENABLED`

### إعدادات v6 (في الكود مباشرة)
- `dedupe.py`: `min_jaccard=0.5`, `max_frame_gap=8`
- `places_v5.py`: distance filter 80م، name overlap min 0.3
- `status_check.py`: PLACE_DETAILS_FIELDS

---

## الاعتمادات

```bash
pip install google-cloud-vision google-genai google-auth \
            pandas openpyxl opencv-python-headless \
            requests google-generativeai pycryptodome
```

---

## Google Cloud

- **Project:** `map-api-463307`
- **Credentials:** `d:/sharea elnassim/google_credentials.json`
- **APIs:** Vertex AI/Gemini, Cloud Vision, Places API (New)

---

## النتيجة الحالية (الشارع الجديد فيديو 1)

| الطبقة | العدد | الحالة |
|--------|------|--------|
| Tier 1 (Google Details) | 9 | كلهم نشطين ✅ |
| Tier 2 (بحث ويب) | 3 | كلهم نشطين ✅ |
| Tier 3 (يحتاج تحقق ميداني) | 34 | غير محدد ⚪ |
| **الإجمالي** | **46 متجر فريد** | **12 مؤكد نشط** |

---

## TODO

### الأولوية العالية
- [ ] Playwright scraper لـ Maroof — للـ 34 متجر "يحتاج تحقق ميداني"
- [ ] SPL integration — العنوان الوطني الرسمي
- [ ] تطبيق على فيديو 2 من الشارع الجديد

### تحسينات
- [ ] UI بـ Streamlit للشخص غير التقني
- [ ] Cleanup للـ versions القديمة (v3/v4)
- [ ] Logging file بدل print
- [ ] Resume mechanism
