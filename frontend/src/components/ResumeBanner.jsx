import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/appStore'
import { fetchAllJobs, fetchResults } from '../services/api'

const STATUS_LABEL = {
  partial:     { text: 'مكتمل جزئيًا', cls: 'bg-warning text-dark' },
  uploading:   { text: 'في انتظار اكتمال الرفع', cls: 'bg-secondary' },
  running:     { text: 'شغّال دلوقتي', cls: 'bg-warning text-dark' },
  finalizing:  { text: 'جاري تجهيز النتائج', cls: 'bg-primary' },
  done:        { text: 'مكتمل',         cls: 'bg-success' },
  interrupted: { text: 'انقطع',         cls: 'bg-secondary' },
  error:       { text: 'خطأ',           cls: 'bg-danger' },
  queued:      { text: 'في الانتظار',   cls: 'bg-info text-dark' },
}

function pickPriority(jobs) {
  // Order: running > interrupted > done > error > queued
  const priority = { running: 7, finalizing: 6, queued: 5, interrupted: 4, partial: 3, done: 2, error: 1, uploading: 0 }
  return [...jobs].sort((a, b) =>
    (priority[b.status] ?? 0) - (priority[a.status] ?? 0)
  )[0]
}

export default function ResumeBanner() {
  const navigate = useNavigate()
  const { jobId: currentJobId, resumeJob, finishAnalysis, setReviewItems } = useAppStore()
  const [pick, setPick] = useState(null)
  const [dismissed, setDismissed] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchAllJobs(20)
      .then((jobs) => {
        if (!Array.isArray(jobs) || jobs.length === 0) return
        const best = pickPriority(jobs)
        // Only surface if it isn't already the one in our store
        if (best && best.jobId !== currentJobId) {
          setPick(best)
        }
      })
      .catch(() => {/* backend down — banner stays hidden */})
    // run once on mount; we don't want it re-running on every store change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleResume = async () => {
    if (!pick) return
    setLoading(true)
    resumeJob(pick)

    // If the job already has results, pull them so the UI is fully populated
    if (pick.hasResults) {
      try {
        const results = await fetchResults(pick.jobId)
        finishAnalysis(results)
        setReviewItems(results?.review ?? [])
      } catch {/* ignore */}
    }

    setLoading(false)
    setDismissed(true)
    navigate(['done', 'partial'].includes(pick.status) ? '/results' : '/progress')
  }

  if (!pick || dismissed) return null

  const label = STATUS_LABEL[pick.status] ?? { text: pick.status, cls: 'bg-secondary' }
  const targetTab = pick.status === 'done' ? 'النتايج' : 'التقدم'

  return (
    <div className="alert alert-light border shadow-sm d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
      <div>
        <i className="bi bi-arrow-counterclockwise me-2 text-primary"></i>
        <strong>عندك تحليل سابق:</strong>{' '}
        <span className="num-ltr fw-semibold">{pick.videoName || pick.jobId}</span>{' '}
        {pick.streetName && <span className="text-muted">({pick.streetName})</span>}
        <span className={`badge ${label.cls} ms-2`}>{label.text}</span>
      </div>
      <div className="d-flex gap-2">
        <button
          className="btn btn-brand btn-sm"
          onClick={handleResume}
          disabled={loading}
        >
          {loading ? (
            <><span className="spinner-border spinner-border-sm me-1" /> جاري التحميل...</>
          ) : (
            <><i className="bi bi-box-arrow-in-right me-1"></i> استكمل في تبويب {targetTab}</>
          )}
        </button>
        <button
          className="btn btn-outline-secondary btn-sm"
          onClick={() => setDismissed(true)}
          title="إخفاء"
        >
          <i className="bi bi-x"></i>
        </button>
      </div>
    </div>
  )
}
