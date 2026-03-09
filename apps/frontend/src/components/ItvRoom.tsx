import { useState, useRef, useCallback } from "react"
import { usePeerConnection } from "@/hooks/usePeerConnection"
import { useLocalMedia } from "@/hooks/useLocalMedia"

type ConnectionState = "idle" | "connecting" | "connected" | "ended" | "error"

type InterviewRoomProps = {
  jobId: string
  candidateId: string
}

export default function ITVRoom({ jobId, candidateId }: InterviewRoomProps) {
  const agentAudioRef = useRef<HTMLAudioElement | null>(null)
  const signalingSocketRef = useRef<WebSocket | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle")
  const [rtcSessionId, setRtcSessionId] = useState<string | null>(null)
  const [agentEvents, setAgentEvents] = useState<string[]>([])
  console.log("Agent events:", agentEvents)
  const { acquireMicrophone, acquireScreenShare, releaseAll } = useLocalMedia()

  const handleAgentEvent = useCallback((message: Record<string, unknown>) => {
    const type = message.type as string
    setAgentEvents((prev) => [...prev, type])

    switch (type) {
      case "question_start":
        console.log("Question started:", message.number)
        break
      case "interview_ended":
        setConnectionState("ended")
        break
      case "evaluation_scores":
        console.log("Scores:", message)
        break
    }
  }, [])

  const { peerConnectionRef, createOffer, setRemoteAnswer, addTrack, dataChannelRef, close } =
    usePeerConnection({
      sessionId: `${jobId}_${candidateId}`,

      onRemoteAudioTrack: (stream) => {
        if (agentAudioRef.current) {
          agentAudioRef.current.srcObject = stream
          agentAudioRef.current.play().catch(console.error)
        }
      },

      onDataChannel: (channel) => {
        channel.onmessage = (event: MessageEvent<string>) => {
          const message = JSON.parse(event.data)
          handleAgentEvent(message)
        }
      },

      onConnectionStateChange: (state) => {
        if (state === "connected") setConnectionState("connected")
        if (state === "failed" || state === "closed") setConnectionState("ended")
      },

      onError: (error) => {
        console.error("Peer connection error", error)
        setConnectionState("error")
      },
    })

  const setupSignaling = useCallback(() => {
    return new Promise<WebSocket>((resolve, reject) => {
      const wsBase = import.meta.env.VITE_PUBLIC_WS_URL
      const ws = new WebSocket(`${wsBase}/api/v1/ws/interview/${jobId}/${candidateId}`)

      ws.onopen = () => {
        signalingSocketRef.current = ws
        resolve(ws)
      }

      ws.onerror = (event) => {
        console.error("WebSocket error:", event)
        reject(new Error("Failed to open signaling websocket"))
      }

      ws.onmessage = async (event) => {
        const msg = JSON.parse(event.data)

        switch (msg.type) {
          case "answer":
            setRtcSessionId(msg.session_id)
            await setRemoteAnswer({
              sdp: msg.sdp,
              type: msg.sdpType,
            })
            break

          case "ice_candidate":
            if (!peerConnectionRef.current) return
            await peerConnectionRef.current.addIceCandidate({
              candidate: msg.candidate,
              sdpMid: msg.sdpMid,
              sdpMLineIndex: msg.sdpMLineIndex,
            })
            break

          case "error":
            console.error("Signaling error:", msg.message)
            setConnectionState("error")
            break
        }
      }
    })
  }, [jobId, candidateId, setRemoteAnswer, peerConnectionRef])

  const startInterview = useCallback(async () => {
    setConnectionState("connecting")

    try {
      const ws = await setupSignaling()

      const localStream = await acquireMicrophone()
      for (const track of localStream.getTracks()) {
        addTrack(track, localStream)
      }

      if (peerConnectionRef.current) {
        peerConnectionRef.current.onicecandidate = (event) => {
          if (!event.candidate || ws.readyState !== WebSocket.OPEN) return

          ws.send(JSON.stringify({
            type: "ice_candidate",
            candidate: event.candidate.candidate,
            sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
          }))
        }
      }

      const offer = await createOffer()

      ws.send(JSON.stringify({
        type: "offer",
        sdp: offer.sdp,
        sdpType: offer.type,
        frame_interval_camera: 5.0,
        frame_interval_screen: 2.0,
      }))
    } catch (error) {
      console.error("Failed to start interview:", error)
      setConnectionState("error")
      releaseAll()
    }
  }, [setupSignaling, acquireMicrophone, addTrack, createOffer, peerConnectionRef, releaseAll])

  const startScreenShare = useCallback(async () => {
    try {
      const screenStream = await acquireScreenShare()

      for (const track of screenStream.getTracks()) {
        addTrack(track, screenStream)
        dataChannelRef.current?.send(JSON.stringify({
          type: "screen_share_start",
          trackId: track.id,
        }))

        track.onended = () => {
          dataChannelRef.current?.send(JSON.stringify({
            type: "screen_share_stop",
          }))
        }
      }
    } catch (error) {
      console.error("Screen share failed:", error)
    }
  }, [acquireScreenShare, addTrack, dataChannelRef])

  const endInterview = useCallback(() => {
    dataChannelRef.current?.send(JSON.stringify({ type: "interview_ended" }))
    signalingSocketRef.current?.send(JSON.stringify({ type: "end_session" }))
    signalingSocketRef.current?.close()
    close()
    releaseAll()
    setConnectionState("ended")
  }, [close, releaseAll, dataChannelRef])

  return (
    <div>
      <audio ref={agentAudioRef} autoPlay />
      <p>Status: {connectionState}</p>
      <p>RTC session: {rtcSessionId ?? "not started"}</p>

      {connectionState === "idle" && (
        <button className="text-white" onClick={startInterview}>
          Start Interview
        </button>
      )}

      {connectionState === "connected" && (
        <>
          <button className="text-white" onClick={startScreenShare}>
            Share Screen
          </button>
          <button className="text-white" onClick={endInterview}>
            End Interview
          </button>
        </>
      )}

      {connectionState === "connecting" && <p>Connecting...</p>}
      {connectionState === "ended" && <p>Interview complete.</p>}
    </div>
  )
}