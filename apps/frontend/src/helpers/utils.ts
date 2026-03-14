import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import type { SessionPhase } from "@/hooks/useInterviewSession"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}



export function fmtTime(s: number) {
  const m = String(Math.floor(s / 60)).padStart(2, "0")
  const sec = String(s % 60).padStart(2, "0")
  return `${m}:${sec}`
}
 
export function phaseLabel(p: SessionPhase): string {
  switch (p) {
    case "idle":              return "Ready"
    case "ws_connecting":     return "Connecting…"
    case "ws_connected":      return "Authenticating…"
    case "session_ready":     return "Setting up WebRTC…"
    case "webrtc_connecting": return "Establishing audio…"
    case "live":              return "Live"
    case "ended":             return "Ended"
    case "error":             return "Error"
  }
}
 
export function phaseColorClass(p: SessionPhase): string {
  if (p === "live")  return "text-primary"
  if (p === "error") return "text-destructive"
  if (p === "ended") return "text-muted-foreground"
  return "text-amber-400"
}
 
export function phaseColorHex(p: SessionPhase): string {
  if (p === "live")  return "#22c55e"
  if (p === "error") return "#ef4444"
  if (p === "ended") return "#6b7280"
  return "#f59e0b"
}