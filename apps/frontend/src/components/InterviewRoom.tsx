
import {useState, useEffect, useRef} from "react"
import { usePeerConnection } from "@/hooks/usePeerConnection"


type InterviewRoomProps = {
    sessionId: string
}

export default function InterviewRoom ({sessionId}: InterviewRoomProps) {

    const agentAudioRef = useRef<HTMLAudioElement|null>(null)

    // const peerConnection = useRef<RTCPeerConnection | null>(null)

    const {peerConnectionRef, createOffer, setRemoteAnswer, addTrack} = usePeerConnection({
        sessionId,
        onRemoteAudioTrack: (stream) => {
            if(agentAudioRef.current){
                agentAudioRef.current.srcObject = stream
                agentAudioRef.current.play()
            }
            //attach to an audio element to play agent voice
            // const stream = new MediaStream([track])
            // agentAudioRef.current!.srcObject = stream
            // agentAudioRef.current!.play()
        },
        onDataChannel: (channel) => {
            //hand off to data channel handler
            channel.onmessage = (event: MessageEvent<string>) => {
                const message = JSON.parse(event.data)
                console.log("Data channel message", message)
                // dispatch({type: message.type, payload: message})
            }
        },
        onError: (error) => {
            console.error("Peer connection error", error)
        }
    })


    const makeCall = async () => {
        try {
            const offer = await createOffer()
            const response = await fetch(`${import.meta.env.VITE_PUBLIC_API_URL}/v1/sessions/${sessionId}/offer`, {
                method: 'POST',
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(offer)
            })

            const answer: RTCSessionDescriptionInit = await response.json()
            await setRemoteAnswer(answer)
        } catch (error) {
            console.error("Failed to start call", error)
        }
    }

    return(
        <div>
            <audio ref={agentAudioRef}/>
            <button onClick={makeCall}>Start Interview</button>
        </div>
    )
}