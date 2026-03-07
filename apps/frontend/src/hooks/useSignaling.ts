import {useRef, useEffect, useCallback} from 'react'

type SignalingMessage = {
    type: string
    candidate?: RTCIceCandidateInit
    [key: string]: unknown
}

type UseSignalingOptions = {
    sessionId: string
    onIceCandidate: (candidate: RTCIceCandidateInit) => void
    onError?: (error: Event) => void
}

export const useSignaling = ({sessionId, onIceCandidate, onError}: UseSignalingOptions) => {

    const socketRef = useRef<WebSocket|null>(null)
    
    const sendCandidate = useCallback((candidate: RTCIceCandidateInit) => {
        const socket = socketRef.current
        if(socket && socket.readyState === WebSocket.OPEN){
            socket.send(JSON.stringify({type: 'ice_candidate', candidate}))
        }
    },[])


    useEffect(() => {
        const socket = new WebSocket(`${import.meta.env.VITE_PUBLIC_WS_URL}/v1/sessions/${sessionId}/ice`)

        socket.onopen = () => {
            socket.send(JSON.stringify({type: 'sender'}))
        }

        socket.onmessage = (event: MessageEvent<string>) => {
            const message: SignalingMessage = JSON.parse(event.data)
            if (message.type === "ice_candidate" && message.candidate !== undefined) {
                onIceCandidate(message.candidate)
            }
        }

        socket.onerror = (error) => {
            onError?.(error)
        }

        socket.onclose = () => {
            socketRef.current = null
        }

        socketRef.current = socket

        return () => {
            socket.close()
            socketRef.current = null
        }
    }, [sessionId])

    return {sendCandidate}
}