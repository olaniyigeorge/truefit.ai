export function Spiral({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none">
      <path
        d="M60 10 C85 10 105 30 105 55 C105 80 85 100 60 100 C35 100 20 82 20 60 C20 38 35 25 52 25 C69 25 80 38 80 52 C80 66 70 74 60 74 C50 74 44 67 44 60 C44 53 50 48 57 50"
        stroke="#22c55e" strokeWidth="2.5" strokeLinecap="round" fill="none"
        style={{ filter: "drop-shadow(0 0 8px #22c55e66)" }}
      />
    </svg>
  )
}

export function SpiralLogo({ size = 24, color = "#22c55e", opacity = 1 }: { size?: number; color?: string; opacity?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" style={{ opacity }}>
      <path
        d="M60 10 C85 10 105 30 105 55 C105 80 85 100 60 100 C35 100 20 82 20 60 C20 38 35 25 52 25 C69 25 80 38 80 52 C80 66 70 74 60 74 C50 74 44 67 44 60 C44 53 50 48 57 50"
        stroke={color} strokeWidth="2.5" strokeLinecap="round" fill="none"
        style={{ filter: `drop-shadow(0 0 8px ${color}66)` }}
      />
    </svg>
  )
}