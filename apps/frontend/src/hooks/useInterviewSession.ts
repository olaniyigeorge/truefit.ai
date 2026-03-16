/**
 * useInterviewSession
 * 
 * Manages the full lifecycle of an interview session:
 *   WS connect → session_started → webrtc_offer (over WS) → webrtc_answer → ICE → audio
 * 
 * Backend WS endpoint: ws://host/api/v1/ws/interview/{job_id}/{candidate_id}
 * All signaling flows over the single WS connection — no separate HTTP signaling.
 */

import { useRef, useState, useCallback, useEffect } from "react"
import {useLocalMedia} from "@/hooks/useLocalMedia"
import config from "@/config"

// ── Types ─────────────────────────────────────────────────────────────────────

export type SessionPhase =
  | "idle"
  | "ws_connecting"
  | "ws_connected"       // WS open, waiting for session_started
  | "session_ready"      // received session_started, sending offer
  | "webrtc_connecting"  // offer sent, waiting for answer + ICE
  | "live"               // WebRTC connected, interview in progress
  | "ended"
  | "error"

export type TranscriptEntry = {
  id: string
  speaker: "agent" | "candidate" | "system"
  text: string
  timestamp: Date
}

export type SessionInfo = {
  interviewId: string
  sessionId: string
  maxQuestions: number
  maxDurationMinutes: number
}

export type InterruptDirective = {
  interruptId: string
  directive: string
  typeDetail: string
}

