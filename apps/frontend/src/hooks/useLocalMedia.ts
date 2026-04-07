import { useRef, useCallback } from "react"

interface UseLocalMediaReturn {
  localStreamRef: React.RefObject<MediaStream | null>
  screenStreamRef: React.RefObject<MediaStream | null>
  acquireMicrophone: () => Promise<MediaStream>
  acquireScreenShare: () => Promise<MediaStream>
  releaseAll: () => void
}

export function useLocalMedia(): UseLocalMediaReturn {
  const localStreamRef = useRef<MediaStream | null>(null)
  const screenStreamRef = useRef<MediaStream | null>(null)

  const acquireMicrophone = useCallback(async (): Promise<MediaStream> => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,  // match Gemini's expected PCM format
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: {             // camera for candidate monitoring
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 15 },
      },
    })
    localStreamRef.current = stream
    return stream
  }, [])

  const acquireScreenShare = useCallback(async (): Promise<MediaStream> => {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        frameRate: { ideal: 5 },  // low FPS - sampler does the throttling anyway
      },
      audio: false,
    })
    // Label the track so backend frame_sampler detects it as screen
    // (track.label is set by browser, but we can use a convention via a 
    //  DataChannel event instead - see InterviewRoom below)
    screenStreamRef.current = stream
    return stream
  }, [])

  const releaseAll = useCallback((): void => {
    localStreamRef.current?.getTracks().forEach(t => t.stop())
    screenStreamRef.current?.getTracks().forEach(t => t.stop())
    localStreamRef.current = null
    screenStreamRef.current = null
  }, [])

  return { localStreamRef, screenStreamRef, acquireMicrophone, acquireScreenShare, releaseAll }
}