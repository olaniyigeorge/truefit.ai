
// import {useRef, useEffect, useCallback} from "react"
// import { useSignaling } from "./useSignaling"


// type UsePeerConnectionOptions = {
//     sessionId: string
//     onRemoteAudioTrack: (track: MediaStream) => void
//     onDataChannel: (channel: RTCDataChannel) => void
//     onError?: (error: Error) => void
// }

// export const usePeerConnection = ({sessionId, onRemoteAudioTrack, onDataChannel, onError}: UsePeerConnectionOptions) => {
//     const peerConnectionRef = useRef<RTCPeerConnection|null>(null)

//     const {sendCandidate} = useSignaling({
//         sessionId,
//         onIceCandidate: (candidate) => {
//             peerConnectionRef.current?.addIceCandidate(
//                 new RTCIceCandidate(candidate)
//             ).catch((err) => onError?.(err))
//         }
//     })


//     const initalizePeerConnection = useCallback(() => {
//         const pc = new RTCPeerConnection({
//             iceServers: [
//                 {urls: "stun:stun.l.google.com:19302"},
//                 {urls: "stun:stun1.l.google.com:19302"}
//             ]
//         })

//         pc.onicecandidate = (event) => {
//             if(event.candidate){
//                 sendCandidate(event.candidate.toJSON())
//             }
//         }

//         pc.ontrack = (event: RTCTrackEvent) => {
//             if(event.track.kind === "audio" && event.streams[0]){
//                 onRemoteAudioTrack(event.streams[0])
//             }
//         }

//         pc.ondatachannel = (event) => {
//             onDataChannel(event.channel)
//         }


//         pc.onconnectionstatechange = () => {
//             if(pc.connectionState === "failed"||
//                 pc.connectionState === "disconnected"
//             ){
//                 onError?.(new Error(`Peer connection ${pc.connectionState}`))
//             }
//         }

//         peerConnectionRef.current = pc
//         return pc
//     }, [sendCandidate, onRemoteAudioTrack, onDataChannel, onError])   

//     const createOffer = useCallback(async () => {
//         const pc = peerConnectionRef.current
//         if(!pc) throw new Error("Peer connection not initialized")
        
//         const offer = await pc.createOffer()
//         await pc.setLocalDescription(offer)
//         return offer
//     }, [])

//     const setRemoteAnswer = useCallback(async (answer: RTCSessionDescriptionInit) => {
//         const pc = peerConnectionRef.current
//         if(!pc) throw new Error("peer connection not initailized")

//         await pc.setRemoteDescription(new RTCSessionDescription(answer))
//     }, [])

//     const addTrack = useCallback((track: MediaStreamTrack, stream: MediaStream) => {
//         peerConnectionRef.current?.addTrack(track, stream)
//     }, [])


//     useEffect(() => {
//         initalizePeerConnection()

//         return() => {
//             peerConnectionRef.current?.close()
//             peerConnectionRef.current = null
//         }
//     }, [sessionId]) //reinitialize if the session changes
    

//     return {
//         peerConnectionRef,
//         createOffer,
//         setRemoteAnswer,
//         addTrack
//     }
// }




// hooks/usePeerConnection.ts
import { useRef, useCallback, useEffect } from "react"

const ICE_SERVERS: RTCConfiguration = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
  ],
}

interface UsePeerConnectionOptions {
  sessionId: string
  onRemoteAudioTrack: (stream: MediaStream) => void
  onDataChannel: (channel: RTCDataChannel) => void
  onConnectionStateChange?: (state: RTCPeerConnectionState) => void
  onError: (error: Error) => void
}

interface UsePeerConnectionReturn {
  peerConnectionRef: React.RefObject<RTCPeerConnection | null>
  dataChannelRef: React.RefObject<RTCDataChannel | null>
  createOffer: () => Promise<RTCSessionDescriptionInit>
  setRemoteAnswer: (answer: RTCSessionDescriptionInit) => Promise<void>
  addTrack: (track: MediaStreamTrack, stream: MediaStream) => void
  close: () => void
}

