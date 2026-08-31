# Plan — Build Extraction Evaluation Foundation

Status: Complete
Spec: `.tasks/build-extraction-eval/spec.md`

## Approach

نبني evaluator محليًا باستخدام Python standard library فقط حتى يكون deterministic وسهل التشغيل في بيئة المشروع دون إضافة dependency أو الاتصال بأي خدمة خارجية.

الأداة ستفصل بين ثلاث طبقات:

1. validation لعقد ground truth وملف mapping اليدوي؛
2. تحويل نتائج v3/v5/v6 إلى تمثيل prediction موحد ثم matching حتمي؛
3. حساب المقاييس وإخراج JSON آلي وMarkdown للمراجعة البشرية.

المطابقة ستكون محافظة وقابلة للتفسير:

- mapping اليدوي، إن وُجد، له الأولوية ويُراجع للتعارضات؛
- بعده تطابق هاتف كامل وفريد؛
- بعده تطابق اسم normalized فريد؛
- بعده fuzzy Arabic name matching فوق threshold معلن، مع كسر التعادل بصورة deterministic والاستفادة من frame overlap/الترتيب عندما تتوفر البيانات؛
- الحالات المتقاربة أو غير الحاسمة تبقى unmatched وتظهر في التقرير بدل تخمين الربط بواسطة LLM.

كل metric سيعرض القيمة وnumerator وdenominator، وتوثق التعريفات في دليل الاستخدام. exact-name لن يخلط مع normalized/fuzzy-name، وحالات الهاتف `not_visible` و`unreadable` لن تُعامل كهواتف كان يجب استخراجها، لكن إخراج رقم لها سيظل ظاهرًا كخطأ محتمل.

## Impact Analysis

- Runtime: لا تغيير في pipeline أو backend أو Functions؛ الأداة CLI محلية فقط.
- Frontend: لا تغيير.
- Backend/Functions: قراءة ملفات JSON محلية فقط؛ لا imports من Firebase ولا اتصالات خارجية.
- Data and migrations: لا migration. يضاف schema جديد وملفات synthetic فقط. ملفات ground truth الحقيقية والتقارير المحلية تُستبعد من Git بنمط واضح مع إبقاء أمثلة synthetic.
- Deployment: لا نشر. الأداة تستخدم أثناء التطوير وShadow Eval فقط.

## Steps

1. تعريف JSON Schema لـground truth وmanual mapping مع version field ومعرفات ثابتة للعينات والمتاجر.
2. إضافة ملفات synthetic صغيرة تغطي متجرًا صحيحًا، متجرًا مفقودًا، نتيجة زائدة، اختلاف اسم عربي، هاتفًا خاطئًا، هاتفًا غير ظاهر وتكرارًا.
3. إنشاء module `scripts/extraction_eval.py` يحتوي:
   - validation برسائل تشير إلى sample/store؛
   - loaders لنتائج v3/v5/v6؛
   - Arabic/name/phone normalization؛
   - manual ثم automatic deterministic matching؛
   - metric calculation؛
   - JSON وMarkdown renderers؛
   - CLI arguments وexit codes واضحة.
4. تعريف `final surfaced prediction` بما يوافق العقود الحالية: تجاهل `excluded_from_results` و`auto_rejected` افتراضيًا، مع تسجيل عددها في metadata حتى لا تختفي بصمت.
5. إضافة اختبارات `unittest` مستقلة عن الشبكة والخدمات الخارجية، تشمل حالات القبول والـedge cases الأساسية.
6. توثيق إعداد Mini Eval من 50 متجرًا، سياسة حماية البيانات، أوامر validation/evaluation، تعريف كل metric، وخطوات التوسع إلى 200+ متجر.
7. تحديث `.gitignore` بأنماط محددة لملفات evaluation الحقيقية والتقارير مع السماح صراحة بملفات schema/examples الملتزمة.
8. تشغيل الاختبارات وcompile وتجربة CLI على synthetic fixtures ثم تسجيل الأدلة في `check.md`.
9. بعد نجاح التحقق، تحويل spec وplan إلى `Complete` وcheck إلى `Passed` وتشغيل SDD validation الكامل.

## Files to Change

Create:

- `scripts/extraction_eval.py`
- `scripts/test_extraction_eval.py`
- `evaluation/schema/ground-truth.schema.json`
- `evaluation/schema/manual-mapping.schema.json`
- `evaluation/examples/ground-truth.synthetic.json`
- `evaluation/examples/predictions-v6.synthetic.json`
- `evaluation/examples/manual-mapping.synthetic.json`
- `evaluation/examples/ground-truth.invalid-phone.synthetic.json`
- `docs/extraction-evaluation.md`
- `.tasks/build-extraction-eval/check.md`

Modify:

- `.gitignore`
- `.tasks/build-extraction-eval/spec.md` للحالات المرحلية والنهائية فقط
- `.tasks/build-extraction-eval/plan.md` للحالات المرحلية والنهائية فقط

Delete:

- none

## Tests

- `python -m unittest scripts.test_extraction_eval -v`
- `python -m py_compile scripts/extraction_eval.py scripts/test_extraction_eval.py`
- تشغيل validator على fixture صحيح والتأكد من exit code صفر.
- تشغيل validator على fixture مؤقت غير صحيح به `not_visible` مع هاتف غير فارغ والتأكد من exit code غير صفري ورسالة sample/store.
- تشغيل evaluator على fixtures وإنتاج التقريرين ثم فحص القيم المتوقعة للاكتشاف والاسم والهاتف والتكرار.
- تشغيل evaluator مرتين ومقارنة JSON الناتج للتأكد من determinism، مع استبعاد timestamp أو عدم إضافته أصلًا.
- `python scripts/sdd_check.py --all`
- فحص يدوي للتقرير Markdown والتأكد أن false positives وfalse negatives وأخطاء الاسم والهاتف تحمل معرفات مفهومة.

## Rollback Plan

الأداة معزولة عن runtime؛ rollback يكون بحذف ملفات evaluator/schema/examples/docs وإزالة أنماط `.gitignore` الخاصة بها. لا توجد بيانات إنتاج أو migrations أو إعدادات سحابية تحتاج استرجاعًا.

## Risks

- 50 متجرًا لا تكفي لاتخاذ قرار معماري نهائي؛ هي smoke baseline فقط، والهدف 200+ بعينات متنوعة.
- fuzzy threshold قد يخفي أخطاء حروف مهمة؛ لذلك exact وfuzzy منفصلان وكل match يسجل سببه ودرجته.
- النتائج القديمة قد لا تحتوي frame IDs أو visual evidence؛ loaders يجب أن تقبل الغياب وتظهر نقص coverage.
- greedy fuzzy matching قد يكون ملتبسًا لمتجرين متشابهين؛ الحالات القريبة تُرفض آليًا وتحتاج manual mapping.
- ground truth نفسه قد يحتوي أخطاء؛ validator يمنع التناقض البنيوي لكنه لا يستطيع إثبات صحة الوسم البشري.
- ملفات mapping المبنية على index تصبح غير صالحة إذا تغير ترتيب النتائج؛ التقرير والأداة سيستخدمان prediction IDs ثابتة مشتقة وموثقة، ويجب إعادة مراجعة mapping لكل run مختلف.
