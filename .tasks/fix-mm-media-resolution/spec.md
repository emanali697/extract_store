# Fix Multimodal Verification media_resolution 400 on Multi-Image Requests

Status: Complete
Owner: Project owner
Type: Bug

## Context

مهمة `raise-extraction-accuracy` فعّلت `media_resolution=MEDIA_RESOLUTION_HIGH` في نداء التحقق البصري المستقل `_multimodal_one`. عند أول تشغيل حقيقي على فيديو بني مالك فشلت المرحلة 13B بالكامل وانهار `run_v6.py` لأن Vertex AI يرفض الطلب بـ `400 INVALID_ARGUMENT`.

## Current Behavior

- `_multimodal_one` يرسل حتى 3 صور دليل لكل متجر مع `media_resolution` العالية.
- رسالة الخطأ الفعلية من Vertex: `the model supports HIGH media resolution only for single images`.
- النداء يفشل 4 محاولات متتالية ثم يرفع `multimodal_verify` استثناءً يوقف الـpipeline دون نتائج نهائية.
- طلبات الصورة المفردة بنفس الإعداد تنجح، وطلبات تعدد الصور بدون الإعداد تنجح.

## Requirements

- تفعيل `media_resolution` العالية فقط عندما يحمل الطلب صورة دليل واحدة.
- إضافة fallback حتمي: إذا رفض Vertex الطلب بخطأ `INVALID_ARGUMENT` يخص media resolution، يُزال الإعداد ويُعاد الطلب بدونه ضمن نفس عداد المحاولات.
- لا تغيير في منطق القرار أو الـschema أو عدد صور الدليل.

## Constraints

- لا dependency جديدة ولا تغيير API.
- الحفاظ على فائدة الدقة العالية للحالات المفردة (أولوية: عدم كسر الطلب).

## Acceptance Criteria

- نداء تحقق بثلاث صور (نفس المتجر الذي انهار سابقًا: «الجمعية السعودية للمحافظة على التراث») ينجح ويعيد JSON صالح.
- نداء صورة مفردة يبقى قادرًا على استخدام الدقة العالية.
- `python -m py_compile auto_review.py` ينجح واختبارات `test_accuracy_changes` الـ27 تبقى ناجحة.

## Edge Cases

- نموذج مستقبلي يقبل HIGH مع تعدد الصور: لا يتأثر، لأن التفعيل يبقى مقيدًا بالصورة المفردة حتى يُراجع القرار.
- رفض 400 لسبب مختلف (ليست media resolution): يُسجل كالسابق ضمن المحاولات العادية.
- SDK أقدم بلا `MediaResolution`: التجاهل الصامت الحالي يستمر.

## Out of Scope

- تغيير عدد صور الدليل أو أحجامها أو إعادة تشغيل مراحل v3/v5.
- تحسين زمن التحقق أو تقليل عدد المتاجر المرسلة له.
