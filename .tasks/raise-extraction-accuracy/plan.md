# Plan — Raise Extraction Accuracy (Image Chain, Sharp Frames, OCR Ensemble, Field Gates)

Status: Complete
Spec: `.tasks/raise-extraction-accuracy/spec.md`

## Approach

أربع حزم تعديل داخل `functions/pipeline/` فقط، كلها deterministic وقابلة لاختبار الوحدة، ولا تغيّر أي عقد UI أو API:

1. **سلسلة الصور**: إيقاف التكبير 2× في `extract_sign_crop` (مع بقاء CLAHE الخفيف ونقل الـsharpening ليكون حصريًا في نقطة واحدة داخل `analyzer._image_bytes`)، ورفع حد التصغير في `_image_bytes` من 3000 إلى 3840px حتى لا يُعاد تصغير شريط 4K الأصلي. النتيجة: resample واحد أقل، sharpening واحد، ضغط JPEG أقل — تفاصيل الحروف العربية تصل Gemini أوضح.
2. **أوضح فريم**: Pass 1 يحسب `blur` (تباين Laplacian على منطقة اللافتات بعد تصغير حسابي رخيص) لكل فريم خام، و`filter_frames_by_speed` يتحول من «أول فريم بعد الفترة» إلى «أوضح فريم داخل نافذة الفترة» مع كسر تعادل deterministic بالأقدم زمنيًا. `BASE_EXTRACTION_INTERVAL` يصبح 0.25s افتراضيًا وقابلًا للضبط بيئيًا. عدد الفريمات المختارة لا يزيد، فلا تتغير كلفة Gemini ولا زمن المعالجة تقريبًا.
3. **قارئ OCR مستقل + تجميع multi-frame**: `ocr.read_signs_text` يقرأ الفريمات المختارة بـ `TEXT_DETECTION` (hints عربي/إنجليزي) مع إعادة المحاولة الفارغة بـ `DOCUMENT_TEXT_DETECTION`، و`main.py` يمرر النصوص ويستدعي `enrich_stores_with_aggregates` بعد `run_analysis` مباشرة: median GPS عبر فريمات الدليل، وتصويت الهواتف (`vote_phones`) كدليل مستقل دون استبدال هاتف Gemini إلا عندما يكون فارغًا. `multimodal_verify` يحفظ الهاتف السابق في `phone_first_pass`.
4. **بوابة الحقول**: `auto_review` يبني `field_verification` لكل متجر Tier 3، وقاعدة صارمة للهاتف: رقم موجود من مصدر واحد فقط ⇒ `needs_human` بسبب «تأكيد الهاتف»؛ لا هاتف ⇒ لا عقوبة. `run_v6` يوسم كل متجر نهائي بـ `name_verified`/`phone_verified`/`location_verified` عبر دالة مشتركة `compute_field_verification`. و`_multimodal_one` يفعّل `media_resolution` العالية عند توفرها في SDK (try/except).

المراحل المرئية للواجهة لا تتغير: قراءة OCR للافتات تُسجَّل تحت STAGE 5 الموجودة (`PIPELINE_STAGE_TO_UI` في `functions/stages.py` لا يُمس).

## Impact Analysis

- Runtime: تغييرات سلوك داخل pipeline فقط (جودة صور أعلى، اختيار فريم أوضح، حقول JSON إضافية، تشدد قبول الهاتف). لا تغيير في endpoints أو WebSocket أو عقد النتائج المعروضة.
- Frontend: لا تغيير. أرقام المراحل والأسماء كما هي.
- Backend/Functions: لا تغيير في `functions/main.py` أو `functions/runner.py`؛ الإعدادات الجديدة كلها في `functions/pipeline/config.py` مع overrides بيئية اختيارية. لا dependency جديدة.
- Data and migrations: لا migration. `stores_raw.json`/`stores_v6_final.json` تكسب حقولًا إضافية فقط (`vision_ocr_text`, `phones_all`, `phone_votes`, `gps_samples`, `phone_first_pass`, `field_verification`, `*_verified`)؛ القرّاء الحاليون (`runner._read_results`, المصدّرات، `scripts/extraction_eval.py`) لا يتأثرون.
- Deployment: لا نشر ضمن المهمة. عند النشر لاحقًا تُرفع `functions/` كالمعتاد؛ متغيرات البيئة الاختيارية (`BASE_EXTRACTION_INTERVAL`, `SIGN_OCR_ENABLED`) لها افتراضات آمنة.
- Cost/time: نفس عدد فريمات Gemini تقريبًا + استدعاءات Cloud Vision إضافية بعدد الفريمات المختارة (قابلة للإيقاف بـ `SIGN_OCR_ENABLED=false`). زمن Pass 1 يزيد قليلًا (حساب blur) ومساحة `/tmp` للفريمات الخام تتضاعف عند 0.25s — مُوثق كخطر مع مخرج بيئي.

