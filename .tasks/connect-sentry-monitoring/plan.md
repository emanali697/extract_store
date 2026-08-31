# Plan — Connect Sentry Monitoring

Status: Approved
Spec: `.tasks/connect-sentry-monitoring/spec.md`

## Approach

إنشاء تهيئة Sentry صغيرة ومشتركة لكل Python runtime، وتنظيف تهيئة React الحالية لتكون environment-driven، ثم إضافة test utilities لا تدخل production UI. نتحقق على ثلاث طبقات مستقلة: صحة build/import، قبول Sentry للأحداث، ثم تشغيل Email Alert ووصول الرسالة. لا تُستخدم صلاحيات كتابة Alerts داخل الكود أو Git؛ إعداد البريد يتم من لوحة Sentry بحساب صاحبة المشروع.

## Impact Analysis

- Runtime: عند وجود DSN تُرسل الأخطاء غير المتوقعة إلى Sentry؛ عند غيابه يبقى السلوك كما هو.
- Frontend: مراجعة `Sentry.init` وError Boundary، وإزالة DSN الحقيقي من source/example، وإضافة release/runtime tags وفلترة الخصوصية.
- Backend/Functions: إضافة `sentry-sdk` وتهيئة مبكرة لـFastAPI وFirebase Functions، والتقاط فشل pipeline الذي يتحول إلى job error ولا يُرفع كاستثناء.
- Data and migrations: لا schema أو migration ولا كتابة Firestore إضافية.
- Deployment: إضافة environment variables إلى Vercel وFirebase Functions، ثم إعادة نشر كل runtime متأثر. local backend يستخدم `backend/.env` غير المتتبع.
- Secrets: DSN ingest يُدار كإعداد runtime؛ `SENTRY_AUTH_TOKEN` للقراءة/فحص API فقط ويظل خارج المشروع. Source-map auth token مؤجل إذا لم يتم اعتماد source maps ضمن التنفيذ.
- Alerts: Email Alert تُضبط في Sentry UI للمشروع والمستخدم المقصود، ثم تُختبر بـissue فريدة.
- Traders: لا تغيير ولا كتابة إلى `traders-data-live`.

## Steps

1. تحديد Sentry organization/project والبيئة والبريد المستلم، وضبط `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, و`SENTRY_PROJECT` محليًا بصلاحيات قراءة فقط للتحقق لاحقًا.
2. نقل تهيئة React إلى module مخصص، وإزالة DSN hardcoded، وضبط privacy filtering وruntime/environment/release tags.
3. إبقاء Error Boundary العربية وإضافة `onError`/capture metadata الآمنة عند الحاجة، من دون عرض تفاصيل تقنية.
4. إضافة اختبار frontend غير متاح في production افتراضيًا، مثل query flag يعمل فقط في development أو وظيفة اختبار منفصلة، لإنتاج issue فريدة والتحقق من fallback.
5. إضافة `sentry-sdk[fastapi]` إلى متطلبات Python وmodule تهيئة مشترك في `backend/` ونسخة مقابلة في `functions/` وفق flat structure الحالية.
6. تهيئة Sentry قبل إنشاء FastAPI app وقبل تعريف Firebase Functions، مع tags تفصل `local-backend` و`firebase-functions`/worker.
7. التقاط فشل pipeline النهائي المتوقع أن يكون مهمًا تشغيليًا كرسالة/exception منظمة مع `job_id` فقط، من دون video path أو store payloads، وتجنب تكرار report لنفس الفشل.
8. تحديث ملفات `.env.example` بقيم placeholders وتعليمات Vercel/Firebase/local، وإضافة ملفات token المحتملة إلى `.gitignore`.
9. إضافة اختبارات unit خفيفة لتهيئة disabled mode وprivacy filter إن أمكن من دون اتصال خارجي، ثم تشغيل lint/build وPython compile/import checks.
10. ضبط DSN الحقيقي في local/Vercel/Firebase خارج Git، ثم نشر frontend وFunctions إذا وافقت صاحبة المشروع على النشر.
11. إرسال issue اختبار فريدة من frontend وأخرى من Python، واستخدام أداة Sentry read-only للتحقق من project/environment/runtime tags وعدم وجود PII.
12. داخل Sentry UI، إنشاء/مراجعة Alert Rule مفعلة: first seen وregression/reappeared → Email للمستخدم المقصود، مع frequency تمنع spam.
13. إرسال issue جديدة بعد تفعيل Alert، انتظار البريد، وطلب تأكيد صاحبة المشروع على الاستلام وفحص Spam عند الحاجة.
14. تسجيل event IDs المنقحة ونتيجة البريد في `check.md`، ثم إكمال المهمة فقط بعد تحقق جميع المعايير.

## Files to Change

Create:

- `frontend/src/services/sentry.js`
- `frontend/src/components/SentryDevelopmentTest.jsx`
- `backend/sentry_setup.py`
- `functions/sentry_setup.py`
- اختبارات Sentry المناسبة حسب بنية الاختبارات التي ستُضاف
- `.tasks/connect-sentry-monitoring/check.md`

Modify:

- `frontend/src/main.jsx`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/.env.example`
- `backend/app.py`
- `backend/runner.py`
- `backend/requirements.txt`
- `backend/.env.example`
- `functions/main.py`
- `functions/runner.py`
- `functions/requirements.txt`
- `functions/.env.example`
- `.gitignore`
- `DEPLOY.md`
- `CHANGELOG.md`
- `.tasks/connect-sentry-monitoring/spec.md`
- `.tasks/connect-sentry-monitoring/plan.md`

