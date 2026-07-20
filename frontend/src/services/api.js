import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 600_000, // 10 min — uploads can be slow on big files
})

/* ----------  Backend endpoints  ---------- */

export async function uploadVideo(file, { onProgress } = {}) {
  const form = new FormData()
  form.append('file', file)
  const res = await api.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) onProgress(evt.loaded / evt.total)
    },
  })
  return res.data // { filename, path, size }
}

export async function createJob(settings) {
  const res = await api.post('/jobs', settings)
  return res.data // { jobId, status }
}

export async function fetchAllJobs(limit = 20) {
  const res = await api.get('/jobs', { params: { limit } })
  return res.data
}

export async function fetchJobStatus(jobId) {
  const res = await api.get(`/jobs/${jobId}`)
  return res.data
}

export async function fetchResults(jobId) {
  const res = await api.get(`/jobs/${jobId}/results`)
  return res.data
}

export async function fetchReviewQueue(jobId) {
  const res = await api.get(`/jobs/${jobId}/review`)
  return res.data
}

export async function approveStores(jobId, stores) {
  const res = await api.post(`/jobs/${jobId}/approve`, { stores })
  return res.data
}

export async function previewTradersPush(jobId, stores) {
  const res = await api.post(`/jobs/${jobId}/traders/preview`, { stores })
  return res.data
}

export async function pushToTraders(jobId, stores) {
  const res = await api.post(`/jobs/${jobId}/traders/push`, { stores })
  return res.data
}

export function downloadExcelUrl(jobId) {
  return `${BASE_URL}/jobs/${jobId}/excel`
}

export function downloadCsvUrl(jobId) {
  return `${BASE_URL}/jobs/${jobId}/export.csv`
}

export async function deleteVideo(jobId) {
  const res = await api.delete(`/jobs/${jobId}/video`)
  return res.data
}

export async function fetchHealth() {
  const res = await api.get('/health')
  return res.data
}

/* ----------  WebSocket  ---------- */

export function openProgressSocket(jobId, { onEvent, onError, onClose } = {}) {
  const wsUrl = BASE_URL.replace(/^http/, 'ws') + `/ws/progress/${jobId}`
  const ws = new WebSocket(wsUrl)
  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data)
      onEvent?.(data)
    } catch {
      onEvent?.({ type: 'raw', raw: evt.data })
    }
  }
  ws.onerror = (e) => onError?.(e)
  ws.onclose = (e) => onClose?.(e)
  return ws
}
