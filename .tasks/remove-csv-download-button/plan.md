# Plan — Remove CSV Download Button

Status: Complete
Spec: `.tasks/remove-csv-download-button/spec.md`

## Approach

تبسيط جزء التنزيل في صفحة النتائج ليخدم Excel فقط: إزالة عنصر زر CSV، وحذف `downloadCsvUrl` من imports، وتحويل handler العام الذي يختار بين Excel وCSV إلى handler مباشر لتنزيل Excel. تظل endpoints الخلفية كما هي لضمان التوافق.

## Impact Analysis

- Runtime: يختفي خيار CSV من واجهة النتائج فقط.
- Frontend: تعديل مكوّن `ResultsPage` وتنظيف الكود غير المستخدم المرتبط بالزر.
- Backend/Functions: لا تغيير؛ endpoints الخاصة بـCSV تظل متاحة.
- Data and migrations: لا توجد كتابة بيانات أو migration.
- Deployment: يحتاج التغيير build ونشر frontend على Vercel بعد الدمج؛ لا يحتاج نشر Firebase Functions.
- Traders: لا تفعيل ولا استدعاء كتابة إلى `traders-data-live`.

## Steps

1. إزالة `downloadCsvUrl` من import خدمات API في صفحة النتائج.
2. تعديل `handleDownload` ليجهز رابط Excel مباشرة بدل استقبال نوع الملف.
3. تعديل زر Excel ليستدعي handler المباشر.
4. حذف markup زر **CSV للبرنامج الآخر** والـspinner الخاص به.
5. التأكد بالبحث أن `ResultsPage.jsx` لا يحتوي على نص الزر أو استدعاء CSV.
6. تشغيل lint وproduction build وفحص SDD.
7. تسجيل النتائج الفعلية في `check.md` وإكمال حالات مستندات المهمة عند النجاح.

## Files to Change

Create:

- `.tasks/remove-csv-download-button/check.md`

Modify:

- `.tasks/remove-csv-download-button/spec.md`
- `.tasks/remove-csv-download-button/plan.md`
- `frontend/src/pages/ResultsPage.jsx`
- `CHANGELOG.md`

Delete:

- none

## Tests

- `rg -n "CSV للبرنامج الآخر|downloadCsvUrl|handleDownload\('csv'\)" frontend/src/pages/ResultsPage.jsx`
- `npm run lint --prefix frontend`
- `npm run build --prefix frontend`
- `python scripts/sdd_check.py --all`
- فحص يدوي لصفحة النتائج: زر CSV غير موجود، وزر Excel موجود ويبدأ التنزيل كما كان.

## Rollback Plan

إرجاع تعديل `ResultsPage.jsx` وإعادة import وزر ومسار CSV. لا توجد بيانات أو بنية خلفية تحتاج rollback.

## Risks

- قد يعتمد مستخدم على زر CSV الحالي؛ إبقاء endpoint الخلفي يقلل أثر التراجع ويسمح بإعادة الزر بسهولة.
- ملفات frontend محلية أخرى معدلة مسبقًا؛ يجب staging للملف المقصود ومستندات المهمة فقط وعدم ضم التعديلات الأخرى.
- لا توجد اختبارات UI آلية بالمشروع، لذلك يلزم build وفحص يدوي للزرين.
