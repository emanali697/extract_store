# SDD Task Templates

استخدم اسم مجلد بصيغة `kebab-case`:

```text
.tasks/<task-name>/
├── spec.md
├── plan.md
└── check.md
```

## Usage

1. انسخ `spec.template.md` إلى المهمة الجديدة، وأكملها بحالة `Draft` ثم `Approved`.
2. بعد اعتماد الـspec، انسخ `plan.template.md` وأكمله ثم اعتمده.
3. نفّذ الخطة.
4. انسخ `check.template.md` وسجل نتائج التحقق الفعلية.
5. بعد نجاح كل المعايير، اجعل spec وplan في حالة `Complete` وcheck في حالة `Passed`.
6. شغّل `python scripts/sdd_check.py --all`.

لا تعدّل ملفات القوالب لتوثيق مهمة فعلية؛ أنشئ مجلد مهمة مستقلًا.
