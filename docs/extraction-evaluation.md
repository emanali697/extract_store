# دليل تقييم استخراج المتاجر

هذه الأداة تقيس نتائج v3/v5/v6 محليًا وبشكل deterministic. لا تستدعي Gemini أو Cloud Vision أو Firebase أو Google Places، ولا ترسل أي بيانات خارج الجهاز.

## حماية البيانات

- ضع ملفات ground truth الحقيقية داخل `evaluation/local/` فقط؛ هذا المسار مستبعد من Git.
- ضع التقارير المحلية داخل `evaluation/reports/`؛ هذا المسار مستبعد أيضًا.
- لا تضف فيديوهات أو crops أو أرقام هواتف حقيقية أو service-account files إلى Git.
- الملفات الموجودة في `evaluation/examples/` صناعية بالكامل وتشرح العقد فقط.

## عقد Ground Truth

المرجع الرسمي للشكل هو `evaluation/schema/ground-truth.schema.json`. يحتوي الملف dataset واحدة أو أكثر من عينات الفيديو. كل entity لها:

- `entity_id`: معرف ثابت داخل العينة؛
- `entity_type`: متجر أو خدمة أو كيان سلبي مثل إعلان أو مركبة؛
- `name_exact`: النص الحرفي المؤكد من اللافتة؛
- `accepted_names`: صيغ صحيحة بديلة، إن وجدت؛
- `phone.visibility`:
  - `visible`: الرقم كامل وقابل للقراءة، ويجب تسجيل قيمة واحدة على الأقل؛
  - `not_visible`: لا يوجد هاتف ظاهر، وتظل `values` فارغة؛
  - `unreadable`: توجد كتابة هاتف لكن الرقم غير قابل للتأكيد، وتظل `values` فارغة؛
- `frames`: نطاقات الفريمات التي يظهر فيها الكيان؛
- `tags`: خصائص مثل `blur` أو `night` أو `angled`.

لا تسجل رقمًا معروفًا من Google Places كحقيقة مرجعية للهاتف إذا لم يكن ظاهرًا في الفيديو.

## التحقق

```powershell
python scripts/extraction_eval.py validate `
  --ground-truth evaluation/local/ground-truth.json `
  --sample-id sample-001
```

مع ملف mapping يدوي:

```powershell
python scripts/extraction_eval.py validate `
  --ground-truth evaluation/local/ground-truth.json `
  --sample-id sample-001 `
  --mapping evaluation/local/sample-001.mapping.json
```

أي خطأ يرجع exit code مقداره `2` ورسالة تحتوي sample وentity المتأثرة.

## تشغيل التقييم

```powershell
python scripts/extraction_eval.py evaluate `
  --ground-truth evaluation/local/ground-truth.json `
  --sample-id sample-001 `
  --predictions backend/jobs/JOB_ID/stores_v6_final.json `
  --mapping evaluation/local/sample-001.mapping.json `
  --output-dir evaluation/reports/sample-001
```

الـmapping اختياري. معرف النتيجة يتولد من موضعها الأصلي في الملف بصيغة `prediction-0001`. يجب مراجعة mapping عند تغير ترتيب ملف النتائج.

الأداة تتجاهل افتراضيًا النتائج ذات `excluded_from_results=true` أو `auto_review.decision=auto_rejected`، وتسجل أعدادها في coverage.

## ترتيب المطابقة

1. mapping يدوي؛
2. هاتف كامل وفريد؛
3. اسم normalized وفريد؛
4. fuzzy match فوق threshold الافتراضي `0.85`؛
5. ربط النتائج الإضافية بنفس المتجر كـduplicates؛
6. إبقاء الحالات غير الحاسمة unmatched.

لا يستخدم evaluator نموذجًا لغويًا لحسم المطابقة. الحالات المتشابهة جدًا تحتاج mapping بشريًا حتى لا يبدو النظام أدق بسبب تخمين المقيم نفسه.

## تعريف المقاييس

- `store_detection_precision`: المتاجر الحقيقية المكتشفة مرة واحدة ÷ كل النتائج الظاهرة. التكرارات والكيانات غير التجارية تعد false positives.
- `store_detection_recall`: المتاجر الحقيقية المكتشفة ÷ كل المتاجر الحقيقية.
- `store_detection_f1`: المتوسط التوافقي للدقة والاستدعاء، ويعرض أيضًا `2TP ÷ (2TP + FP + FN)`.
- `exact_name_accuracy`: الأسماء المطابقة حرفيًا ÷ المتاجر الصحيحة المطابقة.
- `normalized_fuzzy_name_accuracy`: الأسماء المقبولة بعد التطبيع أو fuzzy threshold ÷ المتاجر الصحيحة المطابقة.
- `phone_coverage_all_businesses`: المتاجر المطابقة التي أخرج النظام لها أي هاتف ÷ كل المتاجر الحقيقية، سواء كان الهاتف صحيحًا أم لا.
- `phone_exact_precision`: نتائج الهاتف الصحيحة بالكامل ÷ كل النتائج التي أخرجت هاتفًا. هاتف على إعلان أو متجر غير مطابق يعد خطأ.
- `phone_exact_recall_visible`: المتاجر ذات هاتف مرئي قابل للقراءة واستخرج النظام رقمًا صحيحًا لها ÷ كل المتاجر ذات الهاتف المرئي القابل للقراءة.
- `duplicate_rate`: النتائج الزائدة المرتبطة بمتجر سبق اكتشافه ÷ كل النتائج الظاهرة.
- `auto_passed_accuracy`: نتائج `auto_passed` الصحيحة كمتجر واسم وهاتف، إن أخرج هاتفًا، ÷ كل نتائج `auto_passed`.

كل metric في JSON يحتوي `value` و`numerator` و`denominator`. عندما يكون المقام صفرًا تكون القيمة `null` بدل عرض نسبة مضللة.

## بناء Mini Eval

### المرحلة الأولى: 50 متجرًا

- اختر عدة مقاطع قصيرة من فيديوهات مختلفة.
- علّم كل متجر وكل كيان قد يسبب false positive، وليس فقط نتائج النظام.
- وزع العينة بين النهار والليل والسرعات واللافتات العربية والإنجليزية.
- راجع الأسماء والهواتف شخصان عند الإمكان.
- ثبّت نسخة ground truth ولا تعدلها بعد رؤية نتيجة تجربة معينة إلا لتصحيح خطأ موثق.

هذه المرحلة smoke baseline وليست كافية لاختيار معماري نهائي.

### المرحلة الثانية: 200 متجر أو أكثر

- حافظ على مجموعة holdout لا تستخدم أثناء ضبط thresholds.
- سجل النتائج حسب السرعة والجودة واللغة وظهور الهاتف.
- قارن كل تغيير بنفس dataset ونفس mapping ونفس threshold.
- لا تعتمد تحسينًا يرفع precision عبر حذف معظم النتائج؛ راقب precision وrecall معًا.

## تجربة المثال الصناعي

```powershell
python scripts/extraction_eval.py evaluate `
  --ground-truth evaluation/examples/ground-truth.synthetic.json `
  --sample-id synthetic-street-001 `
  --predictions evaluation/examples/predictions-v6.synthetic.json `
  --mapping evaluation/examples/manual-mapping.synthetic.json `
  --output-dir evaluation/reports/synthetic
```
