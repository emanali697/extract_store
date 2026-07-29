import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { STAGES } from '../data/stages'

const initialStageStatus = () =>
  Object.fromEntries(STAGES.map((_, i) => [i, 'pending']))

const initialStageProgress = () =>
  Object.fromEntries(STAGES.map((_, i) => [i, null]))

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

      startAnalysis: (jobId) =>
        set({
          jobId,
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
      approveReviewItem: (id, edited) => {
        const reviewItems = get().reviewItems.filter((it) => it.id !== id)
        const approvedItems = [...get().approvedItems, edited]
        set({ reviewItems, approvedItems })
      },
      rejectReviewItem: (id) => {
        const reviewItems = get().reviewItems.filter((it) => it.id !== id)
        set({ reviewItems })
      },

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
