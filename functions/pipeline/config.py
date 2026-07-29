"""
إعدادات الـ Pipeline - كل ما يمكن تعديله من هنا
"""
import os

# === Google Cloud ===
# In Cloud Functions the runtime credentials are used by default; allow
# overriding via environment variables for local development.
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "store-extract")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
GCP_CREDENTIALS = os.environ.get("GCP_CREDENTIALS", "")

# === Frame Extraction ===
# فترات التقطيع حسب السرعة (كم/س → ثواني)
# زودنا الفترة شوية عشان نقلل motion blur والتشويش في الصور.
SPEED_TO_INTERVAL = [
    (20, 1.0),    # 0-20 km/h → كل 1 ثانية
    (40, 0.5),    # 20-40 km/h → كل 0.5 ثانية
    (999, 0.4),   # 40+ km/h → كل 0.4 ثانية (بدل 0.25 عشان أوضح)
]
BASE_EXTRACTION_INTERVAL = 0.5  # نقطع كل نص ثانية في الـ pass الأول (تسريع OCR للـ GPS)
STATIONARY_SPEED_THRESHOLD = 2  # أقل من 2 كم/س = السيارة واقفة، نتخطى

# === Image Enhancement ===
SIGN_ZOOM_FACTOR = 2.0  # تكبير اللوحات
GPS_ZOOM_FACTOR = 3.0   # تكبير GPS
SIGN_CROP_Y_RANGE = (0.08, 0.65)  # نسبة ارتفاع منطقة اللوحات من الإطار
GPS_CROP_BOTTOM_PX = 100  # بيكسلات من الأسفل لمنطقة GPS
GPS_CROP_X_RATIO = 0.45   # نسبة عرض GPS من اليسار

# === OCR ===
CLOUD_VISION_BATCH_DELAY = 0.1  # تأخير بين استدعاءات OCR

# === Gemini ===
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BATCH_SIZE = 5       # عدد الفريمات في كل batch
GEMINI_MAX_TOKENS = 8192
GEMINI_TEMPERATURE = 0.1
GEMINI_RETRY_COUNT = 3
GEMINI_DELAY = 0.5

# === Confidence Flags ===
# المعايير اللي تعتبر المتجر "محتاج مراجعة"
FLAG_MIN_NAME_LENGTH = 3        # اسم أقل من 3 حروف
FLAG_EMPTY_CATEGORY = True      # تصنيف فاضي
FLAG_GHOST_CATEGORIES = ["غير محدد", "متجر", "محل", ""]  # تصنيفات مبهمة
FLAG_NO_ARABIC = True           # لو الاسم فيه إنجليزي بس

# === Places API ===
PLACES_RADIUS_METERS = 500      # نصف قطر البحث حوالين إحداثيات الفيديو
PLACES_NEARBY_THRESHOLD = 2000  # أقل من 2 كم = قريب (matched)
PLACES_MAX_RESULTS = 5          # عدد النتائج لكل بحث
PLACES_DELAY = 0.3              # تأخير بين الاستدعاءات

# === Excel Output ===
OUTPUT_SHEET_NAME = "بيانات المتاجر"
EXCEL_RTL = True

# === v4 Settings ===
# Places API (New) - بحث per-store strict
PLACES_STRICT_RADIUS_M = 80          # دائرة صارمة حول إحداثية المتجر
PLACES_FALLBACK_RADIUS_M = 200       # لو ما لقاش، نوسع شوية
PLACES_NEARBY_REVERSE_RADIUS_M = 40  # nearby reverse على إحداثية دقيقة

# OSM
OSM_SEARCH_RADIUS_M = 120

# Vision Judge
VISION_JUDGE_TOP_K = 5    # عدد candidates نبعتها للـ judge
VISION_JUDGE_ENABLED = True

# Street View
STREET_VIEW_ENABLED = False  # يحتاج Maps Static API + GOOGLE_MAPS_API_KEY env var

# Confidence thresholds
CONFIDENCE_AUTO = 0.7        # >= → قرار آلي
CONFIDENCE_REVIEW = 0.5      # 0.5-0.7 → flag
