import axios from 'axios'

const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID || 'store-extract'
const productionDefault = `https://us-central1-${projectId}.cloudfunctions.net`
const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL
  || (import.meta.env.PROD ? productionDefault : 'http://localhost:8000')
).replace(/\/$/, '')

export const isLocalBackend = /^https?:\/\/(localhost|127\.0\.0\.1):8000$/i.test(BASE_URL)

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60_000,
})

function normalizeJob(job = {}) {
  const storagePath = job.video_storage_path || ''
  return {
    ...job,
    jobId: job.jobId || job.job_id,
    videoName: job.videoName || job.video_name || storagePath.split('/').pop() || '',
    streetName: job.streetName || job.street_name || '',
    speedMode: job.speedMode || job.speed_mode || 'auto',
    enablePlaces: job.enablePlaces ?? job.enable_places ?? true,
    enableStatus: job.enableStatus ?? job.enable_status ?? true,
    hasResults: job.hasResults ?? job.has_results ?? Boolean(job.results),
  }
}

/* ----------  Firebase Functions endpoints  ---------- */

export async function createJob(settings) {
  const endpoint = isLocalBackend ? '/jobs' : '/create_job'
  const res = await api.post(endpoint, settings)
  return res.data
}

export async function startJob({ jobId }) {
  if (isLocalBackend) {
    // FastAPI starts the pipeline as part of POST /jobs.
    return { jobId, status: 'queued' }
  }
  const res = await api.post('/start_job', { jobId })
  return res.data
}

export async function fetchAllJobs(limit = 20) {
  const endpoint = isLocalBackend ? '/jobs' : '/list_jobs_fn'
  const res = await api.get(endpoint, { params: { limit } })
  return (res.data?.jobs ?? []).map(normalizeJob)
}

export async function fetchJobStatus(jobId) {
  const endpoint = isLocalBackend ? `/jobs/${jobId}` : `/get_job_fn/${jobId}`
  const res = await api.get(endpoint)
  return normalizeJob(res.data)
}

export async function fetchResults(jobId) {
  const endpoint = isLocalBackend
    ? `/jobs/${jobId}/results`
    : `/get_results/${jobId}`
  const res = await api.get(endpoint)
  return res.data
}

export async function fetchReviewQueue(jobId) {
  const endpoint = isLocalBackend
    ? `/jobs/${jobId}/review`
    : `/get_review/${jobId}`
  const res = await api.get(endpoint)
  return res.data
}

export async function approveStores(jobId, stores) {
  const endpoint = isLocalBackend
    ? `/jobs/${jobId}/approve`
    : `/approve_stores/${jobId}`
  const res = await api.post(endpoint, { stores })
  return res.data
}

export async function previewTradersPush(jobId, stores) {
  const endpoint = isLocalBackend
    ? `/jobs/${jobId}/traders/preview`
    : `/traders_preview/${jobId}`
  const res = await api.post(endpoint, { stores })
  return res.data
}

export async function pushToTraders(jobId, stores) {
  const endpoint = isLocalBackend
    ? `/jobs/${jobId}/traders/push`
    : `/traders_push/${jobId}`
  const res = await api.post(endpoint, { stores })
  return res.data
}

export async function deleteVideo(jobId) {
  const endpoint = isLocalBackend
    ? `/jobs/${jobId}/video`
    : `/delete_video/${jobId}`
  const res = await api.delete(endpoint)
  return res.data
}

export async function fetchHealth() {
  const res = await api.get('/health')
  return res.data
}

export async function getSignImageUrl(jobId, filename) {
  if (isLocalBackend) {
    return `${BASE_URL}/jobs/${jobId}/sign/${encodeURIComponent(filename)}`
  }
  const res = await api.get(`/get_sign/${jobId}/${filename}`)
  return res.data.imageUrl
}

export async function downloadExcelUrl(jobId) {
  if (isLocalBackend) {
    return `${BASE_URL}/jobs/${jobId}/excel`
  }
  const res = await api.get(`/export_excel/${jobId}`)
  return res.data.downloadUrl
}

export async function downloadCsvUrl(jobId) {
  if (isLocalBackend) {
    return `${BASE_URL}/jobs/${jobId}/export.csv`
  }
  const res = await api.get(`/export_csv/${jobId}`)
  return res.data.downloadUrl
}

export async function uploadVideoToBackend(file, { onProgress } = {}) {
  const form = new FormData()
  form.append('file', file)
  const res = await api.post('/upload', form, {
    timeout: 0,
    onUploadProgress: (event) => {
      if (!event.total) return
      onProgress?.(event.loaded / event.total)
    },
  })
  return res.data
}
