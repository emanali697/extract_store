# Frontend — Store Extractor

واجهة المستخدم لـ **Store Extractor** باستخدام React 19 + Vite 8 + Bootstrap 5.3 RTL.

## المتطلبات

- Node.js 18+
- npm
- Backend شغال على `http://localhost:8000`

## التشغيل

```powershell
cd "d:/sharea elnassim/extract stores/frontend"
npm install
npm run dev
```

الواجهة هتكون متاحة على: <http://localhost:5173>

## الأوامر المتاحة

| الأمر | الوصف |
|---|---|
| `npm install` | تثبيت الـ dependencies |
| `npm run dev` | تشغيل خادم التطوير |
| `npm run build` | بناء نسخة الإنتاج في `dist/` |
| `npm run preview` | معاينة نسخة الإنتاج |
| `npm run lint` | تشغيل ESLint |

## الإعدادات

ملف `.env.development` بيحدد عنوان الـ API:

```text
VITE_API_BASE_URL=http://localhost:8000
```

لو غيّرت port الـ Backend، غيّر الرابط هنا.

## هيكل المشروع

```text
frontend/src/
├── App.jsx                 # Routes الرئيسية
├── main.jsx                # نقطة الدخول
├── index.css               # التنسيقات العامة
├── components/
│   ├── Layout.jsx          # الهيكل العام + Sidebar
│   ├── Sidebar.jsx         # إعدادات التحليل
│   ├── StageList.jsx       # قائمة مراحل المعالجة
│   └── ResumeBanner.jsx    # استئناف الـ jobs السابقة
├── pages/
│   ├── UploadPage.jsx      # رفع الفيديو
│   ├── ProgressPage.jsx    # متابعة التقدم
│   ├── ReviewPage.jsx      # المراجعة البشرية
│   └── ResultsPage.jsx     # النتائج والتصدير
├── services/
│   ├── api.js              # Axios + WebSocket helper
│   ├── firebase.js         (اختياري) init للـ Firebase client
│   └── mockRunner.js       # محاكاة محلية للـ Pipeline
├── store/
│   └── appStore.js         # Zustand global state
└── data/
    ├── stages.js           # تعريفات المراحل التسع
    └── demoData.js         # بيانات تجريبية
```

## ملاحظات

- الواجهة **RTL** بالكامل ومخصصة للغة العربية.
- الأيقونات من Bootstrap Icons: `<i className="bi bi-icon-name">`.
- مكتبة الحالة العالمية هي Zustand مع `persist` middleware لتخزين localStorage.
- كل الاتصال بالـ Backend بيتم عن طريق `services/api.js`.

## حل مشاكل شائعة

### الواجهة مش بتقدر توصل للـ Backend

تأكد من:

1. الـ Backend شغال على `http://localhost:8000`.
2. قيمة `VITE_API_BASE_URL` في `frontend/.env.development` صحيحة.
3. المتصفح مش محجوب بسبب CORS (الـ Backend يسمح بـ `localhost:5173` افتراضيًا).

### مشاكل في التثبيت

جرب:

```powershell
rm -rf node_modules package-lock.json
npm install
```
