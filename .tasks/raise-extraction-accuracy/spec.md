# Raise Extraction Accuracy (Image Chain, Sharp Frames, OCR Ensemble, Field Gates)

Status: Complete
Owner: Project owner
Type: Feature

## Context

دقة استخراج الأسماء الحالية مقدرة بحوالي 36% على الفيديوهات الحقيقية، ومراجعة الكود أظهرت أربع مشاكل بنيوية في `functions/pipeline/`:

1. **سلسلة معالجة صور مهدرة**: `extractor.extract_sign_crop` يكبّر شريط اللافتات 2× (مثال: 3840px → 7680px)، ثم `analyzer._image_bytes` يصغّره إلى 3000px مع sharpening إضافي وضغط JPEG ثانٍ — أي resampling مزدوج وsharpening مزدوج يشوّهان الحروف العربية قبل وصولها إلى Gemini.
2. **اختيار فريمات أعمى للوضوح**: Pass 1 يستخرج فريمًا كل 0.5s، والفلترة حسب السرعة تختار أول فريم يتجاوز الفترة الزمنية دون أي قياس للـ motion blur، فتصل فريمات مهتزة إلى Gemini.
3. **لا يوجد مصدر قراءة مستقل**: Cloud Vision يُستخدم فقط لقراءة GPS overlay، بينما أسماء المتاجر والهواتف تعتمد على قراءة Gemini منفردة، و`run_analysis` يستقبل `ocr_texts=[]` فارغة رغم أن `multi_frame.enrich_stores_with_aggregates` جاهز للتصويت عبر الفريمات. لا يوجد median GPS عبر فريمات الدليل — الإحداثية تؤخذ من أول فريم دليل فقط.
4. **بوابة قبول على مستوى المتجر فقط**: `auto_review._decide` يعطي `auto_passed` بناءً على الاسم دون فصل تحقق الهاتف؛ رقم من قراءة واحدة قد يمر تلقائيًا رغم أن خطأ رقمًا واحدًا يجعل الهاتف كله خاطئًا.

مهمة `build-extraction-eval` (Complete) وفرت أداة القياس `scripts/extraction_eval.py` وعقد ground truth، وهذه المهمة تنفذ أول حزمة تحسينات فعلية لتُقاس بتلك الأداة. الخطة المعتمدة من صاحبة المشروع: إصلاح سلسلة الصور، اختيار أوضح فريم، إضافة Cloud Vision كقارئ مستقل مع تصويت هواتف عبر الفريمات، وبوابة تحقق لكل حقل (name/phone/location).

## Current Behavior

- `extract_sign_crop` (`functions/pipeline/extractor.py`) يقص شريطًا كامل العرض (8%–65% من الارتفاع) ثم يطبق CLAHE + sharpening kernel ثم يكبّر 2× بـ INTER_CUBIC.
- `analyzer._image_bytes` (`functions/pipeline/analyzer.py`) يصغّر أي صورة أعرض من 3000px، ثم contrast 1.15 + UnsharpMask + JPEG quality 88.
- `BASE_EXTRACTION_INTERVAL = 0.5` ثانية، و`filter_frames_by_speed` يختار أول فريم بعد انقضاء الفترة المطلوبة بلا معيار وضوح.
- `ocr.batch_ocr` يعمل على صور GPS فقط؛ لا يوجد OCR لنصوص اللافتات.
- `main.py` يستدعي `run_analysis(processed, [], gps_for_processed)` بقائمة OCR فارغة، ولا يستدعي `enrich_stores_with_aggregates` إطلاقًا.
- موقع المتجر = إحداثية أول فريم دليل (`best = evidence[0]` في `analyzer.run_analysis`).
- `auto_review._decide` يمرر `auto_passed` عند اتفاق القراءتين البصريتين على الاسم (أو ثقة نصية عالية) دون اشتراط تحقق الهاتف من مصدرين.
- `multimodal_verify` يحفظ هاتف التحقق المستقل في `s["phone"]` فوق هاتف القراءة الأولى، فيضيع دليل المصدر الأول.

## Requirements

