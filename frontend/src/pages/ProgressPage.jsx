import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/appStore'
import StageList from '../components/StageList'
import { STAGES } from '../data/stages'
import { subscribeToJob } from '../services/firestoreService'
import { fetchJobStatus, fetchResults } from '../services/api'

export default function ProgressPage() {
  const navigate = useNavigate()
  const {
    jobId, analysisStarted, analysisDone,
    analysisStatus, analysisError,
    videoName, videoSizeMb, streetName,
    stageStatus,
    updateStage, finishAnalysis, setReviewItems, setAnalysisState,
  } = useAppStore()

  const [logLines, setLogLines] = useState([])
  const [connectionState, setConnectionState] = useState('connecting')

  useEffect(() => {
    if (!analysisStarted || !jobId) return
    if (import.meta.env.VITE_ENABLE_FIRESTORE_REALTIME !== 'true') return

    let unsub
    try {
      unsub = subscribeToJob(jobId, {
        onEvent: async (evt) => {
          const data = evt.data
          if (!data) return

          setConnectionState('open')
          setAnalysisState(data.status || 'queued', data.error || '')

          // Update stages from Firestore document
          const stages = data.stages || {}
          Object.entries(stages).forEach(([idx, entry]) => {
            updateStage(Number(idx), {
              status: entry.status,
              current: entry.current ?? undefined,
              total: entry.total ?? undefined,
              phase: entry.phase ?? undefined,
            })
          })

          // Update logs
          const logs = data.log_lines || []
          if (logs.length) {
            setLogLines(logs.slice(-200))
          }

          if (data.status === 'error' && data.error) {
            setLogLines((prev) => {
              const line = `ERROR: ${data.error}`
              return prev.at(-1) === line ? prev : [...prev.slice(-199), line]
            })
          }

          // Update status and results
          if (
            ['done', 'partial'].includes(data.status)
            && !useAppStore.getState().analysisDone
          ) {
            const results = data.results || await fetchResults(jobId)
            finishAnalysis(results, data.status)
            setReviewItems(results?.review ?? [])
          }
        },
        onError: (error) => {
          setConnectionState('error')
          setLogLines((prev) => [
            ...prev.slice(-199),
            `Firestore: ${error?.message || 'تعذر الاتصال المباشر — المتابعة الاحتياطية مستمرة'}`,
          ])
        },
      })
    } catch (error) {
      queueMicrotask(() => {
        setConnectionState('error')
        setLogLines((prev) => [
          ...prev.slice(-199),
          `Firestore: ${error?.message || 'تعذر بدء المتابعة المباشرة — المتابعة الاحتياطية مستمرة'}`,
        ])
      })
    }

    return () => unsub?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisStarted, jobId])

  useEffect(() => {
    if (!analysisStarted || !jobId || analysisDone) return

    let stopped = false
    let pollTimer

    const pollJob = async () => {
      try {
        const data = await fetchJobStatus(jobId)
        if (stopped || !data) return

        setConnectionState('open')
        setAnalysisState(data.status || 'queued', data.error || '')

        Object.entries(data.stages || {}).forEach(([idx, entry]) => {
          updateStage(Number(idx), {
            status: entry.status,
            current: entry.current ?? undefined,
            total: entry.total ?? undefined,
            phase: entry.phase ?? undefined,
          })
        })

        const logs = data.log_lines || []
        if (logs.length) {
          setLogLines(logs.slice(-200))
        }

        if (
          ['done', 'partial'].includes(data.status)
          && !useAppStore.getState().analysisDone
        ) {
          const results = data.results || await fetchResults(jobId)
          finishAnalysis(results, data.status)
          setReviewItems(results?.review ?? [])
        }

        if (['done', 'partial', 'error'].includes(data.status) && pollTimer) {
          window.clearInterval(pollTimer)
        }
      } catch (error) {
        if (!stopped) {
          setLogLines((prev) => [
            ...prev.slice(-199),
            `ERROR: ${error?.message || 'تعذر متابعة حالة التحليل'}`,
          ])
        }
      }
    }

    pollTimer = window.setInterval(pollJob, 2000)
    void pollJob()

    return () => {
      stopped = true
      window.clearInterval(pollTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisStarted, analysisDone, jobId])

  if (!analysisStarted) {
    return (
      <div className="alert alert-info" role="alert">
        <i className="bi bi-info-circle me-2"></i>
        ارفع فيديو من تبويب <strong>رفع الفيديو</strong> ثم اضغط ابدأ التحليل
      </div>
    )
  }

  const doneCount = Object.values(stageStatus).filter((s) => ['done', 'skipped'].includes(s)).length
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

  const jobState = {
    partial: { label: 'اكتمل جزئيًا — بعض الخدمات لم تعمل', cls: 'bg-warning text-dark' },
    uploading: { label: 'جاري رفع الفيديو', cls: 'bg-secondary' },
    queued: { label: 'في انتظار بدء التحليل', cls: 'bg-info text-dark' },
    running: { label: 'جاري التحليل', cls: 'bg-warning text-dark' },
    finalizing: { label: 'جاري رفع وتجهيز النتائج', cls: 'bg-primary' },
    done: { label: 'اكتمل التحليل', cls: 'bg-success' },
    error: { label: 'فشل التحليل', cls: 'bg-danger' },
  }[analysisStatus] ?? { label: analysisStatus, cls: 'bg-secondary' }

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

      <div className="mt-3 mb-2">
        <span className={`badge ${jobState.cls} px-3 py-2`}>
          {analysisStatus === 'running' && (
            <span className="spinner-border spinner-border-sm me-2" />
          )}
          {jobState.label}
        </span>
      </div>

      {analysisError && (
        <div className="alert alert-danger mt-3" role="alert">
          <i className="bi bi-exclamation-triangle me-2"></i>
          <strong>توقف التحليل:</strong> {analysisError}
        </div>
      )}

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
