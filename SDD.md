# Specification-Driven Development

هذا الملف هو نقطة الدخول لنظام SDD في **Store Extractor**. الهدف هو أن يكون المطلوب مكتوبًا وقابلًا للقياس قبل تعديل الكود، وأن يكون إتمام المهمة مدعومًا بنتائج تحقق واضحة.

## المسار الإلزامي

```text
Specify → Plan → Implement → Check
```

1. **Specify**: إنشاء `.tasks/<task-name>/spec.md` وكتابة السلوك المطلوب ومعايير القبول.
2. **Plan**: إنشاء `.tasks/<task-name>/plan.md` بعد اعتماد الـspec، وتحديد الملفات والاختبارات والمخاطر والتراجع.
3. **Implement**: تنفيذ الخطة فقط، وتحديث الوثائق إذا ظهر اختلاف حقيقي يستلزم موافقة.
4. **Check**: إنشاء `.tasks/<task-name>/check.md` وتسجيل أوامر التحقق والنتائج، ثم وضع المهمة في حالة `Complete`.

التفاصيل والأمثلة موجودة في [دليل العمل](docs/sdd-workflow.md)، والحالة الحالية للنظام موثقة في [Brownfield baseline](docs/brownfield-baseline.md).

## أمر التحقق

```powershell
python scripts/sdd_check.py --all
```

لا يعني نجاح هذا الأمر أن السلوك البرمجي صحيح وحده؛ هو يضمن اكتمال عقد SDD وترابط مستنداته. اختبارات الكود والفحص اليدوي المحددان في الخطة يظلان إلزاميين.

## الاستثناء الضيق

يمكن إعفاء تعديل لا يغير السلوك، مثل تصحيح إملائي أو تعليق أو ملف مولد/lock فقط. يجب ذكر `SDD-Exempt: <reason>` في وصف Pull Request. أي bug fix أو feature أو refactor أو تعديل API/بيانات/نشر يحتاج مهمة SDD.

## مراجع القواعد

- [القواعد العامة](rules/general-rules.md)
- [قواعد المشروع](rules/project-rules.md)
- [قوالب المهام](.tasks/_templates/README.md)
- [AGENTS.md](AGENTS.md) للمعمارية وأوامر التشغيل
