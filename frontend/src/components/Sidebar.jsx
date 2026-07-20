import { useAppStore } from '../store/appStore'

const CITIES = ['جدة', 'مكة المكرمة', 'الرياض', 'المدينة المنورة', 'غير ذلك']

export default function Sidebar() {
  const {
    city, streetName, district, speedMode, enablePlaces, enableStatus,
    setSettings,
  } = useAppStore()

  return (
    <div>
      <h5 className="mb-3">
        <i className="bi bi-sliders me-2"></i> إعدادات التحليل
      </h5>

      <div className="mb-3">
        <label className="form-label fw-semibold">
          <i className="bi bi-buildings me-1"></i> المدينة
        </label>
        <select
          className="form-select"
          value={city}
          onChange={(e) => setSettings({ city: e.target.value })}
        >
          {CITIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div className="mb-3">
        <label className="form-label fw-semibold">
          <i className="bi bi-geo-alt me-1"></i> اسم الشارع <span className="text-danger">*</span>
        </label>
        <input
          type="text"
          className="form-control"
          placeholder="مثال: شارع الأمير ماجد"
          value={streetName}
          onChange={(e) => setSettings({ streetName: e.target.value })}
        />
      </div>

      <div className="mb-3">
        <label className="form-label fw-semibold">
          <i className="bi bi-houses me-1"></i> الحي <span className="text-muted small">(اختياري)</span>
        </label>
        <input
          type="text"
          className="form-control"
          placeholder="مثال: حي الجوهرة"
          value={district}
          onChange={(e) => setSettings({ district: e.target.value })}
        />
      </div>

      <hr />
      <h6 className="text-muted mb-3">إعدادات متقدمة</h6>

      <div className="mb-3">
        <label className="form-label fw-semibold">نمط التقطيع</label>
        {[
          { key: 'auto', label: 'تلقائي (موصى به)' },
          { key: 'fast', label: 'سريع (كل 1 ثانية)' },
          { key: 'precise', label: 'دقيق (كل 0.5 ثانية)' },
        ].map(({ key, label }) => (
          <div className="form-check" key={key}>
            <input
              type="radio"
              className="form-check-input"
              id={`speed-${key}`}
              checked={speedMode === key}
              onChange={() => setSettings({ speedMode: key })}
            />
            <label className="form-check-label" htmlFor={`speed-${key}`}>{label}</label>
          </div>
        ))}
      </div>

      <div className="form-check form-switch mb-2">
        <input
          type="checkbox"
          className="form-check-input"
          id="enable-places"
          checked={enablePlaces}
          onChange={(e) => setSettings({ enablePlaces: e.target.checked })}
        />
        <label className="form-check-label" htmlFor="enable-places">
          🌍 البحث في Google Places
        </label>
      </div>

      <div className="form-check form-switch mb-3">
        <input
          type="checkbox"
          className="form-check-input"
          id="enable-status"
          checked={enableStatus}
          onChange={(e) => setSettings({ enableStatus: e.target.checked })}
        />
        <label className="form-check-label" htmlFor="enable-status">
          ✅ تحديد حالة المتاجر
        </label>
      </div>

      <hr />
      <details className="small text-muted">
        <summary className="fw-semibold">ℹ️ معلومات النظام</summary>
        <ul className="mt-2 mb-0 ps-3">
          <li>النسخة: v6 (May 2026)</li>
          <li>Cloud Vision OCR</li>
          <li>Vertex AI Gemini 2.5 Flash</li>
          <li>Google Places API (New)</li>
          <li>حد رفع الفيديو: 5 GB</li>
          <li>دقة GPS: 5-50 متر</li>
        </ul>
      </details>
    </div>
  )
}
