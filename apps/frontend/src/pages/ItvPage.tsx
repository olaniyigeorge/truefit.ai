/**
 * ItvPage — /itv/:jobId/:candidateId
 * 
 * Two states:
 *  1. Setup — shows ID fields pre-filled from URL params, lets user start
 *  2. Live  — full interview room with transcript, audio viz, controls
 */

import { useState, useRef, useEffect, useCallback } from "react"
import { useParams } from "react-router"
import { useInterviewSession, type SessionPhase, type TranscriptEntry } from "@/hooks/useInterviewSession"

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(s: number) {
  const m = String(Math.floor(s / 60)).padStart(2, "0")
  const sec = String(s % 60).padStart(2, "0")
  return `${m}:${sec}`
}

function phaseLabel(p: SessionPhase): string {
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

function phaseColor(p: SessionPhase): string {
  if (p === "live")  return "#22c55e"
  if (p === "error") return "#ef4444"
  if (p === "ended") return "#6b7280"
  return "#f59e0b"
}

// ── Audio Visualizer ──────────────────────────────────────────────────────────

function AudioViz({ stream }: { stream: MediaStream | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (!stream || !canvasRef.current) return
    const ctx = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 64
    const src = ctx.createMediaStreamSource(stream)
    src.connect(analyser)
    const buf = new Uint8Array(analyser.frequencyBinCount)
    const canvas = canvasRef.current
    const c = canvas.getContext("2d")!

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw)
      analyser.getByteFrequencyData(buf)
      c.clearRect(0, 0, canvas.width, canvas.height)
      const w = canvas.width / buf.length
      buf.forEach((v, i) => {
        const h = (v / 255) * canvas.height
        const alpha = 0.3 + (v / 255) * 0.7
        c.fillStyle = `rgba(34, 197, 94, ${alpha})`
        c.fillRect(i * w, canvas.height - h, w - 1, h)
      })
    }
    draw()

    return () => {
      cancelAnimationFrame(rafRef.current)
      ctx.close()
    }
  }, [stream])

  return (
    <canvas
      ref={canvasRef}
      width={200}
      height={32}
      style={{ width: "100%", height: 32, display: "block" }}
    />
  )
}

// ── Transcript Message ────────────────────────────────────────────────────────

function Message({ entry }: { entry: TranscriptEntry }) {
  const isAgent     = entry.speaker === "agent"
  const isSystem    = entry.speaker === "system"
  const isCandidate = entry.speaker === "candidate"

  console.log("isCandidate", isCandidate)

  if (isSystem) {
    return (
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 0",
      }}>
        <div style={{ height: 1, flex: 1, background: "#1f2937" }} />
        <span style={{ fontSize: 11, color: "#4b5563", fontFamily: "monospace", letterSpacing: "0.05em" }}>
          {entry.text}
        </span>
        <div style={{ height: 1, flex: 1, background: "#1f2937" }} />
      </div>
    )
  }

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      gap: 4,
      alignItems: isAgent ? "flex-start" : "flex-end",
      animation: "fadeUp 0.25s ease",
    }}>
      <span style={{
        fontSize: 10,
        color: isAgent ? "#22c55e" : "#60a5fa",
        fontFamily: "monospace",
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        paddingLeft: 4, paddingRight: 4,
      }}>
        {isAgent ? "AI Interviewer" : "You"} · {entry.timestamp.toLocaleTimeString("en-US", { hour12: false })}
      </span>
      <div style={{
        maxWidth: "80%",
        background: isAgent ? "#0d1f13" : "#0d1527",
        border: `1px solid ${isAgent ? "#166534" : "#1e3a5f"}`,
        borderRadius: isAgent ? "4px 16px 16px 16px" : "16px 4px 16px 16px",
        padding: "10px 14px",
        fontSize: 14,
        lineHeight: 1.6,
        color: isAgent ? "#dcfce7" : "#dbeafe",
        fontFamily: "'Georgia', serif",
      }}>
        {entry.text}
      </div>
    </div>
  )
}

// ── Setup Screen ──────────────────────────────────────────────────────────────

type SetupProps = {
  jobId: string
  candidateId: string
  onJobIdChange: (v: string) => void
  onCandidateIdChange: (v: string) => void
  onStart: () => void
  isConnecting: boolean
}

