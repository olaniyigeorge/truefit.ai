import {useState, useRef, useEffect} from "react"

export function Counter({ to, suffix }: { to: number; suffix: string }) {
  const [val, setVal] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
 
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        observer.disconnect()
        const start = performance.now()
        const dur = 1200
        const tick = (now: number) => {
          const t = Math.min((now - start) / dur, 1)
          setVal(Math.round(t * to))
          if (t < 1) requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      },
      { threshold: 0.5 }
    )
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [to])
 
  return <span ref={ref}>{val}{suffix}</span>
}