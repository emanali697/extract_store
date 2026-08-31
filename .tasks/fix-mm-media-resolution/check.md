# Check — Fix Multimodal Verification media_resolution 400 on Multi-Image Requests

Status: Passed
Spec: `.tasks/fix-mm-media-resolution/spec.md`
Plan: `.tasks/fix-mm-media-resolution/plan.md`

## Scope Verified

التعديل داخل النطاق: `functions/pipeline/auto_review.py` فقط (تفعيل مشروط بصورة واحدة + fallback عند رفض Vertex) دون أي تغيير في الـschema أو منطق القرار أو عدد صور الدليل.

## Automated Checks

| Command | Result | Evidence |
|---|---|---|
| `python -m py_compile functions/pipeline/auto_review.py` | Passed | Exit code 0. |
| `cd functions/pipeline && python -m unittest test_accuracy_changes` | Passed | 27 اختبارًا ناجحًا. |
| تشخيص سبب الفشل (نداء مباشر بثلاث صور) | Confirmed | Vertex ردّد: `the model supports HIGH media resolution only for single images` — صورة واحدة + HIGH تنجح، وثلاث صور + HIGH تفشل بـ400، وثلاث صور بدون الإعداد تنجح. |
| تحقق حي بعد الإصلاح | Passed | `_multimodal_one` بثلاث صور لمتجر «الجمعية السعودية للمحافظة على التراث» (نفس المنهار سابقًا) أعاد JSON صالحًا: `visible=True, same_store=True, exact_name='الجمعية السعودية للمحافظة على التراث', entity_type='institution', image_clarity=0.9`. |
| `python scripts/sdd_check.py --all` | Passed | — |

## Manual Checks

- Passed: مراجعة الـdiff: المنع الاستباقي يحسب صور الدليل من `parts` ويفعّل HIGH فقط لصورة واحدة، والـfallback لا يبتلع أخطاء 400 غير المتعلقة بـmedia resolution (يشترط وجود النصين `INVALID_ARGUMENT` و`media resolution`).

## Acceptance Criteria

- Passed: نداء ثلاث صور للمتجر المنهار سابقًا نجح وأعاد JSON صالحًا (نتيجة التحقق الحي أعلاه).
- Passed: طلب الصورة المفردة يحتفظ بالدقة العالية (التفعيل مقيد بـ `image_parts == 1` والاختبار التشخيصي أثبت نجاح صورة مفردة + HIGH).
- Passed: الترجمة والاختبارات الـ27 ناجحة.

## Residual Risks

- طلبات الثلاث صور تعمل بالدقة الافتراضية (سلوك ما قبل مهمة الدقة)؛ لو صدر نموذج يدعم HIGH مع تعدد الصور يمكن مراجعة القيد لاحقًا.

## Verdict

Passed. سبب الانهيار مؤكد برسالة Vertex، والإصلاح مثبت حيًا على نفس بيانات الفشل الأصلية.
