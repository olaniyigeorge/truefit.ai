
import {useRef, useEffect, useCallback} from "react"
import { useSignaling } from "./useSignaling"


type UsePeerConnectionOptions = {
    sessionId: string
    onRemoteAudioTrack: (track: MediaStream) => void
    onDataChannel: (channel: RTCDataChannel) => void
    onError?: (error: Error) => void
}

export const usePeerConnection = ({sessionId, onRemoteAudioTrack, onDataChannel, onError}: UsePeerConnectionOptions) => {
    const peerConnectionRef = useRef<RTCPeerConnection|null>(null)

    const {sendCandidate} = useSignaling({
        sessionId,
        onIceCandidate: (candidate) => {
            peerConnectionRef.current?.addIceCandidate(
                new RTCIceCandidate(candidate)
            ).catch((err) => onError?.(err))
        }
    })


    const initalizePeerConnection = useCallback(() => {
        const pc = new RTCPeerConnection({
            iceServers: [
                {urls: "stun:stun.l.google.com:19302"},
                {urls: "stun:stun1.l.google.com:19302"}
            ]
        })

        pc.onicecandidate = (event) => {
            if(event.candidate){
                sendCandidate(event.candidate.toJSON())
            }
        }

        pc.ontrack = (event: RTCTrackEvent) => {
            if(event.track.kind === "audio" && event.streams[0]){
                onRemoteAudioTrack(event.streams[0])
            }
        }

        pc.ondatachannel = (event) => {
            onDataChannel(event.channel)
        }


        pc.onconnectionstatechange = () => {
            if(pc.connectionState === "failed"||
                pc.connectionState === "disconnected"
            ){
                onError?.(new Error(`Peer connection ${pc.connectionState}`))
            }
        }

        peerConnectionRef.current = pc
        return pc
    }, [sendCandidate, onRemoteAudioTrack, onDataChannel, onError])   

    const createOffer = useCallback(async () => {
        const pc = peerConnectionRef.current
        if(!pc) throw new Error("Peer connection not initialized")
        
        const offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        return offer
    }, [])

    const setRemoteAnswer = useCallback(async (answer: RTCSessionDescriptionInit) => {
        const pc = peerConnectionRef.current
        if(!pc) throw new Error("peer connection not initailized")

        await pc.setRemoteDescription(new RTCSessionDescription(answer))
    }, [])

    const addTrack = useCallback((track: MediaStreamTrack, stream: MediaStream) => {
        peerConnectionRef.current?.addTrack(track, stream)
    }, [])


    useEffect(() => {
        initalizePeerConnection()

        return() => {
            peerConnectionRef.current?.close()
            peerConnectionRef.current = null
        }
    }, [sessionId]) //reinitialize if the session changes
    

    return {
        peerConnectionRef,
        createOffer,
        setRemoteAnswer,
        addTrack
    }
}