# Connect Sentry Monitoring

Status: Approved
Owner: Store Extractor team
Type: Infrastructure

## Context

صاحبة المشروع تريد ربط Store Extractor بخدمة Sentry بحيث تُسجل أخطاء التشغيل الحقيقية ويصل تنبيه إلى بريدها عند حدوث خطأ. المشروع يعمل في أكثر من runtime: واجهة React على Vercel، وFastAPI محلي، وFirebase Functions في الإنتاج؛ لذلك ربط الواجهة وحدها لا يغطي أعطال التحليل أو الوظائف السحابية.

توجد تعديلات محلية سابقة تضيف `@sentry/react` و`Sentry.ErrorBoundary`، لكنها لم تُختبر ضد حساب Sentry، ولا تشمل Python، ولا تثبت وجود Email Alert.

## Current Behavior

- `frontend/package.json` المحلي المعدل يحتوي على `@sentry/react`.
- `frontend/src/main.jsx` المحلي المعدل يهيئ Sentry ويغلف التطبيق بـ`Sentry.ErrorBoundary`.
- DSN له fallback مكتوب مباشرة داخل `main.jsx` وموجود بقيمة حقيقية داخل `.env.example`، بينما `.env.development` لا يحتوي إعداد Sentry.
- لا يوجد `sentry-sdk` في `backend/requirements.txt` أو `functions/requirements.txt`.
- لا توجد تهيئة Sentry في FastAPI أو Firebase Functions/Cloud Tasks worker.
- لا توجد آلية اختبار آمنة وموثقة تثبت وصول event من التطبيق.
- لا يوجد دليل داخل المشروع على وجود Alert Rule فعالة ترسل Email، ولا دليل على وصول رسالة اختبار.
- إعدادات Alerts والبريد تقع داخل حساب Sentry وليست نتيجة تلقائية لإضافة SDK.

## Requirements

- ربط React frontend بـSentry فقط عند توفير `VITE_SENTRY_DSN`؛ لا يوجد DSN hardcoded كـfallback داخل source code.
- الاحتفاظ بـError Boundary عربية لا تسرب تفاصيل تقنية للمستخدم، مع تسجيل render errors في Sentry.
- التقاط أخطاء JavaScript غير المعالجة وunhandled promise rejections من الواجهة.
- ربط FastAPI المحلي وFirebase Functions/Cloud Tasks بـSentry Python SDK عند توفير `SENTRY_DSN`.
- تمييز الأحداث باستخدام environment وrelease/runtime tags حتى يمكن معرفة هل الخطأ من frontend أو local backend أو Firebase Functions.
- عدم إرسال PII افتراضيًا، وعدم إرفاق الفيديو أو محتوى الإطارات أو أرقام الهواتف أو service-account data أو tokens.
- توثيق متغيرات البيئة المطلوبة بقيم placeholder فقط داخل ملفات المثال.
- إضافة طريقة اختبار مقصودة وآمنة لا تُظهر زرًا عامًا للمستخدم ولا تترك endpoint إنتاجيًا مفتوحًا لرمي الأخطاء.
- إنشاء أو التحقق من Alert Rule داخل Sentry ترسل Email للمستخدم المحدد عند ظهور issue جديدة أو عودة issue سابقة، مع حد يمنع spam المتكرر.
- إرسال test event مميز يمكن البحث عنه، والتأكد أنه ظهر داخل مشروع Sentry.
- التأكد من وصول Email فعلي لهذا الاختبار؛ لا تُعتبر المهمة مكتملة بمجرد قبول Sentry للـevent.
- الحفاظ على تشغيل التطبيق طبيعيًا إذا لم تُضبط متغيرات Sentry أو تعذر الاتصال بالخدمة.

## Constraints

