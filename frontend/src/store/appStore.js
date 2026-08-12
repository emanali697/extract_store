import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { STAGES } from '../data/stages'

const initialStageStatus = () =>
  Object.fromEntries(STAGES.map((_, i) => [i, 'pending']))

const initialStageProgress = () =>
  Object.fromEntries(STAGES.map((_, i) => [i, null]))

function storeIdForReview(itemOrId) {
  const value = typeof itemOrId === 'object'
    ? (itemOrId?.storeId ?? itemOrId?.id)
    : itemOrId
  const reviewMatch = String(value ?? '').match(/^r(\d+)$/)
  return reviewMatch ? Number(reviewMatch[1]) : value
}

function summarizeStores(previousSummary = {}, stores = [], reviewCount = 0) {
  return {
    ...previousSummary,
    total: stores.length,
    active: stores.filter((store) => (
      Number(store.tier) === 1 || String(store.status || '').includes('نشط')
    )).length,
    phones: stores.filter((store) => String(store.phone || '').trim()).length,
    precise: stores.filter((store) => store.lat != null || store.lng != null).length,
    needs_human: reviewCount,
  }
}

export const useAppStore = create(
  persist(
    (set, get) => ({
      // upload
      videoFile: null,         // NOT persisted — File can't be serialized
      videoName: '',
      videoSizeMb: 0,
      videoPath: '',           // server-side path returned by /upload
      uploadProgress: 0,       // 0..1
      uploadStatus: 'idle',    // idle | uploading | done | error
      uploadError: '',

      // settings
      city: 'جدة',
      streetName: '',
      district: '',
      speedMode: 'auto',
      enablePlaces: true,
      enableStatus: true,

      // analysis
      jobId: null,
      reviewToken: '',
      analysisStarted: false,
      analysisDone: false,
      analysisStatus: 'idle',
      analysisError: '',
      stageStatus: initialStageStatus(),
      stageProgress: initialStageProgress(),

      // results / review
      results: null,
      reviewItems: [],
      approvedItems: [],

      // setters
      setSettings: (partial) => set(partial),
      setVideo: ({ file, name, sizeMb }) =>
        set({
          videoFile: file,
          videoName: name,
          videoSizeMb: sizeMb,
          uploadProgress: 0,
          uploadStatus: 'idle',
          uploadError: '',
        }),
      clearVideo: () => set({
        videoFile: null, videoName: '', videoSizeMb: 0, videoPath: '',
        uploadProgress: 0, uploadStatus: 'idle', uploadError: '',
      }),

      setUploadProgress: (pct) => set({ uploadProgress: pct }),
      setUploadStatus: (status, error = '') => set({ uploadStatus: status, uploadError: error }),
      setVideoPath: (path) => set({ videoPath: path, uploadStatus: 'done' }),

      startAnalysis: (jobId, reviewToken = '') =>
        set({
          jobId,
          reviewToken,
          analysisStarted: true,
          analysisDone: false,
          analysisStatus: 'queued',
          analysisError: '',
          stageStatus: initialStageStatus(),
          stageProgress: initialStageProgress(),
          results: null,
          reviewItems: [],
          approvedItems: [],
        }),

      // Resume an existing backend job into the local store.
      resumeJob: ({ jobId, status, videoName, streetName, city, district }) =>
        set((prev) => ({
          jobId,
          reviewToken: prev.jobId === jobId ? prev.reviewToken : '',
          analysisStarted: true,
          analysisDone: status === 'done' || status === 'partial',
          analysisStatus: status,
          analysisError: '',
          videoName: videoName || prev.videoName,
          streetName: streetName || prev.streetName,
          city: city || prev.city,
          district: district || prev.district,
          uploadStatus: 'done',
          // keep existing stages/results if they match; otherwise start fresh
          stageStatus: prev.jobId === jobId ? prev.stageStatus : initialStageStatus(),
          stageProgress: prev.jobId === jobId ? prev.stageProgress : initialStageProgress(),
          results: prev.jobId === jobId ? prev.results : null,
        })),

      updateStage: (idx, { status, current, total, phase } = {}) => {
        const stageStatus = { ...get().stageStatus }
        const stageProgress = { ...get().stageProgress }
        if (status) stageStatus[idx] = status
        if (
          current !== undefined
          || total !== undefined
          || phase !== undefined
        ) {
          const previous = stageProgress[idx] || {}
          stageProgress[idx] = {
            current: current ?? previous.current ?? 0,
            total: total ?? previous.total ?? 0,
            phase: phase ?? previous.phase,
          }
        }
        set({ stageStatus, stageProgress })
      },

      setAnalysisState: (status, error = '') =>
        set({ analysisStatus: status, analysisError: error }),

      finishAnalysis: (results, status = 'done') =>
        set({ analysisDone: true, analysisStatus: status, analysisError: '', results }),

      setReviewItems: (items) => set({ reviewItems: items }),
      approveReviewItem: (id, edited) => set((state) => {
        const storeId = storeIdForReview(edited?.storeId ?? id)
        const reviewItems = state.reviewItems.filter((item) => item.id !== id)
        const stores = (state.results?.stores ?? []).map((store) => {
          if (String(store.id) !== String(storeId)) return store
          return {
            ...store,
            name: edited.name,
            name_ar: edited.name,
            category: edited.category,
            phone: edited.phone,
            approved: true,
            edited: Boolean(edited.edited),
          }
        })
        const approvedStore = stores.find(
          (store) => String(store.id) === String(storeId)
        ) ?? { ...edited, id: storeId }
        const approvedItems = [
          ...state.approvedItems.filter(
            (item) => String(storeIdForReview(item)) !== String(storeId)
          ),
          approvedStore,
        ]
        const results = state.results
          ? {
              ...state.results,
              stores,
              review: reviewItems,
              summary: summarizeStores(state.results.summary, stores, reviewItems.length),
            }
          : state.results
        return { reviewItems, approvedItems, results }
      }),
      rejectReviewItem: (id) => set((state) => {
        const storeId = storeIdForReview(id)
        const reviewItems = state.reviewItems.filter((item) => item.id !== id)
        const stores = (state.results?.stores ?? []).filter(
          (store) => String(store.id) !== String(storeId)
        )
        const approvedItems = state.approvedItems.filter(
          (item) => String(storeIdForReview(item)) !== String(storeId)
        )
        const results = state.results
          ? {
              ...state.results,
              stores,
              review: reviewItems,
              summary: summarizeStores(state.results.summary, stores, reviewItems.length),
            }
          : state.results
        return { reviewItems, approvedItems, results }
      }),

      resetAll: () =>
        set({
          videoFile: null,
          videoName: '',
          videoSizeMb: 0,
          videoPath: '',
          uploadProgress: 0,
          uploadStatus: 'idle',
          uploadError: '',
          jobId: null,
          reviewToken: '',
          analysisStarted: false,
          analysisDone: false,
          analysisStatus: 'idle',
          analysisError: '',
          stageStatus: initialStageStatus(),
          stageProgress: initialStageProgress(),
          results: null,
          reviewItems: [],
          approvedItems: [],
        }),
    }),
    {
      name: 'store-extractor-state',
      storage: createJSONStorage(() => localStorage),
      // Persist everything EXCEPT volatile/non-serializable bits
      partialize: (state) => ({
        videoName: state.videoName,
        videoSizeMb: state.videoSizeMb,
        videoPath: state.videoPath,
        uploadStatus: state.uploadStatus === 'uploading' ? 'idle' : state.uploadStatus,

        city: state.city,
        streetName: state.streetName,
        district: state.district,
        speedMode: state.speedMode,
        enablePlaces: state.enablePlaces,
        enableStatus: state.enableStatus,

        jobId: state.jobId,
        reviewToken: state.reviewToken,
        analysisStarted: state.analysisStarted,
        analysisDone: state.analysisDone,
        analysisStatus: state.analysisStatus,
        analysisError: state.analysisError,
        stageStatus: state.stageStatus,
        stageProgress: state.stageProgress,

        results: state.results,
        reviewItems: state.reviewItems,
        approvedItems: state.approvedItems,
      }),
      version: 1,
    }
  )
)