Delete:

- none

## Tests

- `npm run lint --prefix frontend`
- `npm run build --prefix frontend`
- `python -m compileall -q backend functions`
- Python tests الخاصة بـdisabled init وevent scrubbing.
- بدء frontend وFastAPI بدون أي DSN والتأكد من عدم فشلهما.
- إرسال frontend test issue فريدة والتحقق منها عبر Sentry API read-only.
- إرسال Python test issue فريدة والتحقق منها عبر Sentry API read-only.
- فحص event metadata بعد إخفاء emails/IP/phone/video paths/tokens.
- اختبار React Error Boundary في development والتأكد من ظهور fallback العربية.
- فحص Alert Rule من لوحة Sentry والتأكد أنها Enabled وبها Email action.
- اختبار وصول رسالة Email فعلية وتسجيل تأكيد المستخدم.
- `python scripts/sdd_check.py --all`

## Rollback Plan

إزالة calls الخاصة بتهيئة Sentry وdependencies الجديدة، وإزالة متغيرات Sentry من Vercel/Firebase/local environments، ثم إعادة نشر frontend/Functions. تعطيل Alert Rule من Sentry UI. لا توجد بيانات تطبيق أو migrations للتراجع عنها، وتظل issues التاريخية في Sentry إلى أن يحذفها مالك الحساب يدويًا.

## Risks

- لا يمكن ضمان Email من الكود: notification preferences والبريد المؤكد وSpam وسياسات Sentry عوامل خارجية، ولذلك تأكيد الاستلام شرط إغلاق.
- مهارة Sentry قراءة فقط وتحتاج token محليًا؛ إدارة Alert عبر UI أكثر أمانًا من تخزين token بصلاحية كتابة.
- الأخطاء التي يمسكها التطبيق ويحوّلها إلى status قد لا تصل تلقائيًا؛ يلزم capture انتقائي لتجنب الضوضاء.
- source maps تحسن stack traces لكنها تحتاج auth token سري في Vercel؛ يمكن تنفيذها في نفس المهمة فقط إذا توفرت org/project/token وإلا تُسجل كتحسين لاحق ولا تمنع التقاط الأخطاء.
- نشر Firebase Functions يغيّر بيئة إنتاج ويحتاج موافقة صريحة وقت النشر حتى لو كان الكود جاهزًا.
- تعديلات Sentry المحلية الحالية تتداخل مع ملفات frontend معدلة قبل المهمة؛ يجب مراجعة diff وstaging بعناية حتى لا تضيع أو تدخل تغييرات غير مرتبطة.