export function usePeerConnection({
  sessionId,
  onRemoteAudioTrack,
  onDataChannel,
  onConnectionStateChange,
  onError,
}: UsePeerConnectionOptions): UsePeerConnectionReturn {
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)
  const pendingCandidates = useRef<RTCIceCandidate[]>([])
  const remoteAnswerSet = useRef(false)

  // ── Initialize PC ────────────────────────────────────────────────────────

  const getOrCreatePC = useCallback((): RTCPeerConnection => {
    if (peerConnectionRef.current) return peerConnectionRef.current

    const pc = new RTCPeerConnection(ICE_SERVERS)
    peerConnectionRef.current = pc

    // Remote track → play agent audio
    pc.ontrack = (event: RTCTrackEvent) => {
      if (event.track.kind === "audio") {
        const [stream] = event.streams
        onRemoteAudioTrack(stream ?? new MediaStream([event.track]))
      }
    }

    // Trickle ICE — send each candidate to backend as discovered
    pc.onicecandidate = async (event: RTCPeerConnectionIceEvent) => {
      if (!event.candidate) return
      const candidate = event.candidate

      // If answer isn't set yet, queue — backend needs remote desc first
      if (!remoteAnswerSet.current) {
        pendingCandidates.current.push(candidate)
        return
      }

      await sendIceCandidate(sessionId, candidate)
    }

    pc.onconnectionstatechange = () => {
      onConnectionStateChange?.(pc.connectionState)
      if (pc.connectionState === "failed") {
        onError(new Error("WebRTC connection failed"))
      }
    }

    pc.onicecandidateerror = (event) => {
      console.warn("ICE candidate error", event)
    }

    // Frontend MUST create the DataChannel (backend listens for ondatachannel)
    const channel = pc.createDataChannel("interview", {
      ordered: true,
    })
    dataChannelRef.current = channel
    onDataChannel(channel)

    return pc
  }, [sessionId, onRemoteAudioTrack, onDataChannel, onConnectionStateChange, onError])

  // ── Create offer ───

  const createOffer = useCallback(async (): Promise<RTCSessionDescriptionInit> => {
    const pc = getOrCreatePC()
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    return offer
  }, [getOrCreatePC])

  // ── Set remote answer ───

  const setRemoteAnswer = useCallback(async (answer: RTCSessionDescriptionInit): Promise<void> => {
    const pc = peerConnectionRef.current
    if (!pc) throw new Error("PeerConnection not initialized")

    await pc.setRemoteDescription(new RTCSessionDescription(answer))
    remoteAnswerSet.current = true

    // Flush any candidates that arrived before the answer
    for (const candidate of pendingCandidates.current) {
      await sendIceCandidate(sessionId, candidate)
    }
    pendingCandidates.current = []
  }, [sessionId])

  // ── Add track ───

  const addTrack = useCallback((track: MediaStreamTrack, stream: MediaStream): void => {
    const pc = getOrCreatePC()
    pc.addTrack(track, stream)
  }, [getOrCreatePC])

  // ── Cleanup ───

  const close = useCallback((): void => {
    dataChannelRef.current?.close()
    peerConnectionRef.current?.close()
    peerConnectionRef.current = null
    dataChannelRef.current = null
    remoteAnswerSet.current = false
    pendingCandidates.current = []
  }, [])

  useEffect(() => () => close(), [close])

  return { peerConnectionRef, dataChannelRef, createOffer, setRemoteAnswer, addTrack, close }
}

// ── Helpers ──

async function sendIceCandidate(sessionId: string, candidate: RTCIceCandidate): Promise<void> {
  await fetch(`${import.meta.env.VITE_PUBLIC_API_URL}/api/v1/webrtc/ice-candidate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      candidate: candidate.candidate,
      sdpMid: candidate.sdpMid,
      sdpMLineIndex: candidate.sdpMLineIndex,
    }),
  })
}