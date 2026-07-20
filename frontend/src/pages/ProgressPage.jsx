import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/appStore'
import StageList from '../components/StageList'
import { STAGES } from '../data/stages'
import { openProgressSocket } from '../services/api'

export default function ProgressPage() {
  const navigate = useNavigate()
  const {
    jobId, analysisStarted, analysisDone,
    videoName, videoSizeMb, streetName,
    stageStatus,
    updateStage, finishAnalysis, setReviewItems,
  } = useAppStore()

  const wsRef = useRef(null)
  const [logLines, setLogLines] = useState([])
  const [connectionState, setConnectionState] = useState('connecting')

  useEffect(() => {
    if (!analysisStarted || !jobId) return

    let cancelled = false

    const ws = openProgressSocket(jobId, {
      onEvent: (evt) => {
        if (cancelled) return
        if (evt.type === 'stage') {
          updateStage(evt.stage, {
            status: evt.status,
            current: evt.current ?? undefined,
            total: evt.total ?? undefined,
          })
        } else if (evt.type === 'log') {
          setLogLines((prev) => {
            const next = [...prev, evt.line]
            return next.length > 200 ? next.slice(-200) : next
          })
        } else if (evt.type === 'results') {
          finishAnalysis(evt.results)
          setReviewItems(evt.results?.review ?? [])
        } else if (evt.type === 'status') {
          if (evt.status === 'error') {
            setLogLines((p) => [...p, `❌ ${evt.error || 'error'}`])
          }
        }
      },
      onError: () => !cancelled && setConnectionState('error'),
      onClose: () => !cancelled && setConnectionState('closed'),
    })

    wsRef.current = ws
    ws.addEventListener('open', () => !cancelled && setConnectionState('open'))

    return () => {
      cancelled = true
      const sock = wsRef.current
      wsRef.current = null
      if (!sock) return
      // If the socket is still CONNECTING (StrictMode double-mount in dev),
      // schedule the close for when it opens instead of yanking it mid-handshake.
      if (sock.readyState === WebSocket.CONNECTING) {
        sock.addEventListener('open', () => sock.close(), { once: true })
      } else if (sock.readyState === WebSocket.OPEN) {
        sock.close()
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisStarted, jobId])

  if (!analysisStarted) {
    return (
      <div className="alert alert-info" role="alert">
        <i className="bi bi-info-circle me-2"></i>
        ارفع فيديو من تبويب <strong>رفع الفيديو</strong> ثم اضغط ابدأ التحليل
      </div>
    )
  }

  const doneCount = Object.values(stageStatus).filter((s) => s === 'done').length
  const totalStages = STAGES.length
  const pct = Math.round((doneCount / totalStages) * 100)

  const sizeStr = videoSizeMb < 1024
    ? `${videoSizeMb.toFixed(0)} MB`
    : `${(videoSizeMb / 1024).toFixed(2)} GB`

  const conn = {
    connecting: { label: 'بيتصل...', cls: 'bg-secondary' },
    open:       { label: 'متصل',    cls: 'bg-success' },
    closed:     { label: 'انقطع',   cls: 'bg-warning' },
    error:      { label: 'خطأ',     cls: 'bg-danger' },
  }[connectionState] ?? { label: connectionState, cls: 'bg-secondary' }

  return (
    <div>
      <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
        <h2 className="section-title mb-0">
          <i className="bi bi-lightning-charge me-2"></i> متابعة التقدم
        </h2>
        <span className={`badge ${conn.cls}`}>
          <i className="bi bi-broadcast me-1"></i> {conn.label}
        </span>
      </div>

      <div className="row g-3 mb-3 mt-1">
        <div className="col-md-4">
          <div className="stat-card">
            <div className="stat-num"><i className="bi bi-film"></i></div>
            <div className="stat-label text-truncate" title={videoName}>{videoName || '—'}</div>
          </div>
        </div>
        <div className="col-md-4">
          <div className="stat-card">
            <div className="stat-num num-ltr">{sizeStr}</div>
            <div className="stat-label">حجم الفيديو</div>
          </div>
        </div>
        <div className="col-md-4">
          <div className="stat-card">
            <div className="stat-num">{streetName || '—'}</div>
            <div className="stat-label">الشارع</div>
          </div>
        </div>
      </div>

      <div className="mb-2 d-flex justify-content-between small fw-semibold">
        <span>التقدم الإجمالي</span>
        <span><span className="num-ltr">{doneCount}</span> / <span className="num-ltr">{totalStages}</span> مراحل</span>
      </div>
      <div className="progress mb-4" style={{ height: 12 }}>
        <div
          className="progress-bar"
          role="progressbar"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(135deg, #1F4E79 0%, #2E75B6 100%)',
          }}
          aria-valuenow={pct}
          aria-valuemin="0"
          aria-valuemax="100"
        />
      </div>

      <h5 className="mb-3">المراحل</h5>
      <StageList />

      <details className="mt-4">
        <summary className="fw-semibold text-muted">📋 سجل التشغيل (آخر 200 سطر)</summary>
        <pre
          className="bg-dark text-light p-3 rounded mt-2 small"
          style={{ maxHeight: 280, overflowY: 'auto', direction: 'ltr', textAlign: 'left' }}
        >
{logLines.length ? logLines.join('\n') : 'في انتظار أول سطر من السيرفر...'}
        </pre>
      </details>

      {analysisDone && (
        <div className="alert alert-success mt-4 d-flex align-items-center justify-content-between flex-wrap gap-2">
          <div>
            <i className="bi bi-check-circle-fill me-2"></i>
            اكتمل التحليل!
          </div>
          <div className="d-flex gap-2">
            <button className="btn btn-outline-warning" onClick={() => navigate('/review')}>
              <i className="bi bi-clipboard-check me-1"></i> اذهب للمراجعة
            </button>
            <button className="btn btn-brand" onClick={() => navigate('/results')}>
              <i className="bi bi-table me-1"></i> عرض النتائج
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
