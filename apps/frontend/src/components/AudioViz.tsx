import {useRef, useEffect} from 'react'



export function AudioViz({ stream }: { stream: MediaStream | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef    = useRef<number>(0)
 
  useEffect(() => {
    if (!stream || !canvasRef.current) return
    const ctx      = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 64
    const src = ctx.createMediaStreamSource(stream)
    src.connect(analyser)
    const buf    = new Uint8Array(analyser.frequencyBinCount)
    const canvas = canvasRef.current
    const c      = canvas.getContext("2d")!
 
    const draw = () => {
      rafRef.current = requestAnimationFrame(draw)
      analyser.getByteFrequencyData(buf)
      c.clearRect(0, 0, canvas.width, canvas.height)
      const bw = canvas.width / buf.length
      buf.forEach((v, i) => {
        const h = (v / 255) * canvas.height
        c.fillStyle = `rgba(34,197,94,${0.4 + (v / 255) * 0.6})`
        c.fillRect(i * bw, canvas.height - h, bw - 1, h)
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
      width={228}
      height={40}
      className="w-full rounded-sm"
      style={{ height: 40 }}
    />
  )
}