- إلغاء التكبير 2× في قص اللافتات: الـcrop يُحفظ بدقته الأصلية، ولا يُصغّر في `analyzer._image_bytes` إلا فوق حد أعلى من عرض 4K الأصلي، مع بقاء نقطة sharpening واحدة فقط عبر السلسلة كلها.
- قياس وضوح (blur score) لكل فريم خام أثناء Pass 1، وفلترة السرعة تختار أوضح فريم داخل كل نافذة زمنية بدل أول فريم زمنيًا، مع الحفاظ على تخطي السيارة المتوقفة والـfallback الزمني الحالي عند غياب سرعات صالحة.
- تكثيف Pass 1 الافتراضي إلى 0.25s (قابل للضبط بمتغير بيئة) حتى توجد أكثر من مرشح داخل النوافذ عالية السرعة.
- إضافة قراءة نص اللافتات بـ Cloud Vision (`TEXT_DETECTION` مع language hints عربي/إنجليزي، وfallback إلى `DOCUMENT_TEXT_DETECTION` للصور الفارغة) على الفريمات المختارة، خلف flag تشغيل `SIGN_OCR_ENABLED` افتراضه مفعّل.
- تمرير نصوص OCR إلى مرحلة التحليل وإرفاقها بكل متجر (`vision_ocr_text`)، وتفعيل `multi_frame.enrich_stores_with_aggregates` في `main.py`:
  - median GPS عبر فريمات الدليل يستبدل إحداثية أول فريم، مع تسجيل `gps_samples`.
  - تصويت الهواتف من OCR عبر الفريمات (`phones_all`, `phone_votes`) دون الكتابة فوق هاتف Gemini المقروء بصريًا؛ OCR يملأ الهاتف فقط إذا كان فارغًا ويوسم `phone_source` بقيمة مميزة.
- الحفاظ على هاتف القراءة الأولى في `phone_first_pass` قبل أن يستبدله التحقق المستقل في `multimodal_verify`.
- بوابة تحقق لكل حقل في `auto_review`:
  - `phone_verified`: نفس الرقم (بعد التطبيع) يظهر من مصدرين مستقلين على الأقل بين {القراءة البصرية الأولى، التحقق البصري المستقل، تصويت OCR بأصوات ≥2 عبر فريمات، هاتف مرشح Google Places}؛ أي رقم ظاهر من مصدر واحد فقط يمنع `auto_passed` ويحول المتجر إلى `needs_human` مع سبب تأكيد الهاتف، بينما غياب الهاتف لا يمنع القبول.
  - `name_verified`: اتفاق القراءة الأولى مع التحقق المستقل (المنطق الحالي) أو مطابقة v5 مؤكدة.
  - تسجيل `field_verification` داخل `auto_review` مع قائمة الأدلة لكل حقل.
- وسم كل متجر نهائي في `run_v6` بـ `name_verified` / `phone_verified` / `location_verified` (الموقع: مرشح Google أو median GPS بعينتين فأكثر).
- استخدام `media_resolution=MEDIA_RESOLUTION_HIGH` في نداء التحقق البصري المستقل (`_multimodal_one`) عندما تدعمه نسخة SDK، مع تجاهل صامت عند عدم الدعم.
- عدم تغيير أرقام مراحل الـpipeline المرئية للواجهة: قراءة OCR للافتات تندرج تحت STAGE 5 الحالية، ولا تعديل على `frontend/` أو `functions/stages.py`.
- عدم تغيير fallback النتائج `v6 > v5 > v3` ولا عقود API ولا إعدادات النشر.

## Constraints

- لا dependency جديدة في `functions/requirements.txt`؛ PaddleOCR غير مشمول (يحتاج runtime أثقل وتُقيّم لاحقًا على Cloud Run).
- لا تدريب detector ولا tracking في هذه المهمة: لا توجد بيانات وسم بعد؛ القص يبقى شريطًا كامل العرض إلى حين مهمة detector منفصلة.
- لا نقل إلى Cloud Run Jobs هنا؛ حد 30 دقيقة للـCloud Tasks يبقى قائمًا، لذلك كثافة الفريمات المختارة المرسلة إلى Gemini لا تزيد عن الوضع الحالي (التكثيف في المجموعة الخام فقط).
- القياس deterministic: اختيار الفريم الأوضح والتصويت والبوابات كلها دوال نقية قابلة لاختبار الوحدة دون شبكة.
- لا كتابة إلى `traders-data-live` ولا تغيير لقواعد Firestore/Storage.
- القيم الجديدة في JSON النتائج إضافية فقط (additive) ولا تكسر `scripts/extraction_eval.py` أو المصدّرات.
- زيادة تخزين الفريمات الخام في `/tmp` نتيجة تكثيف Pass 1 تُدار بجعل الفترة قابلة للضبط عبر البيئة وتوثيق الخطر في الخطة.

## Acceptance Criteria