## Steps

1. `config.py`: جعل `BASE_EXTRACTION_INTERVAL` قابلًا للضبط بيئيًا بقيمة 0.25، وإضافة `SIGN_OCR_ENABLED` (افتراضي true)، و`OCR_SIGN_LANGUAGE_HINTS = ["ar", "en"]`.
2. `extractor.py`:
   - `enhance_image(img, sharpen=True)` — معامل اختياري؛ و`extract_sign_crop` يستدعيه بلا sharpening ودون تكبير (يبقى GPS crop كما هو تمامًا).
   - حساب `blur` لكل فريم في `extract_frames_pass1` (Laplacian variance على منطقة اللافتات بعد resize حسابي إلى 640px عرضًا).
   - إعادة كتابة `filter_frames_by_speed` بمنطق النوافذ: تجميع الفريمات غير المتوقفة في نافذة بطول الفترة المطلوبة لسرعة أول مرشح، واختيار الأعلى `blur` (كسر التعادل بالأقدم)، مع الإبقاء على fast/precise/auto والـfallback الزمني.
3. `ocr.py`: تعميم `_load_batch_requests`/`_run_one_batch`/`batch_ocr` بمعاملَي `feature_type` و`language_hints` (افتراضهما السلوك الحالي لمسار GPS)، وإضافة `read_signs_text(paths, log_fn)` = batch بـ TEXT_DETECTION + hints، مع `_retry_empty_results` الحالية كـ fallback تلقائي.
4. `analyzer.py`: `_image_bytes` يرفع `max_width` إلى 3840 (تصغير LANCZOS فقط فوقه)، ويبقى contrast/UnsharpMask كنقطة التحسين الوحيدة.
5. `multi_frame.py`: في `enrich_stores_with_aggregates` — لا استبدال لهاتف Gemini؛ OCR يملأ الفارغ فقط مع `phone_source="cloud_vision_ocr"`، وإضافة `vision_ocr_text` للمتجر، والإبقاء على median GPS و`gps_samples`.
6. `main.py`: قبل STAGE 5 مباشرة، عند `SIGN_OCR_ENABLED` قراءة نصوص اللافتات للفريمات المعالجة (`read_signs_text`) تحت نفس marker STAGE 5، تمريرها إلى `run_analysis`، وبعده استدعاء `enrich_stores_with_aggregates(stores, ocr_texts, gps_for_processed, processed)`.
7. `auto_review.py`:
   - `_normalized_phone_digits` + `compute_phone_sources(store)` + `compute_field_verification(store)` (مصادر الهاتف: `phone_first_pass`/هاتف أولي، `multimodal.phone`, `phones_all` بأصوات ≥2، `v5.candidate.phone`).
   - `multimodal_verify` يحفظ `phone_first_pass` قبل الاستبدال.
   - `_decide`: عند أي نتيجة `auto_passed` مع وجود هاتف غير مؤكد المصدرين ⇒ تحويل إلى `needs_human` بسبب تأكيد الهاتف؛ وتضمين `field_verification` في كتلة `auto_review`.
   - `_multimodal_one`: `media_resolution=MEDIA_RESOLUTION_HIGH` داخل try/except.
8. `run_v6.py`: بعد `enrich_location_meta`، وسم كل متجر بـ `name_verified`/`phone_verified`/`location_verified` عبر `compute_field_verification`.
9. اختبارات `functions/pipeline/test_accuracy_changes.py` (unittest، بلا شبكة) + تشغيلها + py_compile + اختبارات `scripts.test_extraction_eval` للتأكد من عدم الكسر.
10. تسجيل الأدلة في `check.md`، وتحويل spec/plan إلى Complete بعد نجاح التحقق، وتشغيل `python scripts/sdd_check.py --all`.

