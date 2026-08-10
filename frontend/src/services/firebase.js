import { initializeApp, getApps } from 'firebase/app'
import { getStorage } from 'firebase/storage'
import { getFirestore, initializeFirestore } from 'firebase/firestore'

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

export const firebaseReady = Boolean(firebaseConfig.apiKey && firebaseConfig.projectId)

export const firebaseApp = firebaseReady
  ? (getApps()[0] ?? initializeApp(firebaseConfig))
  : null

export const firebaseStorage = firebaseApp ? getStorage(firebaseApp) : null

function createFirestore(app) {
  try {
    return initializeFirestore(app, {
      experimentalForceLongPolling: true,
    })
  } catch (error) {
    // Vite HMR can reuse an instance initialized by the previous module load.
    if (error?.code === 'failed-precondition') return getFirestore(app)
    throw error
  }
}

export const firebaseFirestore = firebaseApp ? createFirestore(firebaseApp) : null