- `extract_sign_crop` يعيد cropًا بنفس أبعاد المنطقة المقصوصة من الفريم الأصلي (لا تكبير)، واختبار وحدة يثبت الأبعاد على صورة اصطناعية.
- `analyzer._image_bytes` لا يصغّر صورة بعرض ≤ 3840px (حد جديد أعلى من 3000px الحالي).
- Pass 1 يسجل `blur` لكل فريم، و`filter_frames_by_speed` يختار الفريم الأعلى وضوحًا داخل كل نافذة سرعة؛ اختبارات وحدة تغطي: اختيار الأوضح، تخطي التوقف، كسر التعادل بشكل deterministic، والـfallback عند سرعات صفرية كليًا.
- `read_signs_text` في `ocr.py` يبني طلبات `TEXT_DETECTION` مع language hints ويعيد النصوص بترتيب المدخلات، ويُستدعى من `main.py` تحت STAGE 5 عندما `SIGN_OCR_ENABLED` مفعّل.
- كل متجر في `stores_raw.json` يحمل `vision_ocr_text` و`gps_samples` عند توفر البيانات، و`phone` من Gemini لا يُستبدل بهاتف OCR، والهاتف الفارغ فقط يُملأ من OCR مع `phone_source="cloud_vision_ocr"`.
- median GPS: متجر بدليل 3 فريمات بإحداثيات معلومة يحصل على الوسيط لا أول قيمة؛ اختبار وحدة يثبت ذلك.
- `multimodal_verify` يحتفظ بالهاتف السابق في `phone_first_pass` عند الاستبدال.
- `_decide` لا يعطي `auto_passed` لمتجر عليه رقم هاتف غير مؤكد المصدرين؛ يعطي `needs_human` مع سبب تأكيد الهاتف، ويعطي `auto_passed` عندما لا يوجد هاتف أصلًا أو عند تحققه من مصدرين؛ اختبارات وحدة تغطي الحالات الأربع (محلية الاختبار: بدون شبكة).
- `auto_review` يسجل `field_verification` لكل متجر Tier 3، و`run_v6` يوسم كل المتاجر النهائية بـ `name_verified`/`phone_verified`/`location_verified`.
- نداء `_multimodal_one` يمرر `media_resolution` العالية عند دعم SDK دون كسر النسخ الأقدم.
- `python -m unittest` لاختبارات المهمة ينجح، و`python -m py_compile` لكل الملفات المعدلة ينجح، و`python -m unittest scripts.test_extraction_eval` يبقى ناجحًا دون تعديل، و`python scripts/sdd_check.py --all` ينجح.

## Edge Cases

- فيديو بسرعات OCR كلها صفر → الـfallback الزمني الحالي يعمل ويختار الأوضح داخل نوافذ الفترة الثابتة.
- فريمات cached (`--from-cache`) بلا `blur` محفوظ → تُعامل كدرجات متساوية ويُختار الأقدم زمنيًا (السلوك القديم).
- `SIGN_OCR_ENABLED=false` أو فشل Cloud Vision → `ocr_texts=[]` ويعمل الـpipeline كالسابق تمامًا.
- متجر بلا أي هاتف في كل المصادر → لا يُعاقب؛ الهاتف `None` في `field_verification` ولا يمنع `auto_passed`.
- رقم هاتف من OCR يخص لافتة جارة داخل الشريط → خطر معروف؛ التصويت عبر ≥2 فريم والاتفاق مع مصدر بصري يقللانه، ويُوثق في المخاطر.
- إحداثيات GPS غائبة عن فريمات الدليل → لا median ويبقى السلوك الحالي.
- SDK قديم بلا `MediaResolution` → يُتجاهل الإعداد ويكمل النداء بالوضع الافتراضي.
- فيديو طويل مع Pass 1 كل 0.25s قد يضغط `/tmp` في Functions → الفترة قابلة للضبط بيئيًا والخطر موثق.

## Out of Scope

- تدريب أو تشغيل sign detector (YOLO) أو ByteTrack/تتبع اللافتات وقص لافتة منفردة — مهمة لاحقة بعد بناء dataset وسم.
- إضافة PaddleOCR أو أي dependency ثقيلة إلى Functions.
- نقل الـworker إلى Cloud Run Jobs وتعديلات النشر.
- تغيير واجهة المراجعة أو `frontend/` أو مخطط Firestore.
- تغيير معايير `dedupe` أو v5 scoring عتباته.
- تشغيل benchmark على فيديوهات حقيقية — يتم لاحقًا بأداة `build-extraction-eval` بإشراف صاحبة المشروع.
