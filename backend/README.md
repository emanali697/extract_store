# Backend — Store Extractor API

FastAPI backend للمشروع **Store Extractor**. بيستقبل الفيديوهات، يشغّل الـ ML Pipeline كـ subprocess، ويوفر REST APIs + WebSocket للـ Frontend.

## المتطلبات

- Python 3.12+
- `../pipeline/` folder يحتوي على `main.py`
- (اختياري) مفاتيح Firebase Service Account

## التشغيل

```powershell
cd "d:/sharea elnassim/extract stores/backend"
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

بعد التشغيل:

- API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

## هيكل الملفات المهمة

| الملف | الوظيفة |
|---|---|
| `app.py` | تعريفات FastAPI routes |
| `runner.py` | تشغيل الـ Pipeline وقراءة stdout |
| `jobs.py` | إدارة الـ jobs في الذاكرة + SQLite |
| `db.py` | طبقة SQLite |
| `stages.py` | تحويل markers الـ Pipeline لمراحل الواجهة |
| `firebase_service.py` | Firebase Admin SDK للمشروع الافتراضي |
| `traders_firebase_service.py` | Firebase Admin SDK لمشروع traders-data-live |
| `config.py` | الإعدادات والمسارات |

## Endpoints

| Method | Path | الوصف |
|---|---|---|
| `POST` | `/upload` | رفع الفيديو إلى `backend/uploads/` |
| `POST` | `/jobs` | إنشاء job جديد وتشغيل الـ Pipeline |
| `GET`  | `/jobs` | قائمة الـ jobs الأخيرة |
| `GET`  | `/jobs/{id}` | حالة job معينة |
| `GET`  | `/jobs/{id}/results` | النتائج النهائية |
| `GET`  | `/jobs/{id}/review` | عناصر المراجعة البشرية |
| `POST` | `/jobs/{id}/approve` | الموافقة على المراجعة ورفعها للـ Firebase الافتراضي |
| `POST` | `/jobs/{id}/traders/preview` | معاينة schema traders-data-live |
| `POST` | `/jobs/{id}/traders/push` | رفع البيانات لـ traders-data-live |
| `GET`  | `/jobs/{id}/export.csv` | تصدير CSV (UTF-8 BOM) |
| `GET`  | `/jobs/{id}/excel` | تحميل ملف Excel |
| `GET`  | `/jobs/{id}/sign/{filename}` | عرض صورة اللوحة الإعلانية |
| `DELETE` | `/jobs/{id}/video` | حذف ملف الفيديو |
| `WS`   | `/ws/progress/{id}` | تدفق التقدم الحي |

## كيف بيشتغل التقدم؟

الـ `runner.py` بيشغّل الـ Pipeline كـ subprocess ويقرأ stdout سطر سطر. لما يلاقي marker زي:

```text
--- STAGE 3: Smart frame filtering by speed ---
```

بيحول رقم المرحلة لـ UI stage index وبيبعت event عن طريق WebSocket.

## Pipeline Versions

الـ backend بيستخدم سلسلة fallback:

1. `stores_v6_final.json` — من `pipeline/run_v6.py`
2. `stores_v5_raw.json` — من `pipeline/main_v5.py`
3. `stores_raw.json` — من `pipeline/main.py`

## Persistence

الـ jobs بتتخزن في **SQLite** (`backend/state.db`)، مش في الذاكرة بس. لما الـ backend يقفل وهو شغال، الـ jobs بترجع بحالة `interrupted` وبتقدر تستأنفها من الواجهة.

## Firebase Setup

ضع مفاتيح Service Account في مجلد `backend/`:

```text
backend/
├── firebase_key.json              # المشروع الافتراضي
├── newdb_key.json                 # مشروع إضافي
└── traders_data_live_key.json     # مشروع traders-data-live
```

تأكد من صحة الإعداد من `/health`.

## Utilities

مجموعة من السكربتات المساعدة:

| السكربت | الوظيفة |
|---|---|
| `_batch_run.py` | تشغيل دفعة من الفيديوهات |
| `_snapshot_job.py` | عمل snapshot لـ job |
| `_resnapshot_job.py` | إعادة snapshot |
| `_restore_from_db.py` | استعادة jobs من قاعدة البيانات |
| `push_all_to_newdb.py` | رفع بيانات الـ job لـ newdb |