## Files to Change

Create:

- `functions/pipeline/test_accuracy_changes.py`
- `.tasks/raise-extraction-accuracy/check.md`

Modify:

- `functions/pipeline/config.py`
- `functions/pipeline/extractor.py`
- `functions/pipeline/ocr.py`
- `functions/pipeline/analyzer.py`
- `functions/pipeline/multi_frame.py`
- `functions/pipeline/main.py`
- `functions/pipeline/auto_review.py`
- `functions/pipeline/run_v6.py`
- `.tasks/raise-extraction-accuracy/spec.md` للحالات المرحلية والنهائية فقط
- `.tasks/raise-extraction-accuracy/plan.md` للحالات المرحلية والنهائية فقط

Delete:

- none

## Tests

- `cd functions/pipeline && python -m unittest test_accuracy_changes -v`:
  - اختيار أوضح فريم داخل نافذة سرعة، وتخطي المتوقفة، وكسر التعادل بالأقدم، والـfallback الزمني عند سرعات صفرية.
  - `extract_sign_crop` يحافظ على أبعاد القص الأصلية (لا تكبير) على صورة اصطناعية.
  - `enhance_image(sharpen=False)` لا يغيّر الأبعاد.
  - `_image_bytes` لا يصغّر صورة 3840px (يختبر عبر PIL اصطناعية).
  - `enrich_stores_with_aggregates`: الحفاظ على هاتف Gemini، ملء الفارغ من OCR مع `phone_source` الجديد، median GPS لثلاث عينات.
  - `compute_field_verification`/`_decide`: auto_passed بلا هاتف؛ auto_passed بهاتف مؤكد من مصدرين؛ needs_human بهاتف مصدر واحد؛ needs_human عند اختلاف المصدرين.
- `python -m py_compile` لكل ملف معدل.
- `python -m unittest scripts.test_extraction_eval -v` (عدم كسر أداة التقييم).
- `python scripts/sdd_check.py --all`.
- اختبار يدوي مؤجل بعلم صاحبة المشروع: تشغيل job حقيقي على الفيديوهات المرجعية ثم تقييم `stores_v6_final.json` بـ `scripts/extraction_eval.py` مقابل Mini Eval — يُسجل لاحقًا خارج هذه المهمة كـ benchmark.

## Rollback Plan

كل التغييرات داخل `functions/pipeline/` وخلف افتراضات قابلة للعكس: `SIGN_OCR_ENABLED=false` يعيد مسار OCR للوضع السابق، و`BASE_EXTRACTION_INTERVAL=0.5` يعيد كثافة الاستخراج السابقة. عند الحاجة بعد الدمج: `git revert` لcommit المهمة يعيد السلسلة كلها دون أي migration أو بيانات إنتاج.

## Risks

- رفع Pass 1 إلى 0.25s يضاعف ذروة تخزين `/tmp` في Functions (RAM-backed مع 4GB)؛ الفيديوهات الطويلة قد تحتاج `BASE_EXTRACTION_INTERVAL=0.5` بيئيًا أو مهمة Cloud Run اللاحقة.
- OCR للشريط كامل العرض قد يلتقط هاتف لافتة جارة؛ التصويت ≥2 فريم واشتراط اتفاق مصدرين للقبول الآلي يحدّان منه، والمراجعة البشرية تبقى للحالات غير المؤكدة.
- تشدد الهاتف سيحوّل متاجر صحيحة الاسم إلى `needs_human` لتأكيد الرقم — مقصود (رفع دقة الهواتف المقبولة ≥95%) لكنه يخفض معدل auto_passed قصير المدى.
- `media_resolution` العالية ترفع زمن/كلفة نداء التحقق لكل متجر؛ محصورة في مرحلة التحقق فقط وليست في القراءة الأولى المجمعة.
- blur المقاس على منطقة اللافتات قد لا يمثل وضوح لافتة صغيرة بعيدة؛ يبقى معيارًا نسبيًا داخل النافذة الواحدة وهو أفضل من الاختيار الأعمى الحالي.
- دقة التحسن الفعلية غير مثبتة داخل المهمة؛ إثباتها يتطلب تشغيل Mini Eval الحقيقي (خارج النطاق، موثق في spec).
