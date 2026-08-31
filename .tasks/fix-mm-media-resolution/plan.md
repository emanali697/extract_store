# Plan — Fix Multimodal Verification media_resolution 400 on Multi-Image Requests

Status: Complete
Spec: `.tasks/fix-mm-media-resolution/spec.md`

## Approach

إصلاح موضعي داخل `_multimodal_one` في `functions/pipeline/auto_review.py` بمسارين متكاملين:

1. **منع استباقي**: حساب عدد صور الدليل في الطلب (`(len(parts) - 1) // 2` لأن أول Part هو البرومبت ثم زوج نص+صورة لكل دليل)، وتفعيل `MEDIA_RESOLUTION_HIGH` فقط عندما يكون العدد 1 — مطابقًا لقيد Vertex الموثق في رسالة الخطأ.
2. **fallback دفاعي**: داخل حلقة المحاولات، أي `INVALID_ARGUMENT` نصه يتضمن `media resolution` يؤدي إلى إزالة الإعداد من `cfg` (`cfg.pop`) وإعادة المحاولة فورًا بدونه — يحمي من قيود مستقبلية أخرى لنماذج مختلفة دون إسقاط الطلب.

## Impact Analysis

- Runtime: يعيد تشغيل مرحلة 13B التي كانت تنهار دائمًا؛ لا تغيير في النتائج المتوقعة لأن الطلب كان سيفشل بالكامل لولا الإصلاح.
- Frontend: لا تغيير.
- Backend/Functions: ملف واحد فقط.
- Data and migrations: لا شيء.
- Deployment: ينشر مع `functions/` كالمعتاد؛ لا متغيرات بيئة.

## Steps

1. تعديل منطق تفعيل `media_resolution` ليعتمد على عدد صور الدليل.
2. إضافة فرع الـfallback داخل `except` العام في حلقة المحاولات.
3. py_compile + تشغيل اختبارات `test_accuracy_changes` الـ27.
4. تحقق حي: نداء `_multimodal_one` بثلاث صور لنفس متجر «الجمعية السعودية للمحافظة على التراث» الذي انهار في run الأصلي.
5. توثيق الأدلة في check.md وإغلاق المهمة.

## Files to Change

Create:

- `.tasks/fix-mm-media-resolution/check.md`

Modify:

- `functions/pipeline/auto_review.py`
- `.tasks/fix-mm-media-resolution/spec.md` للحالات المرحلية والنهائية فقط
- `.tasks/fix-mm-media-resolution/plan.md` للحالات المرحلية والنهائية فقط

Delete:

- none

## Tests

- `python -m py_compile functions/pipeline/auto_review.py`
- `cd functions/pipeline && python -m unittest test_accuracy_changes -v`
- تحقق حي (موثق في check.md): نداء التحقق بثلاث صور على صور الدليل الحقيقية للمتجر المنهار سابقًا يجب أن يرجع JSON صالحًا فيه `visible/same_store/exact_name`.
- `python scripts/sdd_check.py --all`

## Rollback Plan

`git revert` للتعديل أو إزالة فرع الـfallback؛ لا بيانات ولا migrations.

## Risks

- الحالات المفردة فقط تستفيد من الدقة العالية الآن؛ حالات الثلاث صور ترجع للدقة الافتراضية (نفس سلوك ما قبل مهمة الدقة) — مقبول لأن البديل كان انهارًا كاملًا.
- رسالة الخطأ قد تختلف نصيًا بين نماذج Vertex؛ الـfallback يشترط وجود `media resolution` في النص فلا يبتلع أخطاء 400 أخرى.
