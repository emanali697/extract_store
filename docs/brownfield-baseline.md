# Store Extractor Brownfield Baseline

Last reviewed: 2026-08-12

هذا المستند يثبت نقطة البداية قبل تغييرات SDD اللاحقة. عند التعارض، الكود الحالي و`AGENTS.md` وملفات النشر هي الأدلة التنفيذية، ويجب تحديث هذا المستند داخل المهمة التي تغيّر المعمارية.

## System Boundary

- `frontend/`: React 19 + Vite + Zustand + Bootstrap RTL، منشور على Vercel.
- `backend/`: FastAPI + SQLite + WebSocket للتشغيل المحلي.
- `functions/`: Firebase Functions Python 2nd gen وFirestore وCloud Storage وCloud Tasks للإنتاج.
- `functions/pipeline/`: نسخة pipeline المعبأة مع Functions للإنتاج.
- `../pipeline/`: pipeline خارجي يكتشفه backend المحلي.

## Current User Flow

1. الواجهة تنشئ job.
2. الفيديو يرفع أولًا؛ الملفات الكبيرة تستخدم أجزاء متوازية إلى Firebase Storage.
3. يبدأ التحليل بعد نجاح الرفع.
4. محليًا يصل التقدم عبر WebSocket، وفي Firebase يصل عبر Firestore snapshots مع fallback polling.
5. pipeline يستخرج الإطارات ويحلل اللوحات ويطابق Google Places ويحدد الحالة ويزيل التكرار.
6. النتائج الأكثر اكتمالًا تُفضّل بالترتيب `v6 > v5 > v3`.
7. تعديلات المراجعة تُحفظ في النتائج canonical، وصفحة النتائج وExcel يجب أن تقرآ النسخة المراجعة.
8. الفيديو السحابي يُحذف بعد محاولة التحليل النهائية، بينما تبقى النتائج اللازمة.

## Data Stores

- Local jobs: memory + `backend/state.db`، مع outputs في `backend/jobs/`.
- Cloud jobs/progress/results: Firestore.
- Cloud uploads and generated artifacts: Firebase Storage.
- Default app store destination: مشروع `store-extract` عند الموافقة.
- `traders-data-live`: تكامل موجود لكن الكتابة معطلة افتراضيًا بواسطة `TRADERS_WRITES_ENABLED=false` وبواسطة مفتاح الواجهة المقابل. المعاينة لا تكتب بيانات.

## Deployment Constraints

- Firebase Functions لا تدعم WebSocket المستمر؛ الإنتاج يعتمد Firestore للمراحل.
- Cloud Tasks worker له deadline مقداره 30 دقيقة وذاكرة 4 GB حسب إعداد النشر الحالي.
- مفاتيح service account وملفات `.env` ليست جزءًا من Git ويجب توفيرها خارج المستودع أو عبر Firebase secrets.
- SQLite لا يُشغل بعدة Uvicorn workers.
- إعدادات CORS وStorage rules جزء من صحة الرفع من رابط Vercel.

## High-Risk Change Areas

- فصل إنشاء job ورفع الفيديو وبدء التحليل.
- اتساق status/stages بين WebSocket وFirestore وpolling.
- مزامنة مراجعة المتجر مع النتائج والتصدير الدائم.
- اختيار ملف النتائج الصحيح عبر fallback chain.
- حذف الفيديو بعد المعالجة دون حذف نتائج المهمة.
- deduplication للأسماء العربية المتشابهة دون دمج متجرين حقيقيين.
- أي مسار قد يكتب إلى مشروع traders.

## Current Verification Baseline

لا توجد حزمة اختبارات تطبيق آلية شاملة حتى تاريخ المراجعة. الحد الأدنى الحالي لأي تغيير سلوكي هو:

- Python syntax/compile checks للأجزاء المتأثرة.
- frontend lint وbuild للتغييرات الأمامية.
- اختبار يدوي للتدفق المتأثر محليًا أو في بيئة Firebase مناسبة.
- فحص SDD الآلي.

كل مهمة جديدة يجب أن تضيف regression test عندما يكون ذلك عمليًا، أو تسجل بوضوح سبب الاعتماد على اختبار يدوي.
