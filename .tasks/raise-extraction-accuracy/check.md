# Check — Raise Extraction Accuracy (Image Chain, Sharp Frames, OCR Ensemble, Field Gates)

Status: Passed
Spec: `.tasks/raise-extraction-accuracy/spec.md`
Plan: `.tasks/raise-extraction-accuracy/plan.md`

## Scope Verified

التنفيذ داخل النطاق المعتمد: تعديلات `functions/pipeline/` الثمانية + ملف اختبارات جديد فقط. لم يتغير `frontend/` أو `functions/main.py` أو `functions/runner.py` أو `functions/stages.py` أو `requirements.txt`، ولا dependency جديدة، ولا كتابة إلى `traders-data-live`. تدريب detector وPaddleOCR وCloud Run بقيت خارج النطاق كما وثّق الـspec.

## Automated Checks

| Command | Result | Evidence |
|---|---|---|
| `cd functions/pipeline && python -m unittest test_accuracy_changes -v` | Passed | 27 اختبارًا ناجحًا (1.4s). أول تشغيل كشف خطأين: guard في `aggregate_store_signals` كان يسقط median GPS عند تعطيل OCR (أُصلح في `multi_frame.py`)، واختبار field block كان ينقصه `_phones_clean` (أُصلح في الاختبار). أُعيدت المجموعة كاملة بنجاح. |
| `python -m py_compile config.py extractor.py ocr.py analyzer.py multi_frame.py main.py auto_review.py run_v6.py test_accuracy_changes.py` | Passed | Exit code 0 (`COMPILE_OK`). |
| `python -m unittest scripts.test_extraction_eval -v` | Passed | 7 اختبارات ناجحة — أداة التقييم لم تتكسر بالحقول الجديدة. |
| `python scripts/sdd_check.py --all` | Passed | `SDD validation passed for 5 task(s).` |
| `git diff --check` | Passed | لا whitespace errors؛ تحذيرات CRLF لملفات موجودة سابقًا فقط. |

## Manual Checks

- Passed: مراجعة يدوية للـdiff أظهرت أن قراءة OCR للافتات تندرج تحت marker STAGE 5 الحالية، فلا تتغير خريطة المراحل التسع في الواجهة.
- Passed: التحقق من أن `filter_frames_by_speed` يحافظ على الـfallback الزمني وعلى دلالات fast/precise/auto كما في الاختبارات.
- Pending (بعلم صاحبة المشروع): benchmark على فيديوهات حقيقية عبر `scripts/extraction_eval.py` مقابل Mini Eval لقياس التحسن الفعلي في الدقة — موثق في الـspec كخطوة لاحقة خارج نطاق المهمة.

## Acceptance Criteria

- Passed: `extract_sign_crop` يعيد cropًا بأبعاد القص الأصلية (285×1000 على صورة 500×1000 اصطناعية) دون تكبير — `test_sign_crop_keeps_native_dimensions`.
- Passed: `_image_bytes` لا يصغّر عرض 3840px ويصغّر 5000px إلى 3840 — `test_image_bytes_does_not_downscale_native_4k_strip` و`test_image_bytes_downscales_above_bound`.
- Passed: Pass 1 يسجل `blur` لكل فريم (`sign_region_blur_score`) والفلترة تختار الأوضح داخل كل نافذة مع كسر تعادل بالأقدم وتخطي التوقف والـfallback — اختبارات `SharpestWindowSelectionTest` السبعة.
- Passed: `read_signs_text` يبني طلبات `TEXT_DETECTION` مع hints عربي/إنجليزي عبر `batch_ocr(feature_type=..., language_hints=...)` ويُستدعى من `main.py` تحت STAGE 5 خلف `SIGN_OCR_ENABLED` مع fallback آمن عند الفشل.
- Passed: المتاجر تكسب `vision_ocr_text` و`gps_samples`، وهاتف Gemini محفوظ (`test_gemini_phone_is_preserved_and_ocr_votes_recorded`)، والفارغ فقط يُملأ من OCR مع `phone_source="cloud_vision_ocr"` (`test_ocr_fills_phone_only_when_empty`).
- Passed: median GPS يستبدل إحداثية أول فريم — `test_median_gps_replaces_first_frame_coordinate` (24.0/24.1/24.2 → 24.10000).
- Passed: `multimodal_verify` يحفظ الهاتف السابق في `phone_first_pass` قبل الاستبدال (تعديل موضعي مراجَع في `auto_review.py`).
- Passed: `_decide` — auto_passed بلا هاتف، auto_passed بهاتف مصدرين (gemini_first+gemini_verify / +ocr_votes / +places)، needs_human بمصدر واحد، needs_human عند التعارض — `FieldGateDecisionTest` الستة.
- Passed: `auto_review` يسجل `field_verification` ويوسم `name_verified`/`phone_verified`/`location_verified` لكل Tier 3، و`run_v6` يوسم كل المتاجر النهائية بعد `enrich_location_meta` — `FieldVerificationAnnotationTest` الثلاثة.
- Passed: `_multimodal_one` يمرر `MEDIA_RESOLUTION_HIGH` داخل try/except AttributeError؛ توفر النوع مؤكد على google-genai 1.69.0 المثبتة.
- Passed: أوامر unittest وpy_compile واختبارات أداة التقييم و`sdd_check.py --all` كلها ناجحة (جدول الأدلة أعلاه).

## Residual Risks

- التحسن الفعلي في الدقة لم يُقس بعد على فيديوهات حقيقية؛ يتطلب Mini Eval موسومًا وتشغيل shadow — خارج نطاق المهمة كما في الـspec.
- تكثيف Pass 1 إلى 0.25s يضاعف ذروة فريمات `/tmp`؛ الفيديوهات الطويلة جدًا قد تحتاج `BASE_EXTRACTION_INTERVAL=0.5` بيئيًا حتى مهمة Cloud Run.
- تشدد الهاتف سيرفع نسبة `needs_human` قصير المدى (مقصود لرفع دقة الأرقام المقبولة)، ويجب متابعة المعدل في أول benchmark.
- OCR الشريط كامل العرض قد يلتقط هاتف جار؛ التصويت ≥2 فريم واشتراط مصدرين يحدّان منه دون إلغائه حتى مهمة الـdetector.

## Verdict

Passed. جميع معايير القبول داخل نطاق المهمة لها دليل تحقق آلي مسجل، واختبارات الوحدة والترجمة وأداة التقييم وSDD validation كلها ناجحة.
