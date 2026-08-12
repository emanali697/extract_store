import { useEffect, useState } from 'react'
import Modal from 'react-bootstrap/Modal'
import { useAppStore } from '../store/appStore'
import { getSignImageUrl, saveReviewDecision } from '../services/api'

function ReviewCard({ item, jobId, onApprove, onReject, saving }) {
  const [name, setName] = useState(item.multimodalName || item.suggestedName)
  const [category, setCategory] = useState(item.category)
  const [phone, setPhone] = useState(item.phone || '')
  const [signSrc, setSignSrc] = useState(
    item.signImageUrl?.startsWith('http') ? item.signImageUrl : null
  )
  const [imageOpen, setImageOpen] = useState(false)

  const confPct = Math.round((item.confidence ?? 0) * 100)
  const confClass = confPct >= 70 ? 'success' : confPct >= 50 ? 'warning' : 'danger'

  useEffect(() => {
    if (signSrc || !jobId) return
    const filename = item.signImageFilename || item.signImageUrl?.split('/').pop()
    if (!filename) return

    let active = true
    getSignImageUrl(jobId, filename)
      .then((url) => active && setSignSrc(url))
      .catch(() => {/* Keep the image placeholder when no crop is available. */})

    return () => { active = false }
  }, [item.signImageFilename, item.signImageUrl, jobId, signSrc])

  return (
    <div className="review-card">
      <div className="row g-3">
        <div className="col-md-4">
          <div className="sign-thumb">
            {signSrc
              ? (
                  <button
                    type="button"
                    className="btn border-0 bg-transparent p-0 w-100 h-100"
                    onClick={() => setImageOpen(true)}
                    aria-label="تكبير صورة لوحة المتجر"
                    title="اضغط لتكبير الصورة"
                    style={{ cursor: 'zoom-in' }}
                  >
                    <img
                      src={signSrc}
                      alt={item.suggestedName}
                      style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: 10, background: '#000' }}
                    />
                  </button>
                )
              : <i className="bi bi-image"></i>}
          </div>

          <Modal
            show={imageOpen && Boolean(signSrc)}
            onHide={() => setImageOpen(false)}
            size="xl"
            centered
          >
            <Modal.Header closeButton className="bg-dark text-white border-secondary">
              <Modal.Title className="fs-6">
                <i className="bi bi-zoom-in me-2"></i>
                {name || item.suggestedName}
              </Modal.Title>
            </Modal.Header>
            <Modal.Body className="bg-dark p-2 text-center">
              <img
                src={signSrc || ''}
                alt={name || item.suggestedName}
                className="img-fluid"
                style={{ maxHeight: '82vh', objectFit: 'contain' }}
              />
            </Modal.Body>
          </Modal>

          {item.multimodalName && item.multimodalName !== item.suggestedName && (
            <div className="alert alert-info small mt-2 mb-0 py-2">
              <i className="bi bi-eye me-1"></i>
              <strong>Gemini شاف في الصورة:</strong> {item.multimodalName}
              <div className="text-muted mt-1" style={{ fontSize: '0.75rem' }}>
                الاسم النصي كان: {item.suggestedName}
              </div>
            </div>
          )}

          {item.rawOcr && (
            <div className="mt-2 small text-muted">
              <i className="bi bi-blockquote-right me-1"></i>
              النص الكامل من اللوحة:
              <div className="bg-light rounded p-2 mt-1" dir="rtl" style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem' }}>
                {item.rawOcr}
              </div>
            </div>
          )}

          {item.note && (
            <div className="alert alert-warning small mt-2 mb-0 py-2">
              <i className="bi bi-exclamation-circle me-1"></i> {item.note}
            </div>
          )}
        </div>

        <div className="col-md-8">
          <div className="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2">
            <span className={`badge badge-tier-${item.tier} px-3 py-2`}>Tier {item.tier}</span>
            <div className="d-flex align-items-center gap-2">
              <span className="small text-muted">ثقة Gemini:</span>
              <div className="progress" style={{ width: 120, height: 8 }}>
                <div className={`progress-bar bg-${confClass}`} style={{ width: `${confPct}%` }} />
              </div>
              <span className="small fw-semibold num-ltr">{confPct}%</span>
            </div>
          </div>

          <div className="row g-2">
            <div className="col-12">
              <label className="form-label small fw-semibold">اسم المتجر</label>
              <input
                className="form-control"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="col-sm-6">
              <label className="form-label small fw-semibold">التصنيف</label>
              <input
                className="form-control"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              />
            </div>
            <div className="col-sm-6">
              <label className="form-label small fw-semibold">الهاتف</label>
              <input
                className="form-control num-ltr"
                placeholder="05XXXXXXXX"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </div>
          </div>

          <div className="d-flex gap-2 mt-3 flex-wrap">
            <button
              className="btn btn-success"
              disabled={saving}
              onClick={() => onApprove({ ...item, name, category, phone, approved: true })}
            >
              {saving
                ? <><span className="spinner-border spinner-border-sm me-1" /> جاري الحفظ...</>
                : <><i className="bi bi-check-lg me-1"></i> موافق وأرسل</>}
            </button>
            <button
              className="btn btn-outline-secondary"
              disabled={saving}
              onClick={() => onApprove({ ...item, name, category, phone, approved: true, edited: true })}
            >
              <i className="bi bi-pencil me-1"></i> حفظ التعديل
            </button>
            <button
              className="btn btn-outline-danger"
              disabled={saving}
              onClick={() => onReject(item.id)}
            >
              <i className="bi bi-trash me-1"></i> حذف
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function ReviewPage() {
  const {
    jobId, reviewToken, analysisDone, analysisStatus, reviewItems, approvedItems, results,
    approveReviewItem, rejectReviewItem, finishAnalysis, setReviewItems,
  } = useAppStore()
  const [savingId, setSavingId] = useState(null)
  const [saveError, setSaveError] = useState('')

  const handleApprove = async (id, edited) => {
    setSavingId(id)
    setSaveError('')
    try {
      const response = await saveReviewDecision(jobId, reviewToken, id, 'approve', edited)
      approveReviewItem(id, edited)
      finishAnalysis(response.results, analysisStatus || 'done')
      setReviewItems(response.results?.review ?? [])
    } catch (error) {
      setSaveError(
        error?.response?.data?.detail
        || error?.message
        || 'تعذر حفظ تعديل المتجر'
      )
    } finally {
      setSavingId(null)
    }
  }

  const handleReject = async (id) => {
    setSavingId(id)
    setSaveError('')
    try {
      const response = await saveReviewDecision(jobId, reviewToken, id, 'reject')
      rejectReviewItem(id)
      finishAnalysis(response.results, analysisStatus || 'done')
      setReviewItems(response.results?.review ?? [])
    } catch (error) {
      setSaveError(
        error?.response?.data?.detail
        || error?.message
        || 'تعذر حذف المتجر من النتائج'
      )
    } finally {
      setSavingId(null)
    }
  }

  const summary = results?.summary ?? {}
  const autoPassed = summary.auto_passed ?? 0
  const autoRejected = summary.auto_rejected ?? 0

  if (!analysisDone) {
    return (
      <div className="alert alert-info" role="alert">
        <i className="bi bi-info-circle me-2"></i>
        التحليل لسه ما خلصش. اذهب لتبويب <strong>التقدم</strong>
      </div>
    )
  }

  return (
    <div>
      <h2 className="section-title">
        <i className="bi bi-clipboard-check me-2"></i> مراجعة المتاجر المشكوك فيها
      </h2>

      {saveError && (
        <div className="alert alert-danger" role="alert">
          <i className="bi bi-exclamation-triangle me-2"></i>
          {saveError}
        </div>
      )}

      {(autoPassed > 0 || autoRejected > 0) && (
        <div className="alert alert-info border-0 shadow-sm small mb-3">
          <i className="bi bi-robot me-2"></i>
          <strong>المراجعة الآلية (Gemini):</strong>{' '}
          أكّدت <span className="badge bg-success mx-1">{autoPassed}</span> متجر تلقائي،
          واستبعدت <span className="badge bg-secondary mx-1">{autoRejected}</span> كأخطاء OCR،
          وحوّلت <span className="badge bg-warning text-dark mx-1">{reviewItems.length}</span> ليكي للمراجعة البشرية.
        </div>
      )}

      <div className="row g-3 mb-3">
        <div className="col-md-3">
          <div className="stat-card">
            <div className="stat-num text-warning">{reviewItems.length}</div>
            <div className="stat-label">محتاج مراجعتك</div>
          </div>
        </div>
        <div className="col-md-3">
          <div className="stat-card">
            <div className="stat-num text-success">{approvedItems.length}</div>
            <div className="stat-label">تمت الموافقة</div>
          </div>
        </div>
        <div className="col-md-3">
          <div className="stat-card">
            <div className="stat-num text-primary">
              <i className="bi bi-robot"></i> {autoPassed}
            </div>
            <div className="stat-label">أكدها AI آليًا</div>
          </div>
        </div>
        <div className="col-md-3">
          <div className="stat-card">
            <div className="stat-num text-muted">{autoRejected}</div>
            <div className="stat-label">استبعدها AI (OCR error)</div>
          </div>
        </div>
      </div>

      {reviewItems.length === 0 ? (
        <div className="alert alert-success" role="alert">
          <i className="bi bi-check-circle-fill me-2"></i>
          مفيش متاجر باقية للمراجعة. ممكن دلوقتي ترفع المؤكدين لـ Firebase.
        </div>
      ) : (
        <div className="d-flex flex-column gap-3">
          {reviewItems.map((item) => (
            <ReviewCard
              key={item.id}
              item={item}
              jobId={jobId}
              saving={savingId === item.id}
              onApprove={(edited) => handleApprove(item.id, edited)}
              onReject={handleReject}
            />
          ))}
        </div>
      )}
    </div>
  )
}
