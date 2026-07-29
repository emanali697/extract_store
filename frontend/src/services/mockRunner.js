import { STAGES } from '../data/stages'

const STAGE_TOTALS = [224, 224, 124, 124, 124, 25, 46, 46, 1]
const STEP_DELAY_MS = 80
const TICKS_PER_STAGE = 18

export function runMockAnalysis({ onUpdate, onDone } = {}) {
  let cancelled = false
  let stage = 0

  const tickStage = (i) => {
    if (cancelled) return
    const total = STAGE_TOTALS[i] ?? 1
    const step = Math.max(1, Math.ceil(total / TICKS_PER_STAGE))
    let current = 0

    onUpdate?.({ stage: i, status: 'active', current: 0, total })

    const id = setInterval(() => {
      if (cancelled) {
        clearInterval(id)
        return
      }
      current = Math.min(total, current + step)
      onUpdate?.({ stage: i, status: 'active', current, total })

      if (current >= total) {
        clearInterval(id)
        onUpdate?.({ stage: i, status: 'done', current: total, total })
        stage += 1
        if (stage < STAGES.length) {
          setTimeout(() => tickStage(stage), STEP_DELAY_MS * 2)
        } else {
          onDone?.()
        }
      }
    }, STEP_DELAY_MS)
  }

  tickStage(0)

  return {
    cancel() { cancelled = true },
  }
}
