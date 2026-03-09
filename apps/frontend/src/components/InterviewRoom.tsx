
// import {useState, useEffect, useRef} from "react"
// import { usePeerConnection } from "@/hooks/usePeerConnection"


// type InterviewRoomProps = {
//     sessionId: string
// }

// export default function InterviewRoom ({sessionId}: InterviewRoomProps) {

//     const agentAudioRef = useRef<HTMLAudioElement|null>(null)

//     // const peerConnection = useRef<RTCPeerConnection | null>(null)

//     const {peerConnectionRef, createOffer, setRemoteAnswer, addTrack} = usePeerConnection({
//         sessionId,
//         onRemoteAudioTrack: (stream) => {
//             if(agentAudioRef.current){
//                 agentAudioRef.current.srcObject = stream
//                 agentAudioRef.current.play()
//             }
//             //attach to an audio element to play agent voice
//             // const stream = new MediaStream([track])
//             // agentAudioRef.current!.srcObject = stream
//             // agentAudioRef.current!.play()
//         },
//         onDataChannel: (channel) => {
//             //hand off to data channel handler
//             channel.onmessage = (event: MessageEvent<string>) => {
//                 const message = JSON.parse(event.data)
//                 console.log("Data channel message", message)
//                 // dispatch({type: message.type, payload: message})
//             }
//         },
//         onError: (error) => {
//             console.error("Peer connection error", error)
//         }
//     })


//     const makeCall = async () => {
//         try {
//             const offer = await createOffer()
//             const response = await fetch(`${import.meta.env.VITE_PUBLIC_API_URL}/v1/sessions/${sessionId}/offer`, {
//                 method: 'POST',
//                 headers: {"Content-Type": "application/json"},
//                 body: JSON.stringify(offer)
//             })

//             const answer: RTCSessionDescriptionInit = await response.json()
//             await setRemoteAnswer(answer)
//         } catch (error) {
//             console.error("Failed to start call", error)
//         }
//     }

//     return(
//         <div>
//             <audio ref={agentAudioRef}/>
//             <button onClick={makeCall}>Start Interview</button>
//         </div>
//     )
// }



import { useState, useRef, useCallback } from "react"
import { usePeerConnection } from "@/hooks/usePeerConnection"
import { useLocalMedia } from "@/hooks/useLocalMedia"

type ConnectionState = "idle" | "connecting" | "connected" | "ended" | "error"

type InterviewRoomProps = {
  jobId: string
  candidateId: string
}

export default function InterviewRoom({ jobId, candidateId }: InterviewRoomProps) {
  const agentAudioRef = useRef<HTMLAudioElement | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle")
  const [interview_session_id, setInterviewSessionId] = useState<string | null>(null)
  const [agentEvents, setAgentEvents] = useState<string[]>([])
  console.log("Agent events:", agentEvents)
  const { acquireMicrophone, acquireScreenShare, releaseAll } = useLocalMedia()

  const { createOffer, setRemoteAnswer, addTrack, dataChannelRef, close } = usePeerConnection({
    sessionId: `${jobId}_${candidateId}`,

    onRemoteAudioTrack: (stream) => {
      if (agentAudioRef.current) {
        agentAudioRef.current.srcObject = stream
        agentAudioRef.current.play()
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

  // ── Agent event dispatch ────

  const handleAgentEvent = useCallback((message: Record<string, unknown>) => {
    const type = message.type as string
    setAgentEvents(prev => [...prev, type])

    switch (type) {
      case "question_start":
        console.log("Question started:", message.number)
        break
      case "interview_ended":
        setConnectionState("ended")
        break
      case "agent_thinking":
        // show thinking indicator
        break
      case "interrupt":
        // agent interrupted — could pause a local recording UI, etc.
        break
      case "evaluation_scores":
        console.log("Scores:", message)
        break
    }
  }, [])

  // ── Initiate call ───

  const startInterview = useCallback(async () => {
    setConnectionState("connecting")
    try {
      // 1. Acquire local media and add tracks BEFORE creating offer
      const localStream = await acquireMicrophone()
      for (const track of localStream.getTracks()) {
        addTrack(track, localStream)
      }

      // 2. Create and send offer
      const offer = await createOffer()
      const sdpPayload = {
            ...offer,
            job_id: jobId,        
            candidate_id: candidateId, 
      }
      console.log(`\n\nSending offer for job \n\n`, sdpPayload)
      const response = await fetch(
        `${import.meta.env.VITE_PUBLIC_API_URL}/api/v1/webrtc/offer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(sdpPayload),
        }
      )

      if (!response.ok) throw new Error(`Signaling failed: ${response.status}`)

      const { sdp, type, session_id } = await response.json()
      console.log(`\n\nSession id: ${session_id} \n\n`)
      setInterviewSessionId(session_id)
      console.log(`\n\n Interview session id: ${interview_session_id} \n\n`)
      await setRemoteAnswer({ sdp, type })

    } catch (error) {
      console.error("Failed to start interview:", error)
      setConnectionState("error")
      releaseAll()
    }
  }, [acquireMicrophone, addTrack, createOffer, setRemoteAnswer, releaseAll])

  // ── Screen share ──────────────────────────────────────────────────────────

  const startScreenShare = useCallback(async () => {
    try {
      const screenStream = await acquireScreenShare()
      for (const track of screenStream.getTracks()) {
        addTrack(track, screenStream)
        // Notify backend this is a screen track (since track.label varies by browser)
        dataChannelRef.current?.send(JSON.stringify({
          type: "screen_share_start",
          trackId: track.id,
        }))
        // Stop screen share if user clicks browser's "Stop sharing" button
        track.onended = () => {
          dataChannelRef.current?.send(JSON.stringify({ type: "screen_share_stop" }))
        }
      }
    } catch (error) {
      console.error("Screen share failed:", error)
    }
  }, [acquireScreenShare, addTrack, dataChannelRef])

  // ── End session ───────────────────────────────────────────────────────────

  const endInterview = useCallback(() => {
    dataChannelRef.current?.send(JSON.stringify({ type: "interview_ended" }))
    close()
    releaseAll()
    setConnectionState("ended")
  }, [close, releaseAll, dataChannelRef])

  // ── Render ──

  return (
    <div>
      <audio ref={agentAudioRef} autoPlay />

      <p>Status: {connectionState}</p>

      {connectionState === "idle" && (
        <button className="text-white"
        onClick={startInterview}>Start Interview</button>
      )}

      {connectionState === "connected" && (
        <>
          <button className="text-white" onClick={startScreenShare}>Share Screen</button>
          <button className="text-white" onClick={endInterview}>End Interview</button>
        </>
      )}

      {connectionState === "connecting" && <p>Connecting...</p>}
      {connectionState === "ended" && <p>Interview complete.</p>}
    </div>
  )
}