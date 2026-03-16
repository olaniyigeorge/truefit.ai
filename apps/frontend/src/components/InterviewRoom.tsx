
import {InfoRow} from "./InfoRow"
import {useEffect, useRef, useCallback} from "react"
import { useInterviewSession } from "@/hooks/useInterviewSession"
import {useLocalMedia} from "@/hooks/useLocalMedia"
import { AudioViz } from "./AudioViz"
import {Separator} from "@/components/ui/separator"
import {Message} from "@/components/TranscriptMessage"
import {WebRTCStateIndicator} from "./WebRTCStateIndicator"
import { ControlBtn } from "./ControlBtn"
import {cn} from "@/helpers/utils"
import {fmtTime, phaseLabel, phaseColorClass, phaseColorHex} from "@/helpers/utils"


type RoomProps = { jobId: string; candidateId: string; onExit: () => void }
 
export function InterviewRoom({ jobId, candidateId, onExit }: RoomProps) {
  const transcriptRef = useRef<HTMLDivElement>(null)
  // const [localStream, setLocalStream] = useState<MediaStream | null>(null)
 
  const {
    phase, transcript, sessionInfo, elapsedSeconds, isMuted,
    connect, disconnect, toggleMute, startScreenShare, audioRef, localStreamRef
  } = useInterviewSession({ jobId, candidateId })
//  const {localStreamRef} = useLocalMedia()

  // useEffect(() => {
  //   if (phase === "live") {
  //     navigator.mediaDevices.getUserMedia({ audio: true, video: false })
  //       .then(setLocalStream).catch(() => {})
  //   }
  // }, [phase])
 
  useEffect(() => {
    if (transcriptRef.current)
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
  }, [transcript])
 
  useEffect(() => { connect() }, [connect])
 
  const handleEnd = useCallback(() => {
    disconnect()
    onExit()
  }, [disconnect, onExit])
 
  const isLive   = phase === "live"
  const hexColor = phaseColorHex(phase)
 
  return (
    <div className="h-screen bg-background grid font-mono text-foreground" style={{ gridTemplateRows: "52px 1fr 72px" }}>
      <audio ref={audioRef} autoPlay className="hidden" />
 
      {/* ── Top bar ── */}
      <div className="flex items-center justify-between px-5 border-b border-border bg-card">
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-bold text-primary tracking-tight">TrueFit.ai</span>
          <Separator orientation="vertical" className="h-4" />
          <span className="text-[11px] text-muted-foreground/60">Interview Session</span>
        </div>
 
        <div className="flex items-center gap-4">
          {/* Phase badge */}
          <div
            className="flex items-center gap-1.5 px-2.5 py-1 bg-secondary rounded border"
            style={{ borderColor: `${hexColor}22` }}
          >
            <div
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: hexColor,
                boxShadow: isLive ? `0 0 8px ${hexColor}` : "none",
                animation: isLive ? "pulse-dot 2s infinite" : "none",
              }}
            />
            <span className={cn("text-[11px] tracking-wide", phaseColorClass(phase))}>
              {phaseLabel(phase)}
            </span>
          </div>
 
          {/* Timer */}
          <span className={cn(
            "text-lg font-light tracking-[0.15em] min-w-[52px] text-right tabular-nums",
            isLive ? "text-foreground" : "text-muted-foreground/30"
          )}>
            {fmtTime(elapsedSeconds)}
          </span>
        </div>
      </div>
 
      {/* ── Main area ── */}
      <div className="grid overflow-hidden" style={{ gridTemplateColumns: "260px 1fr" }}>
 
        {/* Sidebar */}
        <div className="border-r border-border bg-card flex flex-col overflow-hidden">
 
          {/* Session info */}
          <div className="px-4 py-5 border-b border-border">
            <p className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground/40 mb-3.5">Session</p>
            {sessionInfo ? (
              <div className="flex flex-col gap-2.5">
                <InfoRow label="Interview" value={sessionInfo.interviewId.slice(0, 8) + "…"} accent />
                <InfoRow label="Max Questions" value={String(sessionInfo.maxQuestions)} />
                <InfoRow label="Duration"      value={`${sessionInfo.maxDurationMinutes} min`} />
                <InfoRow label="Job"           value={jobId.slice(0, 8) + "…"} />
                <InfoRow label="Candidate"     value={candidateId.slice(0, 8) + "…"} />
              </div>
            ) : (
              <p className="text-[12px] text-muted-foreground/40">Awaiting session…</p>
            )}
          </div>
 
          {/* Mic visualizer */}
          <div className="px-4 py-3.5 border-b border-border">
            <p className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground/40 mb-2.5">Mic Level</p>
            <AudioViz stream={localStreamRef.current} />
          </div>
 
          {/* Controls */}
          <div className="p-4 flex flex-col gap-2 mt-auto">
            <ControlBtn onClick={toggleMute}       label={isMuted ? "🔇 Unmute" : "🎙 Mute"} disabled={!isLive} variant="ghost" active={isMuted} />
            <ControlBtn onClick={startScreenShare} label="🖥 Share Screen"                    disabled={!isLive} variant="ghost" />
            <ControlBtn onClick={handleEnd}        label="■ End Interview"                                       variant="danger" />
          </div>
        </div>
 
        {/* Transcript panel */}
        <div className="flex flex-col overflow-hidden bg-background">
          <div className="px-6 py-3.5 border-b border-border bg-card text-[11px] tracking-[0.2em] uppercase text-muted-foreground/40">
            Transcript
          </div>
 
          <div
            ref={transcriptRef}
            className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-3 scrollbar-thin"
          >
            {transcript.length === 0 && (
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center pt-20">
                <div className="text-5xl opacity-20">◎</div>
                <p className="font-serif text-xl font-bold text-muted-foreground/20">Waiting for session</p>
                <p className="text-[12px] text-muted-foreground/30 max-w-[280px] leading-relaxed">
                  Transcript will appear here as the interview progresses
                </p>
              </div>
            )}
            {transcript.map(entry => <Message key={entry.id} entry={entry} />)}
          </div>
        </div>
      </div>
 
      {/* ── Bottom bar ── */}
      <div className="flex items-center justify-between px-6 border-t border-border bg-card">
        <span className="text-[11px] text-muted-foreground/40">
          {isLive ? "Audio connected · speak naturally" : phaseLabel(phase)}
        </span>
        <WebRTCStateIndicator phase={phase} />
      </div>
    </div>
  )
}