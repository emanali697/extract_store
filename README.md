# دليل استخدام Store Extractor

> تطوير المشروع يتبع الآن **Specification-Driven Development**. قبل أي feature أو bug fix أو refactor، ابدأ من [SDD.md](SDD.md) وأنشئ مهمة داخل `.tasks/`.

تطبيق ويب لاستخراج بيانات المتاجر والمحلات من فيديوهات كاميرا السيارة (Dashcam).

## المقدمة

**Store Extractor** بيعالج فيديوهات الكاميرا ويستخرج منها معلومات منظمة عن المتاجر اللي ظهرت في الفيديو، زي:

- اسم المتجر
- رقم التليفون
- التصنيف (مطعم، صيدلية، محل ملابس، إلخ)
- الموقع والإحداثيات الجغرافية
- حالة التشغيل (نشط / مقفول / غير مؤكد)
- صورة اللوحة الإعلانية (Sign)

التطبيق بيتكون من جزئين:

1. **Backend** باستخدام FastAPI (Python): بيستقبل الفيديو، يشغّل الـ Pipeline، ويرجع النتائج.
2. **Frontend** باستخدام React + Vite: واجهة المستخدم بالعربية وبتدعم RTL.

> **ملاحظة:** الـ Pipeline نفسه (ML processing) مش موجود في الريبو ده، لازم يكون في مجلد شقيق اسمه `../pipeline/`.

---

## المتطلبات الأساسية

قبل ما تبدأ، لازم يكون عندك:

- **Python 3.12** أو أحدث
- **Node.js 18+** و **npm**
- **Git** (اختياري)
- **Pipeline folder** موجود في المسار الصحيح (`../pipeline/main.py`)
- **مفاتيح Firebase** لو عايز ترفع البيانات للسحابة (اختياري)

---

## هيكل المشروع

```text
extract stores/
├── backend/               # FastAPI + SQLite + Firebase services
│   ├── app.py
│   ├── runner.py
│   ├── requirements.txt
│   ├── uploads/           # الفيديوهات المرفوعة
│   └── jobs/              # نتائج معالجة كل job
├── frontend/              # React + Vite + Bootstrap RTL
│   ├── src/
│   ├── package.json
│   └── .env.development
└── ../pipeline/           # الـ ML pipeline (مش موجود هنا)
```

---

## خطوات التشغيل السريعة

### 1. تجهيز البيئة

افتح PowerShell وروح لمجلد المشروع:

```powershell
cd "d:/sharea elnassim/extract stores"
```

### 2. تشغيل الـ Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

لو التثبيت نجح، هتلاقي السيرفر شغال على:

```text
http://localhost:8000
```

وصفحات API docs متاحة على:

```text
http://localhost:8000/docs
```

### 3. تشغيل الـ Frontend

افتح PowerShell تاني (سيب الـ Backend شغال):

```powershell
cd "d:/sharea elnassim/extract stores/frontend"
npm install
npm run dev
```

الواجهة هتكون متاحة على:

```text
http://localhost:5173
```

---

## دليل الاستخدام خطوة بخطوة

### 1. رفع الفيديو

- افتح الرابط: <http://localhost:5173>
- هتتوجه تلقائيًا لصفحة الرفع.
- اضغط **اختر ملف الفيديو** واختار الفيديو من جهازك.
- الفيديو ممكن يكون أي صيغة شائعة (MP4, MOV, AVI, إلخ).

### 2. إعدادات التحليل

بعد الرفع، هتظهر لك Sidebar على اليمين فيها إعدادات التحليل:

| الإعداد | الوصف |
|---|---|
| **عدد الإطارات المستهدف** | عدد الإطارات اللي الـ Pipeline هيحللها من الفيديو |
| **سرعة البدء** | السرعة اللي الـ Pipeline يبدأ منها تحليل الإطارات |
| **مستوى الثقة** | الحد الأدنى لقبول نتيجة المتجر |
| **نطاق البحث الجغرافي** | نصف قطر البحث عن المكان في Google Places |
| **تفعيل المراجعة التلقائية** | يسمح للنظام يقرر المتاجر اللي محتاجة مراجعة بشرية |

بعد ما تظبط الإعدادات، اضغط **ابدأ التحليل**.

### 3. متابعة التقدم

هتتنقل لصفحة **التقدم** فيها:

- شريط التقدم العام.
- قائمة المراحل التسعة:
  1. استخراج الإطارات
  2. قراءة بيانات GPS والسرعة
  3. فلترة الإطارات الذكية
  4. تحليل الإطارات بـ Gemini
  5. مطابقة Google Places
  6. فحص حالة التشغيل
  7. مراجعة تلقائية
  8. تصدير Excel
  9. انتهاء المعالجة
- سجل الأحداث (Log) بيظهر live.

### 4. المراجعة البشرية

لو فيه متاجر محتاجة مراجعة، هتتنقل لصفحة **المراجعة** فيها:

- صورة اللوحة الإعلانية.
- اسم المتجر المقترح.
- بيانات Google Places المتشابهة.
- أزرار:
  - **موافق** ✅
  - **رفض** ❌
  - **تعديل** ✏️ (تعديل الاسم أو الفئة أو رقم التليفون)

### 5. نتائج التحليل

بعد الانتهاء والموافقة على المراجعات، هتروح لصفحة **النتائج** فيها:

- جدول بكل المتاجر المستخرجة.
- حالة كل متجر:
  - `✅ نشط`
  - `🚫 مقفول`
  - `⚠️ غير مؤكد`
  - `⚪ يحتاج تحقق`
