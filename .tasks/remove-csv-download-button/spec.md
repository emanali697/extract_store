# Remove CSV Download Button

Status: Complete
Owner: Store Extractor team
Type: Feature

## Context

صفحة النتائج تعرض حاليًا زرًا باسم **CSV للبرنامج الآخر** بجانب زر تحميل Excel. صاحبة المشروع لا تريد إتاحة تصدير CSV من واجهة المستخدم، وتريد أن يظل Excel هو خيار تنزيل النتائج الظاهر.

## Current Behavior

- تعرض `frontend/src/pages/ResultsPage.jsx` زرين داخل بطاقة تحميل النتائج: Excel وCSV.
- زر CSV يستدعي `handleDownload('csv')`، والذي يستخدم `downloadCsvUrl(jobId)`.
- توجد endpoints لتصدير CSV في FastAPI المحلي وFirebase Functions.
- زر Excel الحالي ينزّل النتائج المحدثة بعد المراجعة ويجب الحفاظ عليه.

## Requirements

- إزالة زر **CSV للبرنامج الآخر** من صفحة النتائج.
- إزالة كود frontend الذي يصبح غير مستخدم بسبب حذف الزر، بما في ذلك import أو branch خاص بـCSV إذا لم يعد له مستهلك.
- إبقاء زر Excel ظاهرًا ويعمل بنفس السلوك الحالي.
- عدم تغيير عرض النتائج أو المراجعة أو الرفع إلى Firebase أو إعدادات traders.
- تطبيق السلوك نفسه عند تشغيل الواجهة محليًا أو من Vercel.

## Constraints

- التعديل داخل frontend فقط.
- لا تُحذف endpoints الخاصة بـCSV من `backend/` أو `functions/` في هذه المهمة، حفاظًا على التوافق مع أي مستهلك خارجي غير ظاهر في الواجهة.
- لا تُعدّل ملفات البيئة أو dependencies أو تعديلات frontend المحلية غير المرتبطة الموجودة حاليًا.
- لا يتم تفعيل أو تنفيذ أي كتابة إلى `traders-data-live`.

## Acceptance Criteria

- لا يظهر زر أو نص **CSV للبرنامج الآخر** في صفحة النتائج.
- لا تستورد صفحة النتائج `downloadCsvUrl` ولا تحتوي على مسار تنزيل CSV غير مستخدم.
- يظل زر **Excel كامل (v6)** ظاهرًا وقابلًا للتشغيل، مع spinner ورسالة الخطأ الحالية.
- ينجح `npm run lint --prefix frontend`.
- ينجح `npm run build --prefix frontend`.
- تنجح `python scripts/sdd_check.py --all` بعد اكتمال مستندات المهمة.
- لا تتغير ملفات backend أو Functions أو Firebase rules ضمن هذه المهمة.

## Edge Cases

- عند عدم وجود نتائج، يستمر سلوك صفحة النتائج الحالي بلا تغيير.
- أثناء تجهيز ملف Excel، يظل منع الضغط المتكرر ورسالة الخطأ يعملان كما هما.
- بقاء endpoint CSV متاحًا لا يعني ظهوره للمستخدم؛ المطلوب هو إزالة الوصول إليه من واجهة البرنامج فقط.

## Out of Scope

- حذف أو تعطيل CSV API في FastAPI أو Firebase Functions.
- تغيير أعمدة أو تنسيق ملف Excel.
- تعديل نتائج التحليل أو المراجعة أو إزالة التكرار.
- تغيير أزرار Firebase أو traders أو حذف الفيديو.
- نشر Firebase Functions أو تعديل قاعدة بيانات.
