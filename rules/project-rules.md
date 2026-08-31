# Store Extractor Project Rules

هذه القواعد مكيّفة مع البنية الفعلية للمشروع، وتستبدل افتراضات Node/AWS الموجودة في القالب المصدر.

## Architecture

- Frontend: React 19 + Vite، Zustand للحالة، Axios داخل `frontend/src/services/`، وBootstrap RTL.
- Local backend: FastAPI في `backend/` مع SQLite وWebSocket.
- Cloud backend: Firebase Functions Python في `functions/` مع Firestore وStorage وCloud Tasks.
- Production frontend: Vercel.
- لا تنقل المشروع إلى framework أو cloud مختلف داخل مهمة feature عادية.

## Upload and Analysis Contract

- رفع الفيديو يكتمل أولًا، ثم يبدأ التحليل كعملية منفصلة.
- لا تُظهر المهمة `done` قبل حفظ النتائج canonical أو خطأ صريح قابل للفهم.
- الفيديوهات الكبيرة قد تستخدم multipart parallel upload؛ فشل جزء واحد لا يجوز أن يبدأ pipeline ناقصًا.
- حذف الفيديو بعد المعالجة يجب ألا يحذف results أو review decisions أو exports.

## Progress Contract

- محليًا: WebSocket `/ws/progress/{job_id}` هو المسار المباشر مع REST snapshot للاستعادة.
- Firebase: Firestore snapshots هي المسار المباشر مع polling fallback؛ لا تفترض دعم WebSocket داخل Functions.
- أي مرحلة backend جديدة أو معاد تسميتها يجب مزامنتها مع `frontend/src/data/stages.js` ومسارات الاستعادة.

## Result and Review Contract

- fallback لقراءة النتائج هو `v6 > v5 > v3` ما لم يغيّره spec صريح مع migration plan.
- تعديل المراجعة يحدّث المصدر canonical للنتائج، وليس نسخة UI مؤقتة فقط.
- ResultsPage وCSV وExcel وFirebase approval يجب أن تقرأ النتائج المراجعة نفسها.
- المتجر الناتج يجب أن يكون ظاهرًا في الفيديو؛ Google Places مصدر إثراء/مطابقة وليس مصدرًا لإضافة متجر غير مرئي.
- dedupe يحافظ على الدليل الأصلي ويرسل الحالات غير الحاسمة للمراجعة اليدوية بدل حذفها بلا أثر.

## Traders Safety

- الكتابة إلى `traders-data-live` معطلة افتراضيًا.
- لا تغيّر `TRADERS_WRITES_ENABLED` إلى true ولا تستدعِ push فعليًا إلا بطلب صريح ومهمة SDD مستقلة.
- يلزم تفعيل backend guard وfrontend guard معًا بعد الموافقة؛ preview يبقى read/transform only.
- الاختبارات الافتراضية تستخدم dry-run أو mocks ولا تكتب إلى أي مشروع traders.

## Python

- استخدم `from __future__ import annotations` في modules الجديدة.
- استخدم type hints بصيغة Python الحديثة، وحافظ على flat structure الموجودة في backend.
- persistence failure لا يجوز أن يسقط pipeline بلا محاولة تسجيل الحالة.
- لا تشغل أكثر من Uvicorn worker واحد على SQLite المحلية.

## React

- لا semicolons، واستخدم single quotes و2-space indentation.
- المكونات Functional Components؛ Zustand للحالة المشتركة وhooks للحالة المحلية.
- API/Firebase calls تكون في `services/` وليست داخل pages مباشرة.
- حافظ على RTL وطبقة `.num-ltr` للأرقام والإنجليزية داخل النص العربي.

## Firebase and Secrets

- لا تكرر Firebase initialization خارج modules الحالية.
- Firebase web config غير سري بطبيعته، لكن service-account JSON وAPI secrets ممنوعة من Git.
- قواعد Firestore وStorage وCORS تُعامل كتغييرات سلوكية وتحتاج test plan ونشرًا موثقًا.
- Functions تستخدم `/tmp` فقط للملفات المؤقتة، ولا تعتمد على filesystem دائم.

## Required Checks by Change Type

- SDD docs: `python scripts/sdd_check.py --all`.
- Python: compile checks واختبارات الوحدة/التكامل الموجودة أو المضافة.
- Frontend: `npm run lint --prefix frontend` و`npm run build --prefix frontend`.
- Upload/pipeline/progress/review: اختبار يدوي end-to-end يسجل job ID والبيئة والنتيجة دون أسرار.
- Firebase rules/deployment: emulator أو بيئة test عند الإمكان، ثم smoke test بعد النشر.
