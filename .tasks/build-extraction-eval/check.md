# Check — Build Extraction Evaluation Foundation

Status: Passed
Spec: `.tasks/build-extraction-eval/spec.md`
Plan: `.tasks/build-extraction-eval/plan.md`

## Scope Verified

التنفيذ داخل النطاق المعتمد: أداة CLI وschemas وأمثلة synthetic واختبارات وتوثيق فقط. لم يتغير pipeline أو backend أو Functions أو frontend أو Firebase، ولم يحدث اتصال شبكي أو كتابة إلى `traders-data-live`.

## Automated Checks

| Command | Result | Evidence |
|---|---|---|
| `python -m unittest scripts.test_extraction_eval -v` | Passed | 7 tests passed in 0.015s. أول تشغيل كشف خطأ `round()` في F1؛ تم إصلاحه وإعادة المجموعة بنجاح. |
| `python -m py_compile scripts/extraction_eval.py scripts/test_extraction_eval.py` | Passed | Exit code 0. |
| `python -m json.tool` لكل schema وfixture | Passed | ملفات JSON الستة parsed بنجاح. |
| Synthetic CLI validation and evaluation | Passed | validator عرض dataset/sample/5 entities، وأنشأ `report.json` و`report.md`. |
| Invalid phone visibility validation | Passed | Exit code 2 ورسالة `sample/invalid-phone-sample/entity/store-invalid-phone: not_visible phone must have empty values`. |
| Deterministic report comparison | Passed | JSON SHA-256 في التشغيلين `A8C6CF36AC6ED62A5A571D3DF0088954E7AEA6C741786BFD1979DC3A379E9847`؛ Markdown في التشغيلين `E71E7657C51DA1250303A2145495B98D26B2E241646AD5071E94A8954DC050D3`. |
| `git diff --check` | Passed | Exit code 0؛ ظهرت تحذيرات CRLF لملفات موجودة فقط دون whitespace errors. |
| `python scripts/sdd_check.py --all` | Passed | `SDD validation passed for 4 task(s).` |

## Manual Checks

- Passed: تمت مراجعة `evaluation/reports/synthetic-first/report.md` يدويًا.
- التقرير عرض false negative `store-004`، وخطأ الاسم `prediction-0002`، وخطأي الهاتف `prediction-0004/0005`، والتكرار `prediction-0003` بمعرفات واضحة.
- بيانات التقرير synthetic فقط، ومسار `evaluation/reports/` مستبعد من Git.

## Acceptance Criteria

- Passed: schema موثق ويمثل حالات الهاتف الثلاث، وتحقق JSON parsing.
- Passed: validator رفض تناقض `not_visible` مع قيمة هاتف وحدد sample/entity.
- Passed: loaders قبلت قائمة v3/v5/v6 وwrapper يحتوي `stores[]` في الاختبارات.
- Passed: CLI أنشأ JSON وMarkdown بكل metrics مع numerator وdenominator؛ F1 يستخدم `2TP/(2TP+FP+FN)`.
- Passed: exact-name منفصل عن normalized/fuzzy-name؛ المثال حقق 2/3 exact و3/3 fuzzy.
- Passed: phone coverage منفصل عن exact precision/visible recall؛ المثال حقق 2/4 و2/4 و1/2 على الترتيب.
- Passed: التكرار قيس كـ1/5 ولم يتحول إلى true positive ثانٍ.
- Passed: التقرير سرد false positives وfalse negatives وأخطاء الاسم والهاتف بمعرفات مستقرة.
- Passed: الاختبارات تغطي correct match، missing store، extra non-business result، Arabic one-letter difference، wrong phone، not-visible phone، duplicate، malformed prediction، excluded/rejected filtering وdeterminism.
- Passed: لا توجد فيديوهات أو crops أو بيانات أو أرقام حقيقية أو secrets؛ كل الأمثلة مصنفة synthetic.

## Residual Risks

- الـMini Eval الحقيقي ما زال يحتاج وسمًا ومراجعة بشرية؛ الأداة لا تثبت صحة الـground truth نفسه.
- المطابقة fuzzy المحافظة تترك الحالات الملتبسة unmatched؛ يجب استخدام manual mapping لها.
- `prediction-NNNN` يعتمد على ترتيب ملف run المحدد، لذلك يجب مراجعة mapping عند تغير النتائج.

## Verdict

Passed. جميع معايير القبول داخل نطاق المهمة لها دليل تحقق مسجل، ونجح SDD validation النهائي.