function SetupScreen({ jobId, candidateId, onJobIdChange, onCandidateIdChange, onStart, isConnecting }: SetupProps) {
  return (
    <div style={{
      minHeight: "100vh",
      background: "#030712",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "monospace",
      padding: 24,
    }}>
      {/* Background grid */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none",
        backgroundImage: `
          linear-gradient(rgba(34,197,94,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(34,197,94,0.03) 1px, transparent 1px)
        `,
        backgroundSize: "40px 40px",
      }} />

      <div style={{
        position: "relative",
        width: "100%",
        maxWidth: 480,
        display: "flex",
        flexDirection: "column",
        gap: 32,
      }}>
        {/* Logo / header */}
        <div>
          <div style={{
            fontSize: 11,
            letterSpacing: "0.3em",
            color: "#22c55e",
            textTransform: "uppercase",
            marginBottom: 8,
          }}>
            TrueFit · Interview System
          </div>
          <h1 style={{
            fontSize: 36,
            fontWeight: 800,
            color: "#f9fafb",
            fontFamily: "'Georgia', serif",
            lineHeight: 1.1,
            letterSpacing: "-1px",
            margin: 0,
          }}>
            Start Your<br />
            <span style={{ color: "#22c55e" }}>Interview</span>
          </h1>
          <p style={{ marginTop: 12, fontSize: 13, color: "#6b7280", lineHeight: 1.6 }}>
            AI-powered voice interview. You'll need microphone access.
          </p>
        </div>

        {/* Form card */}
        <div style={{
          background: "#0d1117",
          border: "1px solid #1f2937",
          borderRadius: 12,
          padding: 28,
          display: "flex",
          flexDirection: "column",
          gap: 20,
        }}>
          <Field
            label="Candidate ID"
            value={candidateId}
            onChange={onCandidateIdChange}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            hint="Your candidate profile UUID"
          />
          <Field
            label="Job ID"
            value={jobId}
            onChange={onJobIdChange}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            hint="The position you're interviewing for"
          />

          <button
            onClick={onStart}
            disabled={!jobId.trim() || !candidateId.trim() || isConnecting}
            style={{
              marginTop: 4,
              padding: "14px 0",
              background: jobId && candidateId && !isConnecting ? "#22c55e" : "#1f2937",
              color: jobId && candidateId && !isConnecting ? "#000" : "#4b5563",
              border: "none",
              borderRadius: 8,
              fontSize: 14,
              fontWeight: 700,
              fontFamily: "monospace",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              cursor: jobId && candidateId && !isConnecting ? "pointer" : "not-allowed",
              transition: "all 0.15s",
            }}
          >
            {isConnecting ? "Connecting…" : "▶  Begin Interview"}
          </button>
        </div>

        {/* Footer hint */}
        <p style={{ fontSize: 11, color: "#374151", textAlign: "center", lineHeight: 1.5 }}>
          By starting, you grant microphone access for the duration of this session.
          Audio is processed in real-time and not stored beyond transcript generation.
        </p>
      </div>
    </div>
  )
}

function Field({
  label, value, onChange, placeholder, hint
}: {
  label: string; value: string; onChange: (v: string) => void
  placeholder: string; hint: string
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ fontSize: 10, letterSpacing: "0.15em", textTransform: "uppercase", color: "#6b7280" }}>
        {label}
      </label>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        style={{
          background: "#030712",
          border: "1px solid #1f2937",
          borderRadius: 6,
          padding: "10px 12px",
          color: "#f9fafb",
          fontSize: 12,
          fontFamily: "monospace",
          outline: "none",
          transition: "border-color 0.15s",
        }}
        onFocus={e => (e.target.style.borderColor = "#22c55e")}
        onBlur={e => (e.target.style.borderColor = "#1f2937")}
      />
      <span style={{ fontSize: 11, color: "#374151" }}>{hint}</span>
    </div>
  )
}

// ── Live Interview Room ───────────────────────────────────────────────────────

type RoomProps = {
  jobId: string
  candidateId: string
  onExit: () => void
}