- أزرار التصدير:
  - **CSV** (UTF-8 with BOM لـ Excel)
  - **Excel**
  - **Push to Firebase** (لو المفاتيح متاحة)

---

## إعداد Firebase (اختياري)

لو عايز ترفع البيانات لـ Firebase، لازم تضع ملفات مفاتيح Service Account في مجلد `backend/`:

```text
backend/
├── firebase_key.json              # المشروع الافتراضي (store-extract)
├── newdb_key.json                 # مشروع إضافي
└── traders_data_live_key.json     # مشروع traders-data-live
```

### الحصول على مفتاح Service Account

1. ادخل [Firebase Console](https://console.firebase.google.com/).
2. اختار مشروعك.
3. اذهب إلى **Project Settings** ⚙️.
4. افتح تبويب **Service Accounts**.
5. اضغط **Generate new private key**.
6. حمّل الـ JSON وضعه في `backend/` بالاسم المناسب.

### التأكد من صحة الإعداد

افتح في المتصفح:

```text
http://localhost:8000/health
```

لازم يرجّع حالة Firebase و traders-data-live.

---

## إعداد Pipeline

الـ Backend بيدور تلقائيًا على مجلد `pipeline/` في أحد الأبواب لحد 4 مستويات فوق `backend/`. الملفات المتوقعة:

```text
../pipeline/
├── main.py              # v3: استخراج أولي
├── main_v5.py           # v5: مطابقة Google Places
└── run_v6.py            # v6: فحص الحالة + مراجعة تلقائية + Excel
```

لو الـ Pipeline مش موجود، هتظهر رسالة خطأ واضحة في الواجهة.

---

## أهم REST Endpoints

| Method | Path | الوصف |
|---|---|---|
| `POST` | `/upload` | رفع الفيديو |
| `POST` | `/jobs` | إنشاء job وتشغيل التحليل |
| `GET`  | `/jobs` | قائمة الـ jobs |
| `GET`  | `/jobs/{id}` | حالة job معينة |
| `GET`  | `/jobs/{id}/results` | النتائج النهائية |
| `GET`  | `/jobs/{id}/review` | عناصر المراجعة البشرية |
| `POST` | `/jobs/{id}/approve` | الموافقة على المراجعة ورفعها |
| `POST` | `/jobs/{id}/traders/preview` | معاينة schema traders-data-live |
| `POST` | `/jobs/{id}/traders/push` | رفع لـ traders-data-live |
| `GET`  | `/jobs/{id}/export.csv` | تصدير CSV |
| `GET`  | `/jobs/{id}/excel` | تحميل ملف Excel |
| `WS`   | `/ws/progress/{id}` | تدفق التقدم الحي |

---

## حل المشاكل الشائعة

### 1. Frontend مش بيقدر يوصل للـ Backend

تأكد إن:

- الـ Backend شغال فعلًا على `http://localhost:8000`.
- ملف `frontend/.env.development` فيه:

  ```text
  VITE_API_BASE_URL=http://localhost:8000
  ```

### 2. Pipeline مش متلاقي

تأكد إن مجلد `pipeline/` موجود في مسار شقيق للمشروع، زي:

```text
d:/sharea elnassim/pipeline/
```

ولازم يحتوي على `main.py` على الأقل.

### 3. Firebase push بيفشل

- تأكد من وجود ملف `firebase_key.json`.
- تأكد إن المفتاح صالح ولم يتم إبطاله من Firebase Console.
- افتح `/health` وشوف حالة Firebase.

### 4. Excel/CSV فيه حروف مشوهة

ملفات CSV بتتصدّر بـ **UTF-8 BOM** عشان تتفتح صح في Excel. لو ظهرت الحروف العربية غلط، افتح Excel واختار:

```text
Data → Get Data → From File → From Text/CSV
```

واختار الترميز **UTF-8**.

### 5. Job اتحذف بعد ما قفلت الـ Backend

الـ Backend حاليًا بيستخدم **SQLite** (`backend/state.db`) لتخزين الـ jobs. يعني مش بتتمسح. بس لو ظهرت رسالة استئناف، استخدم زر **استئناف العملية السابقة** في الواجهة.

---

## التشغيل في وضع الإنتاج

المشروع مفيهوش إعدادات إنتاج جاهزة. لو عايز ترفعه لإنتاج، لازم:

1. استخدم **Gunicorn + Uvicorn** بدلاً من `uvicorn --reload`.
2. حط الـ Service Account Keys في متغيرات بيئة أو Secret Manager.
3. استخدم قاعدة بيانات حقيقية بدل SQLite.
4. جهّز الـ Pipeline في Docker image أو خادم منفصل.
5. شغّل Frontend على Nginx أو CDN.

---

## المساهمة

لو عايز تضيف ميزة أو تصلح مشكلة:

1. افتح `AGENTS.md` الأول عشان تعرف قواعد المشروع.
2. اتبع نفس style الموجود.
3. جرب التغييرات محليًا قبل ما ترفعها.

---

## ملاحظات أمان

- **لا ترفع ملفات مفاتيح Firebase لـ Git.**
- متأكد إن `.gitignore` بيستبعد:

  ```text
  *_key.json
  *.db
  uploads/
  jobs/
  __pycache__/
  node_modules/
  dist/
  ```

---

## الدعم

لو واجهت أي مشكلة، افتح أدوات المطور في المتصفح (F12) وشوف:

- تبويب **Console** للأخطاء في Frontend.
- تبويب **Network** لطلبات API.
- سطر أوامر الـ Backend للأخطاء في Python.

---

**تمت كتابة هذا الدليل بتاريخ:** 2026-07-16