type UseInterviewSessionOptions = {
  jobId: string
  candidateId: string
  wsBaseUrl?: string
  onPhaseChange?: (phase: SessionPhase) => void
  onTranscript?: (entry: TranscriptEntry) => void
  onInterrupt?: (interrupt: InterruptDirective) => void
  onSessionInfo?: (info: SessionInfo) => void
  onError?: (message: string) => void
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useInterviewSession({
  jobId,
  candidateId,
  wsBaseUrl,
  onPhaseChange,
  onTranscript,
  onInterrupt,
  onSessionInfo,
  onError,
}: UseInterviewSessionOptions) {

  const [phase, setPhase] = useState<SessionPhase>("idle")
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [isMuted, setIsMuted] = useState(false)

  const wsRef      = useRef<WebSocket | null>(null)
  const pcRef      = useRef<RTCPeerConnection | null>(null)
  const phaseRef = useRef<SessionPhase>("idle")
  // const localRef   = useRef<MediaStream | null>(null)
  const audioRef   = useRef<HTMLAudioElement | null>(null)
  const timerRef   = useRef<ReturnType<typeof setInterval> | null>(null)
  const pingRef    = useRef<ReturnType<typeof setInterval> | null>(null)
  const iceBufRef  = useRef<RTCIceCandidate[]>([])
  const answerSetRef = useRef(false)

  const { acquireMicrophone, acquireScreenShare, releaseAll, localStreamRef} = useLocalMedia()

  // ── Phase setter (also fires callback) ───────────────────────────────────

  const updatePhase = useCallback((p: SessionPhase) => {
    phaseRef.current = p
    setPhase(p)
    onPhaseChange?.(p)
  }, [onPhaseChange])

  // ── Transcript helper ─────────────────────────────────────────────────────

  const addEntry = useCallback((
    speaker: TranscriptEntry["speaker"],
    text: string
  ) => {
    const entry: TranscriptEntry = {
      id: crypto.randomUUID(),
      speaker,
      text,
      timestamp: new Date(),
    }
    setTranscript(prev => [...prev, entry])
    onTranscript?.(entry)
  }, [onTranscript])

  // ── Timer ──

  const startTimer = useCallback(() => {
    timerRef.current = setInterval(() => {
      setElapsedSeconds(s => s + 1)
    }, 1000)
  }, [])

  const stopTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    setElapsedSeconds(0)
  }, [])

  // ── WebRTC setup ───

  const setupWebRTC = useCallback(async () => {
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    })
    pcRef.current = pc
    answerSetRef.current = false
    iceBufRef.current = []

    // DataChannel — frontend must create it (backend uses ondatachannel)
    const dc = pc.createDataChannel("interview")
    dc.onopen  = () => addEntry("system", "DataChannel open")
    dc.onclose = () => addEntry("system", "DataChannel closed")

    // Remote audio → play agent voice
    const remoteAudio = audioRef.current ?? new Audio()
    remoteAudio.autoplay = true
    audioRef.current = remoteAudio

    pc.ontrack = ({ streams }) => {
      if (streams[0]) {
        remoteAudio.srcObject = streams[0]
        remoteAudio.play().catch(() => {})
      }
    }

    // ICE candidates → send over WS (not HTTP)
    pc.onicecandidate = ({ candidate }) => {
      if (!candidate || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
      wsRef.current.send(JSON.stringify({
        type: "ice_candidate",
        candidate: candidate.candidate,
        sdpMid: candidate.sdpMid,
        sdpMLineIndex: candidate.sdpMLineIndex,
      }))
    }

    pc.onconnectionstatechange = () => {
      const state = pc.connectionState
      if (state === "connected") {
        updatePhase("live")
        startTimer()
        addEntry("system", "WebRTC connected — interview in progress")
      } else if (state === "failed" || state === "closed") {
        updatePhase("ended")
      }
    }

    // Acquire mic
    // const stream = await navigator.mediaDevices.getUserMedia({
    //   audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 16000 },
    //   video: false,
    // })
    // localRef.current = stream
    const stream = await acquireMicrophone()
    stream.getTracks().forEach(t => pc.addTrack(t, stream))

    // Create offer and send over WS
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    updatePhase("webrtc_connecting")

    wsRef.current?.send(JSON.stringify({
      type: "webrtc_offer",
      sdp: offer.sdp,
      sdp_type: offer.type,
      frame_interval_camera: 5,
      frame_interval_screen: 3,
    }))
  }, [addEntry, updatePhase, startTimer])

  // ── Apply remote answer + flush ICE ──────────────────────────────────────

  const applyAnswer = useCallback(async (sdp: string, sdpType: string) => {
    if (!pcRef.current) return
    await pcRef.current.setRemoteDescription(
      new RTCSessionDescription({ type: sdpType as RTCSdpType, sdp })
    )
    answerSetRef.current = true

    console.log("\nRemote description set, applying buffered ICE candidates:", iceBufRef.current)
    for (const c of iceBufRef.current) {
      await pcRef.current.addIceCandidate(c).catch(() => {})
    }
    iceBufRef.current = []
  }, [])

  // ── WS message handler ────────────────────────────────────────────────────

  const handleMessage = useCallback(async (raw: string) => {
    let msg: Record<string, unknown>
    try { msg = JSON.parse(raw) } catch { return }

    switch (msg.type as string) {

      case "session_started": {
        const info: SessionInfo = {
          interviewId:       msg.interview_id as string,
          sessionId:         msg.session_id as string,
          maxQuestions:      msg.max_questions as number,
          maxDurationMinutes: msg.max_duration_minutes as number,
        }
        setSessionInfo(info)
        onSessionInfo?.(info)
        updatePhase("session_ready")
        addEntry("system", `Session started · Interview ${(msg.interview_id as string).slice(0, 8)}…`)
        // Kick off WebRTC immediately
        await setupWebRTC()
        break
      }

      case "webrtc_answer": {
        await applyAnswer(msg.sdp as string, msg.sdp_type as string)
        addEntry("system", "SDP answer received — establishing connection…")
        break
      }

      case "ice_candidate": {
        if (!msg.candidate) break
        const cand = new RTCIceCandidate({
          candidate:     msg.candidate as string,
          sdpMid:        msg.sdpMid as string | undefined,
          sdpMLineIndex: msg.sdpMLineIndex as number | undefined,
        })
        if (answerSetRef.current && pcRef.current) {
          await pcRef.current.addIceCandidate(cand).catch(() => {})
        } else {
          iceBufRef.current.push(cand)
        }
        break
      }

      case "transcript": {
        const speaker = (msg.speaker as string) === "agent" ? "agent" : "candidate"
        addEntry(speaker, msg.text as string)
        break
      }

      case "interrupt": {
        const iv: InterruptDirective = {
          interruptId: msg.interrupt_id as string,
          directive:   msg.directive as string,
          typeDetail:  msg.type_detail as string,
        }
        onInterrupt?.(iv)
        addEntry("system", `[interrupt] ${iv.directive}`)
        break
      }

      case "session_ended": {
        addEntry("system", `Session ended: ${msg.reason} (${msg.status})`)
        updatePhase("ended")
        cleanup(false)
        break
      }

      case "error": {
        const errMsg = msg.message as string
        addEntry("system", `Error: ${errMsg}`)
        onError?.(errMsg)
        updatePhase("error")
        break
      }

      case "pong":
        break
    }
  }, [setupWebRTC, applyAnswer, addEntry, updatePhase, onSessionInfo, onInterrupt, onError])

  // ── Connect ───────────────────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (wsRef.current) return

    const base = (wsBaseUrl ?? config.wsUrl ?? "ws://localhost:8000")
      .replace(/\/$/, "")
    const url = `${base}/api/v1/ws/interview/${jobId}/${candidateId}`

    updatePhase("ws_connecting")
    addEntry("system", `Connecting to ${url}`)

    console.log("Creating WebSocket:", url)

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      updatePhase("ws_connected")
      addEntry("system", "WebSocket connected — waiting for session…")
      // Heartbeat
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }))
        }
      }, 20_000)
    }

    ws.onmessage = ({ data }) => handleMessage(data)

    ws.onerror = () => {
      addEntry("system", "WebSocket error — check backend URL")
      onError?.("WebSocket connection error")
      updatePhase("error")
    }

    ws.onclose = ({ code, reason }) => {
      addEntry("system", `WebSocket closed: ${code} ${reason ?? ""}`)
      if (pingRef.current) clearInterval(pingRef.current)
      if (phaseRef.current !== "ended") updatePhase("ended")
    }
  }, [jobId, candidateId, wsBaseUrl, handleMessage, addEntry, updatePhase, onError])

  // ── Disconnect ────────────────────────────────────────────────────────────

  const cleanup = useCallback((closeWs = true) => {
    if (closeWs && wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "end_session", reason: "candidate_ended" }))
      }
      wsRef.current.close()
      wsRef.current = null
    }
    if (pcRef.current) { pcRef.current.close(); pcRef.current = null }
    // if (localRef.current) { localRef.current.getTracks().forEach(t => t.stop()); localRef.current = null }
    releaseAll()
    if (pingRef.current) clearInterval(pingRef.current)
    answerSetRef.current = false
    iceBufRef.current = []
    stopTimer()
  }, [stopTimer])

  const disconnect = useCallback(() => {
    cleanup(true)
    updatePhase("ended")
  }, [cleanup, updatePhase])

  // ── Mic toggle ────────────────────────────────────────────────────────────

  const toggleMute = useCallback(() => {
    const stream = localStreamRef.current
    console.log('Muted')
    if (!stream) return
    const track = stream.getAudioTracks()[0]
    if (!track) return
    track.enabled = !track.enabled
    setIsMuted(!track.enabled)
  }, [localStreamRef])

  // ── Screen share ──────────────────────────────────────────────────────────

  const startScreenShare = useCallback(async () => {
    if (!pcRef.current) return
    console.log('Sharing')
    try {
      // const screen = await navigator.mediaDevices.getDisplayMedia({ video: true })
      const screen = await acquireScreenShare()
      console.log('screen', screen)
      screen.getTracks().forEach(t => {
        pcRef.current!.addTrack(t, screen)
        t.onended = () => {} // handle stop sharing
      })
    } catch {
      addEntry("system", "Screen share cancelled")
    }
  }, [addEntry])

  // ── Cleanup on unmount ────────────────────────────────────────────────────

  useEffect(() => () => cleanup(true), [cleanup])

  return {
    // State
    phase,
    transcript,
    sessionInfo,
    elapsedSeconds,
    isMuted,
    // Actions
    connect,
    disconnect,
    toggleMute,
    startScreenShare,
    // Refs (for audio element)
    audioRef,
    localStreamRef
  }
}