import type { SessionPhase } from "@/hooks/useInterviewSession";
import {cn} from "@/helpers/utils"



export function WebRTCStateIndicator({ phase }: { phase: SessionPhase }) {
  const steps: Array<{ key: SessionPhase[]; label: string }> = [
    { key: ["ws_connecting", "ws_connected"], label: "WS" },
    { key: ["session_ready"],                 label: "Session" },
    { key: ["webrtc_connecting"],             label: "WebRTC" },
    { key: ["live"],                          label: "Audio" },
  ]
  const phaseOrder: SessionPhase[] = [
    "idle", "ws_connecting", "ws_connected", "session_ready",
    "webrtc_connecting", "live", "ended", "error",
  ]
  const currentIdx = phaseOrder.indexOf(phase)
 
  return (
    <div className="flex items-center gap-1">
      {steps.map((step, i) => {
        const stepIdx = phaseOrder.indexOf(step.key[0])
        const done    = currentIdx > stepIdx + 1
        const active  = step.key.includes(phase) || (phase === "live" && i === 3)
 
        return (
          <div key={i} className="flex items-center gap-1">
            <div
              className={cn(
                "px-2 py-0.5 rounded-sm text-[10px] font-mono tracking-wide border",
                active && "bg-primary/15 text-primary border-primary/20",
                done   && "bg-primary/5 text-green-800 border-border",
                !active && !done && "bg-secondary text-muted-foreground/50 border-border"
              )}
            >
              {done ? "✓ " : ""}{step.label}
            </div>
            {i < steps.length - 1 && <div className="w-3 h-px bg-border" />}
          </div>
        )
      })}
    </div>
  )
}