- DSN مفتاح ingest عام وليس service-account secret، لكن يُدار عبر environment variables لتفادي ربط الكود بمشروع Sentry واحد.
- `SENTRY_AUTH_TOKEN` — إذا استُخدم لرفع source maps أو إدارة Alerts — سر ممنوع من Git وfrontend bundle، ويُحفظ فقط في Sentry/Vercel/Firebase secrets أو جلسة محلية مؤقتة.
- لا تُسجل payloads الكاملة لطلبات API أو نتائج المتاجر أو بيانات المستخدمين.
- لا تُرسل أخطاء متوقعة مثل رفض validation العادي أو 404 المقصود كـissues حرجة بلا تمييز.
- لا تُفعّل أو تُنفذ أي كتابة إلى `traders-data-live` أثناء الربط أو الاختبار.
- تعديلات Sentry المحلية الموجودة تُعامل كعمل غير مكتمل لصاحبة المشروع: تُراجع وتُنظف ولا تُستبدل عشوائيًا.
- إعداد Email Alert يحتاج صلاحية مناسبة داخل Sentry ومستخدمًا له بريد مؤكد ومفعلة له إشعارات البريد.
- موصل Sentry تم تثبيته، لكن أدواته لا تزال تحتاج أن تصبح متاحة للجلسة قبل التحقق الخارجي المباشر.

## Acceptance Criteria

- frontend lint وproduction build ينجحان بعد التهيئة.
- Python import/compile checks تنجح للـbackend وFunctions مع Sentry SDK.
- لا توجد قيمة DSN حقيقية أو auth token في tracked source/example files؛ ملفات المثال تحتوي placeholders فقط.
- عند غياب DSN يبدأ frontend وFastAPI وFunctions دون فشل بسبب Sentry.
- test event من frontend يظهر في مشروع Sentry الصحيح مع tag يحدد `frontend` والـenvironment.
- test event من Python يظهر في مشروع Sentry الصحيح مع tag يحدد `local-backend` أو `firebase-functions`.
- خطأ React render تجريبي يُلتقط ويعرض fallback العربية بدل شاشة بيضاء.
- Alert Rule تكون enabled وتحتوي Email action للمستخدم/البريد المقصود، وتتعامل على الأقل مع `first_seen` و`regression/reappeared`.
- تصل رسالة Email فعلية بسبب test issue جديدة، وتُسجل صاحبة المشروع تأكيد الاستلام.
- لا تظهر في test events بيانات هاتف أو فيديو أو token أو service-account content.
- لا تتغير وظيفة التحليل أو الرفع أو المراجعة أو التصدير أو قاعدة traders بسبب الربط.

## Edge Cases

- مانع الإعلانات أو DNS/QUIC قد يمنع browser event؛ يجب أن يفشل الإرسال بهدوء ولا يعطل التطبيق، ويُختبر من شبكة تسمح بـSentry ingest.
- إذا كان test event مطابقًا issue قديمة فلن يشغل شرط `first_seen`؛ يجب استخدام اسم/معرف فريد للاختبار أو إعادة فتح مناسبة.
- وصول الحدث لا يضمن وصول البريد إذا كانت notification settings للمستخدم معطلة أو الرسالة في Spam؛ يجب فحص الجانبين.
- React Error Boundary لا يلتقط كل أخطاء event handlers؛ تعتمد الأخطاء غير المعالجة على integrations الافتراضية، والأخطاء التي يمسكها التطبيق عمدًا تحتاج `captureException` انتقائيًا عند كونها غير متوقعة.
- أخطاء subprocess الخاصة بالـpipeline قد تتحول إلى job status بدل exception؛ ينبغي تسجيل الفشل غير المتوقع مع `job_id` آمن دون نتائج أو PII.
- إذا استُخدم مشروع Sentry واحد لكل runtimes، يجب فصلها بالـtags؛ وإذا اختيرت مشاريع منفصلة، يلزم DSN مستقل لكل runtime وقاعدة Alert تغطيها.

## Out of Scope

- تفعيل Session Replay أو تسجيل شاشة المستخدم.
- إرسال ملفات الفيديو أو الصور أو نتائج المتاجر كمرفقات إلى Sentry.
- تحويل كل رسائل logs إلى Sentry أو شراء خطة مدفوعة.
- بناء dashboard مخصص أو تكامل Slack/PagerDuty.
- إصلاح كل الأخطاء التي قد يكشفها Sentry بعد الربط.
- تعديل منطق Gemini/OCR/Google Places أو pipeline.
- تفعيل الكتابة إلى قاعدة بيانات traders.