function InterviewRoom({ jobId, candidateId, onExit }: RoomProps) {
  const transcriptRef = useRef<HTMLDivElement>(null)
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)

  const {
    phase, transcript, sessionInfo, elapsedSeconds, isMuted,
    connect, disconnect, toggleMute, startScreenShare, audioRef,
  } = useInterviewSession({
    jobId,
    candidateId,
  })

  // Capture local stream ref for visualizer after WebRTC sets up mic
  useEffect(() => {
    if (phase === "live") {
      navigator.mediaDevices.getUserMedia({ audio: true, video: false })
        .then(setLocalStream)
        .catch(() => {})
    }
  }, [phase])

  // Auto-scroll transcript
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [transcript])

  // Connect on mount
  useEffect(() => {
    connect()
    return () => disconnect() // cleanup on unmount
  }, []) // empty deps, not [connect]

  const handleEnd = useCallback(() => {
    disconnect()
    onExit()
  }, [disconnect, onExit])

  const isLive = phase === "live"

  return (
    <div style={{
      height: "100vh",
      background: "#030712",
      display: "grid",
      gridTemplateRows: "52px 1fr 72px",
      fontFamily: "monospace",
      color: "#f9fafb",
    }}>
      {/* Hidden audio element for agent voice */}
      <audio ref={audioRef} autoPlay style={{ display: "none" }} />

      {/* ── Top bar ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 20px",
        borderBottom: "1px solid #111827",
        background: "#0d1117",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#22c55e", letterSpacing: "-0.5px" }}>
            TrueFit.ai
          </span>
          <span style={{ color: "#1f2937" }}>|</span>
          <span style={{ fontSize: 11, color: "#647087" }}>Interview Session</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {/* Phase badge */}
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "4px 10px",
            background: "#111827",
            borderRadius: 4,
            border: `1px solid ${phaseColor(phase)}22`,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: "50%",
              background: phaseColor(phase),
              boxShadow: isLive ? `0 0 8px ${phaseColor(phase)}` : "none",
              animation: isLive ? "pulse 2s infinite" : "none",
            }} />
            <span style={{ fontSize: 11, color: phaseColor(phase), letterSpacing: "0.05em" }}>
              {phaseLabel(phase)}
            </span>
          </div>

          {/* Timer */}
          <span style={{
            fontSize: 18, fontWeight: 300, letterSpacing: "0.15em",
            color: isLive ? "#f9fafb" : "#374151",
            minWidth: 52, textAlign: "right",
          }}>
            {fmtTime(elapsedSeconds)}
          </span>
        </div>
      </div>

      {/* ── Main area ── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "260px 1fr",
        overflow: "hidden",
      }}>

        {/* Sidebar */}
        <div style={{
          borderRight: "1px solid #111827",
          background: "#0d1117",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}>
          {/* Session info */}
          <div style={{ padding: "20px 16px", borderBottom: "1px solid #111827" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.2em", textTransform: "uppercase", color: "#374151", marginBottom: 14 }}>
              Session
            </div>
            {sessionInfo ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <InfoRow label="Interview" value={sessionInfo.interviewId.slice(0, 8) + "…"} accent />
                <InfoRow label="Max Questions" value={String(sessionInfo.maxQuestions)} />
                <InfoRow label="Duration" value={`${sessionInfo.maxDurationMinutes} min`} />
                <InfoRow label="Job" value={jobId.slice(0, 8) + "…"} />
                <InfoRow label="Candidate" value={candidateId.slice(0, 8) + "…"} />
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "#374151" }}>Awaiting session…</div>
            )}
          </div>

          {/* Visualizer */}
          <div style={{ padding: "14px 16px", borderBottom: "1px solid #111827" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.2em", textTransform: "uppercase", color: "#374151", marginBottom: 10 }}>
              Mic Level
            </div>
            <AudioViz stream={localStream} />
          </div>

          {/* Controls */}
          <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: 8, marginTop: "auto" }}>
            <ControlBtn
              onClick={toggleMute}
              active={isMuted}
              label={isMuted ? "🔇 Unmute" : "🎙 Mute"}
              disabled={!isLive}
              variant="ghost"
            />
            <ControlBtn
              onClick={startScreenShare}
              label="🖥 Share Screen"
              disabled={!isLive}
              variant="ghost"
            />
            <ControlBtn
              onClick={handleEnd}
              label="■ End Interview"
              variant="danger"
            />
          </div>
        </div>

        {/* Transcript */}
        <div style={{
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          background: "#030712",
        }}>
          <div style={{
            padding: "14px 24px",
            borderBottom: "1px solid #111827",
            background: "#0d1117",
            fontSize: 11,
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            color: "#374151",
          }}>
            Transcript
          </div>

          <div
            ref={transcriptRef}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "20px 24px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            {transcript.length === 0 && (
              <div style={{
                flex: 1, display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center",
                gap: 12, color: "#1f2937", textAlign: "center",
                paddingTop: 80,
              }}>
                <div style={{ fontSize: 48, opacity: 0.3 }}>◎</div>
                <div style={{ fontSize: 20, fontFamily: "'Georgia', serif", fontWeight: 700, color: "#111827" }}>
                  Waiting for session
                </div>
                <div style={{ fontSize: 12, color: "#1f2937", maxWidth: 280, lineHeight: 1.6 }}>
                  Transcript will appear here as the interview progresses
                </div>
              </div>
            )}

            {transcript.map(entry => (
              <Message key={entry.id} entry={entry} />
            ))}
          </div>
        </div>
      </div>

      {/* ── Bottom toolbar ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 24px",
        borderTop: "1px solid #111827",
        background: "#0d1117",
      }}>
        <span style={{ fontSize: 11, color: "#374151" }}>
          {isLive ? "Audio connected · speak naturally" : phaseLabel(phase)}
        </span>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <WebRTCStateIndicator phase={phase} />
        </div>
      </div>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        @keyframes fadeUp { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #1f2937; border-radius: 2px; }
      `}</style>
    </div>
  )
}

function InfoRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
      <span style={{ color: "#493fff" }}>{label}</span>
      <span style={{ color: accent ? "#22c55e" : "#6f7f9f", fontFamily: "monospace" }}>{value}</span>
    </div>
  )
}

function ControlBtn({
  onClick, label, disabled, variant, active
}: {
  onClick: () => void; label: string; disabled?: boolean
  variant?: "ghost" | "danger"; active?: boolean
}) {
  const colors = {
    ghost: { bg: "transparent", border: "#1f2937", color: "#6b7280", hoverBg: "#111827", hoverColor: "#f9fafb" },
    danger: { bg: "transparent", border: "#7f1d1d", color: "#ef4444", hoverBg: "#ef4444", hoverColor: "#000" },
  }
  const c = colors[variant ?? "ghost"]

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "8px 12px",
        background: active ? "#111827" : c.bg,
        border: `1px solid ${active ? "#374151" : c.border}`,
        borderRadius: 6,
        color: active ? "#f9fafb" : c.color,
        fontSize: 12,
        fontFamily: "monospace",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.3 : 1,
        transition: "all 0.15s",
        textAlign: "left" as const,
        width: "100%",
      }}
    >
      {label}
    </button>
  )
}

function WebRTCStateIndicator({ phase }: { phase: SessionPhase }) {
  const steps: Array<{ key: SessionPhase[]; label: string }> = [
    { key: ["ws_connecting", "ws_connected"], label: "WS" },
    { key: ["session_ready"], label: "Session" },
    { key: ["webrtc_connecting"], label: "WebRTC" },
    { key: ["live"], label: "Audio" },
  ]

  const phaseOrder: SessionPhase[] = [
    "idle", "ws_connecting", "ws_connected", "session_ready",
    "webrtc_connecting", "live", "ended", "error"
  ]
  const currentIdx = phaseOrder.indexOf(phase)

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      {steps.map((step, i) => {
        const stepIdx = phaseOrder.indexOf(step.key[0])
        const done    = currentIdx > stepIdx + 1
        const active  = step.key.includes(phase) || (phase === "live" && i === 3)

        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{
              padding: "2px 8px",
              borderRadius: 3,
              fontSize: 10,
              fontFamily: "monospace",
              letterSpacing: "0.05em",
              background: active ? "rgba(34,197,94,0.15)" : done ? "rgba(34,197,94,0.05)" : "#111827",
              color: active ? "#22c55e" : done ? "#166534" : "#374151",
              border: `1px solid ${active ? "#22c55e33" : "#1f2937"}`,
            }}>
              {done ? "✓ " : ""}{step.label}
            </div>
            {i < steps.length - 1 && (
              <div style={{ width: 12, height: 1, background: "#1f2937" }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── ItvPage (route entry point) ───

export default function ItvPage() {
  const { jobId: urlJobId, candidateId: urlCandidateId } = useParams<{
    jobId: string
    candidateId: string
  }>()

  const [jobId, setJobId] = useState(urlJobId ?? "")
  const [candidateId, setCandidateId] = useState(urlCandidateId ?? "")
  const [started, setStarted] = useState(false)

  // If IDs come from URL and are valid UUIDs, auto-start
  const uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  const isConnecting = false // could wire phase from session hook if needed

  console.log("URL params", { urlJobId, urlCandidateId, isValidJobId: uuidRe.test(urlJobId ?? ""), isValidCandidateId: uuidRe.test(urlCandidateId ?? "") })

  const handleStart = () => {
    if (!jobId.trim() || !candidateId.trim()) return
    setStarted(true)
  }

  if (started && jobId && candidateId) {
    return (
      
      <InterviewRoom
        jobId={jobId}
        candidateId={candidateId}
        onExit={() => setStarted(false)}
      />
    )
  }

  return (
<div
  className="min-w-screen flex items-center justify-center h-screen"
  style={{
    background: "#030712",
    backgroundImage: `
      radial-gradient(ellipse 80% 50% at 50% -10%, rgba(34,197,94,0.12) 6%, transparent 95%),
      linear-gradient(rgba(34,197,94,0.03) 0.5px, transparent 1px),
      linear-gradient(90deg, rgba(34,197,94,0.03) 0.5px, transparent 1px)
    `,
    backgroundSize: "100% 100%, 48px 48px, 48px 48px",
  }}
>
  <SetupScreen
    jobId={jobId}
    candidateId={candidateId}
    onJobIdChange={setJobId}
    onCandidateIdChange={setCandidateId}
    onStart={handleStart}
    isConnecting={isConnecting}
  />
</div>
  )
}