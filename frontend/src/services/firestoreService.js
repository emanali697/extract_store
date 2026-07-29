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

export function uploadVideoToStorage(file, jobId, { onProgress } = {}) {
  if (!firebaseStorage) {
    throw new Error('Firebase Storage not initialized')
  }
  const storageRef = ref(firebaseStorage, `jobs/${jobId}/video.mp4`)
  const task = uploadBytesResumable(storageRef, file, {
    contentType: file.type || 'video/mp4',
  })

  return new Promise((resolve, reject) => {
    task.on(
      'state_changed',
      (snapshot) => {
        const progress = snapshot.bytesTransferred / snapshot.totalBytes
        onProgress?.(progress)
      },
      (error) => reject(error),
      () => resolve(task.snapshot.ref.fullPath)
    )
  })
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
