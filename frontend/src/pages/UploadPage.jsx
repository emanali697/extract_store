import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/appStore'
import {
  createJob,
  isLocalBackend,
  startJob,
  uploadVideoToBackend,
} from '../services/api'
import { uploadVideoToStorage, isFirebaseReady } from '../services/firestoreService'
import StageList from '../components/StageList'

const ACCEPT = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/x-matroska']
const MAX_BYTES = 5 * 1024 * 1024 * 1024 // 5 GB

function humanSize(bytes) {
  const mb = bytes / (1024 * 1024)
  return mb < 1024 ? `${mb.toFixed(1)} MB` : `${(mb / 1024).toFixed(2)} GB`
}

export default function UploadPage() {
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const {
    videoFile, videoName, videoSizeMb,
    uploadStatus, uploadProgress, uploadError,
    streetName, city, district, speedMode, enablePlaces, enableStatus,
    setVideo, clearVideo,
    setUploadStatus, setUploadProgress,
    startAnalysis,
  } = useAppStore()

  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [startStep, setStartStep] = useState('')

  const handleFile = (file) => {
    if (!file) return
    setError('')
    if (file.size > MAX_BYTES) {
      setError(`الفيديو أكبر من 5 GB (الحجم الحالي: ${humanSize(file.size)})`)
      return
    }
    if (ACCEPT.length && !ACCEPT.includes(file.type) && !/\.(mp4|mov|avi|mkv)$/i.test(file.name)) {
      setError('نوع الملف غير مدعوم. الأنواع المدعومة: MP4, MOV, AVI, MKV')
      return
    }
    setVideo({ file, name: file.name, sizeMb: file.size / (1024 * 1024) })
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    handleFile(e.dataTransfer.files?.[0])
  }

  const canStart = !!videoFile && !!streetName.trim() && !starting

  const handleStart = async () => {
    setError('')
    setStarting(true)
    setStartStep('creating')
    try {
      if (!isLocalBackend && !isFirebaseReady()) {
        throw new Error('Firebase not initialized. Check VITE_FIREBASE_* env vars.')
      }

      if (isLocalBackend) {
        // FastAPI receives the complete video first. POST /jobs starts analysis
        // only after /upload has returned successfully.
        setStartStep('uploading')
        setUploadStatus('uploading')
        const uploaded = await uploadVideoToBackend(videoFile, {
          onProgress: (pct) => setUploadProgress(pct),
        })
        setUploadStatus('done')

        setStartStep('starting')
        const { jobId } = await createJob({
          videoPath: uploaded.path,
          streetName,
          city,
          district,
          speedMode,
          enablePlaces,
          enableStatus,
        })
        startAnalysis(jobId)
        navigate('/progress')
        return
      }

      // 1. Create job first so we know the jobId
      const { jobId } = await createJob({
        videoName,
        streetName,
        city,
        district,
        speedMode,
        enablePlaces,
        enableStatus,
      })

      // 2. Upload video to Firebase Storage
      setStartStep('uploading')
      setUploadStatus('uploading')
      await uploadVideoToStorage(videoFile, jobId, {
        onProgress: (pct) => setUploadProgress(pct),
      })
      setUploadStatus('done')

      // 3. Start the pipeline
      setStartStep('starting')
      await startJob({ jobId })
      startAnalysis(jobId)
      navigate('/progress')
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || 'فشل بدء التحليل'
      setError(msg)
      setUploadStatus('error', msg)
    } finally {
      setStarting(false)
      setStartStep('')
    }
  }

  return (
    <div>
      <h2 className="section-title">
        <i className="bi bi-cloud-arrow-up me-2"></i> ارفع فيديو الشارع
      </h2>

      <div
        className={`dropzone ${dragOver ? 'dragover' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
      >
        <div className="dropzone-icon">
          <i className="bi bi-cloud-arrow-up-fill"></i>
        </div>
        <div className="dropzone-title">اسحب ملف الفيديو هنا أو اضغط للاختيار</div>
        <div className="dropzone-hint">
          الأنواع المدعومة: MP4, MOV, AVI, MKV — الحد الأقصى 5 GB (يناسب فيديوهات 4K)
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".mp4,.mov,.avi,.mkv,video/*"
          className="d-none"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>

      {error && (
        <div className="alert alert-danger mt-3" role="alert">
          <i className="bi bi-exclamation-triangle me-2"></i>{error}
        </div>
      )}

      {videoFile && (
        <div className="alert alert-light border mt-3" role="alert">
          <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
            <div>
              <i className="bi bi-film me-2"></i>
              <strong>{videoName}</strong>
              <span className="text-muted ms-2">
                ({videoSizeMb < 1024 ? `${videoSizeMb.toFixed(1)} MB` : `${(videoSizeMb / 1024).toFixed(2)} GB`})
              </span>
            </div>
            {uploadStatus !== 'uploading' && (
              <button className="btn btn-sm btn-outline-secondary" onClick={clearVideo}>
                <i className="bi bi-x-circle"></i> إزالة
              </button>
            )}
          </div>

          {uploadStatus === 'uploading' && (
            <>
              <div className="mt-2 small">
                <i className="bi bi-arrow-up-circle me-1"></i>
                جاري الرفع... <span className="num-ltr">{Math.round(uploadProgress * 100)}%</span>
              </div>
              <div className="progress mt-1" style={{ height: 8 }}>
                <div
                  className="progress-bar progress-bar-striped progress-bar-animated"
                  style={{ width: `${uploadProgress * 100}%` }}
                />
              </div>
            </>
          )}

          {uploadStatus === 'done' && (
            <div className="mt-2 small text-success">
              <i className="bi bi-check-circle me-1"></i>
              تم الرفع للسيرفر بنجاح
            </div>
          )}

          {uploadStatus === 'error' && (
            <div className="mt-2 small text-danger">
              <i className="bi bi-exclamation-triangle me-1"></i>
              {uploadError || 'فشل الرفع'}
            </div>
          )}
        </div>
      )}

      <h2 className="section-title">
        <i className="bi bi-list-check me-2"></i> الخطوات اللي هتحصل
      </h2>
      <StageList />

      <hr className="my-4" />

      {!streetName.trim() && (
        <div className="alert alert-warning" role="alert">
          <i className="bi bi-exclamation-circle me-2"></i>
          من فضلك أدخل <strong>اسم الشارع</strong> في الشريط الجانبي
        </div>
      )}

      <div className="d-flex flex-wrap gap-3 align-items-center">
        <button
          className="btn btn-brand btn-lg px-4"
          disabled={!canStart}
          onClick={handleStart}
        >
          {starting ? (
            <>
              <span className="spinner-border spinner-border-sm me-2" />
              {startStep === 'uploading' && 'جاري رفع الفيديو كاملًا...'}
              {startStep === 'starting' && 'تم الرفع — جاري بدء التحليل...'}
              {startStep === 'creating' && 'جاري تجهيز مهمة التحليل...'}
            </>
          ) : (
            <>
              <i className="bi bi-play-fill me-1"></i> ابدأ التحليل
            </>
          )}
        </button>
        {canStart && (
          <span className="text-muted small">
            <i className="bi bi-info-circle me-1"></i>
            اضغط لبدء التحليل، وانتقل لتبويب <strong>التقدم</strong> لمتابعة الحالة
          </span>
        )}
      </div>
    </div>
  )
}
