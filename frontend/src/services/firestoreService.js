import {
  ref,
  uploadBytesResumable,
} from 'firebase/storage'
import {
  doc,
  onSnapshot,
  Timestamp,
} from 'firebase/firestore'
import { firebaseStorage, firebaseFirestore, firebaseReady } from './firebase'

export function isFirebaseReady() {
  return firebaseReady && firebaseStorage && firebaseFirestore
}

const MULTIPART_THRESHOLD = 64 * 1024 * 1024

function reportAggregateProgress(transferred, total, startedAt, samples, onProgress) {
  const now = performance.now()
  samples.push({ at: now, bytes: transferred })
  while (samples.length > 2 && now - samples[0].at > 10_000) samples.shift()
  const first = samples[0]
  const seconds = Math.max((now - first.at) / 1000, 0.25)
  const speedBps = Math.max(0, (transferred - first.bytes) / seconds)
  const etaSeconds = speedBps > 0 ? Math.max(0, (total - transferred) / speedBps) : null
  onProgress?.({
    progress: total ? transferred / total : 0,
    bytesTransferred: transferred,
    totalBytes: total,
    speedBps,
    etaSeconds,
    elapsedSeconds: (now - startedAt) / 1000,
  })
}

export function uploadVideoToStorage(file, jobId, { onProgress } = {}) {
  if (!firebaseStorage) {
    throw new Error('Firebase Storage not initialized')
  }
  const contentType = file.type || 'video/mp4'
  const partCount = file.size < MULTIPART_THRESHOLD
    ? 1
    : file.size >= 1024 * 1024 * 1024 ? 8 : 4
  const partSize = Math.ceil(file.size / partCount)
  const transferredByPart = Array(partCount).fill(0)
  const tasks = []
  const samples = []
  const startedAt = performance.now()

  const promises = Array.from({ length: partCount }, (_, index) => {
    const start = index * partSize
    const end = Math.min(file.size, start + partSize)
    const part = file.slice(start, end, contentType)
    const storagePath = partCount === 1
      ? `jobs/${jobId}/video.mp4`
      : `jobs/${jobId}/upload_parts/part_${String(index).padStart(2, '0')}`
    const task = uploadBytesResumable(ref(firebaseStorage, storagePath), part, { contentType })
    tasks.push(task)

    return new Promise((resolve, reject) => {
      task.on(
        'state_changed',
        (snapshot) => {
          transferredByPart[index] = snapshot.bytesTransferred
          const transferred = transferredByPart.reduce((sum, bytes) => sum + bytes, 0)
          reportAggregateProgress(transferred, file.size, startedAt, samples, onProgress)
        },
        reject,
        () => resolve(task.snapshot.ref.fullPath)
      )
    })
  })

  const promise = Promise.all(promises)
    .then((paths) => ({
      path: partCount === 1 ? paths[0] : null,
      multipart: partCount > 1,
      partCount,
    }))
    .catch((error) => {
      tasks.forEach((task) => task.cancel())
      throw error
    })
  promise.pause = () => tasks.forEach((task) => task.pause())
  promise.resume = () => tasks.forEach((task) => task.resume())
  promise.cancel = () => tasks.forEach((task) => task.cancel())
  return promise
}

export function subscribeToJob(jobId, { onEvent, onError } = {}) {
  if (!firebaseFirestore) {
    throw new Error('Firebase Firestore not initialized')
  }
  const jobRef = doc(firebaseFirestore, 'jobs', jobId)
  return onSnapshot(
    jobRef,
    (snapshot) => {
      const data = snapshot.data()
      if (!data) return
      onEvent?.({ type: 'snapshot', data })
    },
    (error) => onError?.(error)
  )
}

export function firestoreTimestampToDate(ts) {
  if (!ts) return null
  if (ts instanceof Timestamp) return ts.toDate()
  if (ts.toDate) return ts.toDate()
  return new Date(ts)
}
