import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/appStore'
import { downloadExcelUrl, downloadCsvUrl, deleteVideo, approveStores, fetchHealth, previewTradersPush, pushToTraders } from '../services/api'

const TIER_LABEL = {
  1: 'Tier 1 — مؤكد',
  2: 'Tier 2 — من بحث ويب',
  3: 'Tier 3 — يحتاج تحقق',
}

// Both this UI switch and the backend TRADERS_WRITES_ENABLED switch must be true.
const TRADERS_ENABLED = import.meta.env.VITE_TRADERS_WRITES_ENABLED === 'true'

const SRC_LABEL = {
  google_places: 'Google',
  dashcam_frame: 'داش كاميرا',
  unknown: '—',
}

function reviewedStoreId(item) {
  const value = item?.storeId ?? item?.id
  const reviewMatch = String(value ?? '').match(/^r(\d+)$/)
  return reviewMatch ? reviewMatch[1] : String(value ?? '')
}

export default function ResultsPage() {
  const navigate = useNavigate()
  const { jobId, analysisDone, results, approvedItems, resetAll } = useAppStore()
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')

  const [videoState, setVideoState] = useState('present') // present|deleting|deleted|error
  const [videoError, setVideoError] = useState('')

  const [pushing, setPushing] = useState(false)
  const [pushResult, setPushResult] = useState(null)
  const [pushError, setPushError] = useState('')
  const [downloadBusy, setDownloadBusy] = useState('')
  const [downloadError, setDownloadError] = useState('')

  // traders-data-live integration
  const [tradersReady, setTradersReady] = useState(null)
  const [tradersPreview, setTradersPreview] = useState(null) // {count, documents}
  const [tradersBusy, setTradersBusy] = useState(false)
  const [tradersError, setTradersError] = useState('')
  const [tradersResult, setTradersResult] = useState(null)

  const [fbReady, setFbReady] = useState(null)

  useEffect(() => {
    fetchHealth().then((h) => {
      setFbReady(!!h?.firebase?.ready)
      setTradersReady(!!h?.traders?.ready && h?.traders?.writes_enabled === true)
    }).catch(() => { setFbReady(false); setTradersReady(false) })
  }, [])

  const stores = useMemo(() => {
    const originalStores = results?.stores ?? []
    if (!approvedItems.length) return originalStores

    const reviewedById = new Map(
      approvedItems.map((item) => [reviewedStoreId(item), item])
    )
    return originalStores.map((store) => {
      const reviewed = reviewedById.get(String(store.id))
      if (!reviewed) return store
      const reviewedName = reviewed.name
        || reviewed.multimodalName
        || reviewed.suggestedName
        || store.name
      return {
        ...store,
        name: reviewedName,
        name_ar: reviewedName,
        category: reviewed.category ?? store.category,
        phone: reviewed.phone ?? store.phone,
        approved: true,
        edited: Boolean(reviewed.edited),
      }
    })
  }, [approvedItems, results])
  const summary = useMemo(() => ({
    ...(results?.summary ?? {}),
    total: stores.length,
    active: stores.filter((store) => (
      Number(store.tier) === 1 || String(store.status || '').includes('نشط')
    )).length,
    phones: stores.filter((store) => String(store.phone || '').trim()).length,
    precise: stores.filter((store) => store.lat != null || store.lng != null).length,
  }), [results?.summary, stores])

  const eligibleForTraders = useMemo(
    () => stores.filter(s => s.auto_review_decision !== 'auto_rejected'),
    [stores]
  )

  const handleTradersPreview = async () => {
    setTradersError('')
    setTradersBusy(true)
    setTradersResult(null)
    try {
      const data = await previewTradersPush(jobId, eligibleForTraders)
      setTradersPreview(data)
    } catch (e) {
      setTradersError(e?.response?.data?.detail || e?.message || 'فشل المعاينة')
    } finally {
      setTradersBusy(false)
    }
  }

  const handleTradersPushConfirm = async () => {
    if (!confirm(`متأكدة تبعتي ${eligibleForTraders.length} متجر لـ traders-data-live؟`)) return
    setTradersBusy(true)
    setTradersError('')
    try {
      const res = await pushToTraders(jobId, eligibleForTraders)
      setTradersResult(res)
      setTradersPreview(null)
    } catch (e) {
      setTradersError(e?.response?.data?.detail || e?.message || 'فشل الرفع')
    } finally {
      setTradersBusy(false)
    }
  }

  const visible = useMemo(() => {
    return stores.filter((s) => {
      if (filter !== 'all' && String(s.tier) !== filter) return false
      if (search && !`${s.name} ${s.category} ${s.phone}`.includes(search)) return false
      return true
    })
  }, [stores, filter, search])

  const handleDeleteVideo = async () => {
    if (!confirm('متأكدة تحذفي ملف الفيديو؟ البيانات هتفضل محفوظة.')) return
    setVideoState('deleting')
    try {
      await deleteVideo(jobId)
      setVideoState('deleted')
    } catch (e) {
      setVideoError(e?.response?.data?.detail || e?.message || 'فشل')
      setVideoState('error')
    }
  }

  const handlePushFirebase = async () => {
    setPushing(true)
    setPushError('')
    setPushResult(null)
    try {
      // Push approved stores if any, otherwise tier-1 stores by default
      const approvedStoreIds = new Set(approvedItems.map(reviewedStoreId))
      const toPush = approvedStoreIds.size
        ? stores.filter((store) => approvedStoreIds.has(String(store.id)))
        : stores.filter((s) => s.tier <= 2)
      const res = await approveStores(jobId, toPush)
      setPushResult(res)
    } catch (e) {
      setPushError(e?.response?.data?.detail || e?.message || 'فشل الرفع لـ Firestore')
    } finally {
      setPushing(false)
    }
  }

  const handleDownload = async (kind) => {
    setDownloadBusy(kind)
    setDownloadError('')
    try {
      const url = kind === 'excel'
        ? await downloadExcelUrl(jobId)
        : await downloadCsvUrl(jobId)
      window.location.assign(url)
    } catch (e) {
      setDownloadError(
        e?.response?.data?.detail
        || e?.message
        || 'تعذر تجهيز رابط تحميل الملف'
      )
    } finally {
      setDownloadBusy('')
    }
  }

  if (!analysisDone) {
    return (
      <div className="alert alert-info" role="alert">
        <i className="bi bi-hourglass-split me-2"></i>
        التحليل لسه ما خلصش. اذهب لتبويب <strong>التقدم</strong>
      </div>
    )
  }

  return (
    <div>
      <h2 className="section-title">
        <i className="bi bi-bar-chart-line me-2"></i> ملخص النتائج
        {summary.source && (
          <span className="badge bg-light text-primary ms-2 small">
            مصدر: {summary.source}
          </span>
        )}
      </h2>

      <div className="row g-3 mb-4">
        <div className="col-6 col-md-3">
          <div className="stat-card">
            <div className="stat-num num-ltr">{summary.total}</div>
            <div className="stat-label">إجمالي المتاجر</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="stat-card">
            <div className="stat-num num-ltr text-success">{summary.active}</div>
            <div className="stat-label">✅ مؤكد نشط</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="stat-card">
            <div className="stat-num num-ltr text-warning">{summary.phones}</div>
            <div className="stat-label">📞 أرقام هاتف</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="stat-card">
            <div className="stat-num num-ltr" style={{ color: '#2E75B6' }}>{summary.precise}</div>
            <div className="stat-label">📍 موقع دقيق</div>
          </div>
        </div>
      </div>

      <h2 className="section-title">
        <i className="bi bi-list-ul me-2"></i> المتاجر المستخرجة
      </h2>

      <div className="row g-2 mb-3">
        <div className="col-md-6">
          <div className="input-group">
            <span className="input-group-text"><i className="bi bi-search"></i></span>
            <input
              className="form-control"
              placeholder="ابحث بالاسم، التصنيف، أو الرقم..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
        <div className="col-md-6">
          <div className="btn-group w-100" role="group">
            {[
              { key: 'all', label: 'الكل' },
              { key: '1', label: 'Tier 1' },
              { key: '2', label: 'Tier 2' },
              { key: '3', label: 'Tier 3' },
            ].map(({ key, label }) => (
              <button
                key={key}
                type="button"
                className={`btn ${filter === key ? 'btn-brand' : 'btn-outline-secondary'}`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="table-responsive">
        <table className="table table-hover align-middle bg-white rounded shadow-sm">
          <thead className="table-light">
            <tr>
              <th>#</th>
              <th>الاسم</th>
              <th>التصنيف</th>
              <th>الهاتف</th>
              <th>الحالة</th>
              <th>Tier</th>
              <th>مصدر الموقع</th>
              <th>دقة الموقع</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((s, i) => (
              <tr key={s.id}>
                <td className="num-ltr">{i + 1}</td>
                <td className="fw-semibold">{s.name}</td>
                <td>{s.category}</td>
                <td className="num-ltr">{s.phone || '—'}</td>
                <td>{s.status}</td>
                <td>
                  <span className={`badge badge-tier-${s.tier}`} title={TIER_LABEL[s.tier]}>
                    Tier {s.tier}
                  </span>
                </td>
                <td>
                  <span className="badge bg-light text-dark">
                    <i className={`bi ${s.location_source === 'google_places' ? 'bi-google' : 'bi-camera-video'} me-1`}></i>
                    {SRC_LABEL[s.location_source] || '—'}
                  </span>
                </td>
                <td className="num-ltr">
                  {s.location_accuracy_m != null ? `±${s.location_accuracy_m}م` : '—'}
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr><td colSpan="8" className="text-center text-muted py-4">مفيش نتايج مطابقة</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <hr className="my-4" />

      {/* Actions */}
      <div className="row g-3">
        <div className="col-md-6">
          <div className="card border-0 shadow-sm h-100">
            <div className="card-body">
              <h6 className="fw-bold">
                <i className="bi bi-file-earmark-excel text-success me-1"></i> تحميل النتايج
              </h6>
              <p className="small text-muted mb-3">
                Excel v6 الكامل بكل الأعمدة والألوان والمصادر (نفس شكل الـ output_v6).
              </p>
              <div className="d-flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn btn-brand"
                  disabled={Boolean(downloadBusy)}
                  onClick={() => handleDownload('excel')}
                >
                  {downloadBusy === 'excel' && (
                    <span className="spinner-border spinner-border-sm me-2" />
                  )}
                  <i className="bi bi-file-earmark-excel me-1"></i> Excel كامل (v6)
                </button>
                <button
                  type="button"
                  className="btn btn-outline-success"
                  disabled={Boolean(downloadBusy)}
                  onClick={() => handleDownload('csv')}
                  title="اسم المتجر، الإحداثيات، التصنيف، الهاتف، الشارع، المدينة، الحي"
                >
                  {downloadBusy === 'csv' && (
                    <span className="spinner-border spinner-border-sm me-2" />
                  )}
                  <i className="bi bi-filetype-csv me-1"></i> CSV للبرنامج الآخر
                </button>
              </div>
              {downloadError && (
                <div className="alert alert-danger small mt-3 mb-0">
                  <i className="bi bi-exclamation-triangle me-1"></i>
                  {downloadError}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="col-md-6">
          <div className="card border-0 shadow-sm h-100">
            <div className="card-body">
              <h6 className="fw-bold">
                <i className="bi bi-fire text-danger me-1"></i> رفع لـ Firestore
                {fbReady === false && <span className="badge bg-secondary ms-2">غير متصل</span>}
                {fbReady === true && <span className="badge bg-success ms-2">متصل</span>}
              </h6>
              <p className="small text-muted mb-3">
                {approvedItems.length > 0
                  ? `${approvedItems.length} متجر بعد المراجعة جاهز للرفع`
                  : `هيرفع ${stores.filter(s => s.tier <= 2).length} متجر (Tier 1 و 2) تلقائي`}
              </p>
              <button
                className="btn btn-success"
                disabled={pushing || !fbReady || stores.length === 0}
                onClick={handlePushFirebase}
              >
                {pushing ? (
                  <><span className="spinner-border spinner-border-sm me-2" /> جاري الرفع...</>
                ) : (
                  <><i className="bi bi-cloud-upload me-1"></i> ارفع لـ Firestore</>
                )}
              </button>
              {pushResult && (
                <div className="alert alert-success small mt-3 mb-0 py-2">
                  <i className="bi bi-check-circle me-1"></i>
                  اترفع {pushResult.written} متجر في collection <code>{pushResult.collection}</code>
                  {pushResult.skipped > 0 && <> · تخطّى {pushResult.skipped}</>}
                </div>
              )}
              {pushError && (
                <div className="alert alert-danger small mt-3 mb-0 py-2">
                  <i className="bi bi-exclamation-triangle me-1"></i> {pushError}
                </div>
              )}
            </div>
          </div>
        </div>

        {TRADERS_ENABLED && <div className="col-12">
          <div className="card border-0 shadow-sm">
            <div className="card-body">
              <h6 className="fw-bold">
                <i className="bi bi-link-45deg text-primary me-1"></i> ربط مع البرنامج التاني (traders-data-live)
                {tradersReady === false && <span className="badge bg-secondary ms-2">غير متصل</span>}
                {tradersReady === true && <span className="badge bg-success ms-2">متصل</span>}
              </h6>
              <p className="small text-muted mb-3">
                هتم تحويل بيانات المتاجر لـ schema <code>stores</code> الخاصة بـ <code>traders-data-live</code>.
                اضغطي <strong>معاينة</strong> الأول عشان تشوفي الشكل قبل الرفع. <strong>{eligibleForTraders.length}</strong> متجر مؤهلين للرفع (مستبعد منهم اللي AI صنّفهم OCR errors).
              </p>

              <div className="d-flex flex-wrap gap-2">
                <button
                  className="btn btn-outline-primary"
                  disabled={tradersBusy || !tradersReady || eligibleForTraders.length === 0}
                  onClick={handleTradersPreview}
                >
                  {tradersBusy && !tradersPreview ? (
                    <><span className="spinner-border spinner-border-sm me-2" /> جاري المعاينة...</>
                  ) : (
                    <><i className="bi bi-eye me-1"></i> معاينة قبل الرفع</>
                  )}
                </button>

                {tradersPreview && (
                  <button
                    className="btn btn-primary"
                    disabled={tradersBusy}
                    onClick={handleTradersPushConfirm}
                  >
                    {tradersBusy ? (
                      <><span className="spinner-border spinner-border-sm me-2" /> جاري الرفع...</>
                    ) : (
                      <><i className="bi bi-cloud-upload me-1"></i> تأكيد الرفع ({tradersPreview.count})</>
                    )}
                  </button>
                )}

                {tradersPreview && (
                  <button
                    className="btn btn-outline-secondary btn-sm"
                    onClick={() => setTradersPreview(null)}
                  >
                    <i className="bi bi-x"></i> إلغاء المعاينة
                  </button>
                )}
              </div>

              {tradersPreview && (
                <div className="mt-3">
                  <div className="alert alert-info small mb-2">
                    <i className="bi bi-info-circle me-1"></i>
                    معاينة لـ <strong>{tradersPreview.count}</strong> متجر — هتتكتب في <code>{tradersPreview.project} / {tradersPreview.collection}</code>
                  </div>
                  <details>
                    <summary className="small fw-semibold text-muted">شوفي أول document بالكامل</summary>
                    <pre className="bg-dark text-light p-3 rounded mt-2 small"
                         style={{ maxHeight: 300, overflowY: 'auto', direction: 'ltr', textAlign: 'left' }}>
{JSON.stringify(tradersPreview.documents[0], null, 2)}
                    </pre>
                  </details>
                </div>
              )}

              {tradersResult && (
                <div className="alert alert-success small mt-3 mb-0">
                  <i className="bi bi-check-circle me-1"></i>
                  اترفع <strong>{tradersResult.written}</strong> متجر بنجاح في{' '}
                  <code>{tradersResult.project} / {tradersResult.collection}</code>
                  {tradersResult.skipped > 0 && <> · تخطّى {tradersResult.skipped}</>}
                </div>
              )}

              {tradersError && (
                <div className="alert alert-danger small mt-3 mb-0">
                  <i className="bi bi-exclamation-triangle me-1"></i> {tradersError}
                </div>
              )}
            </div>
          </div>
        </div>}
      </div>

      <hr className="my-4" />

      <div className="d-flex flex-wrap gap-2 align-items-center">
        <button
          className="btn btn-outline-warning"
          onClick={handleDeleteVideo}
          disabled={videoState !== 'present'}
        >
          {videoState === 'deleting' && <><span className="spinner-border spinner-border-sm me-2" /> جاري الحذف...</>}
          {videoState === 'present' && <><i className="bi bi-trash me-1"></i> احذف ملف الفيديو</>}
          {videoState === 'deleted' && <><i className="bi bi-check2 me-1"></i> اتمسح</>}
          {videoState === 'error' && <><i className="bi bi-x-circle me-1"></i> فشل الحذف</>}
        </button>
        {videoState === 'error' && (
          <span className="small text-danger">{videoError}</span>
        )}

        <button className="btn btn-outline-primary" onClick={() => navigate('/review')}>
          <i className="bi bi-clipboard-check me-1"></i> صفحة المراجعة
        </button>

        <button
          className="btn btn-outline-danger ms-auto"
          onClick={() => { resetAll(); navigate('/upload') }}
        >
          <i className="bi bi-arrow-counterclockwise me-1"></i> تحليل فيديو جديد
        </button>
      </div>
    </div>
  )
}
