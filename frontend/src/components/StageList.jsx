import { STAGES } from '../data/stages'
import { useAppStore } from '../store/appStore'

export default function StageList() {
  const stageStatus = useAppStore((s) => s.stageStatus)
  const stageProgress = useAppStore((s) => s.stageProgress)

  return (
    <div>
      {STAGES.map((s, idx) => {
        const status = stageStatus[idx] ?? 'pending'
        const prog = stageProgress[idx]
        let detail = s.desc
        if (prog && prog.total > 0) {
          const pct = Math.round((prog.current / prog.total) * 100)
          detail = `${prog.current}/${prog.total} (${pct}%)`
        }
        return (
          <div key={idx} className={`stage-row ${status}`}>
            <span className="stage-icon">
              <i className={`bi ${s.icon}`}></i>
            </span>
            <span className="stage-name">{s.name}</span>
            <span className="stage-detail">{detail}</span>
          </div>
        )
      })}
    </div>
  )
}
