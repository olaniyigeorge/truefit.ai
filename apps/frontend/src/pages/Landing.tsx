import { useState, useEffect, useRef } from "react"

// ── Animated counter ──────────────────────────────────────────────────────────
function Counter({ to, suffix = "" }: { to: number; suffix?: string }) {
  const [val, setVal] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const observer = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return
      observer.disconnect()
      let start = 0
      const step = to / 60
      const t = setInterval(() => {
        start += step
        if (start >= to) { setVal(to); clearInterval(t) }
        else setVal(Math.floor(start))
      }, 16)
    })
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [to])
  return <span ref={ref}>{val.toLocaleString()}{suffix}</span>
}

// ── Spiral SVG (matches logo aesthetic) ──────────────────────────────────────
function Spiral({ size = 120, color = "#22c55e", opacity = 1 }: { size?: number; color?: string; opacity?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" style={{ opacity }}>
      <path d="M60 10 C85 10 105 30 105 55 C105 80 85 100 60 100 C35 100 20 82 20 60 C20 38 35 25 52 25 C69 25 80 38 80 52 C80 66 70 74 60 74 C50 74 44 67 44 60 C44 53 50 48 57 50"
        stroke={color} strokeWidth="2.5" strokeLinecap="round" fill="none"
        style={{ filter: `drop-shadow(0 0 8px ${color}66)` }} />
    </svg>
  )
}

// ── Noise texture overlay ─────────────────────────────────────────────────────
const noiseStyle: React.CSSProperties = {
  position: "fixed", inset: 0, pointerEvents: "none", zIndex: 999,
  opacity: 0.025,
  backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
}

// ── Grid background ───────────────────────────────────────────────────────────
const gridStyle: React.CSSProperties = {
  position: "fixed", inset: 0, pointerEvents: "none",
  backgroundImage: `
    linear-gradient(rgba(34,197,94,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(34,197,94,0.04) 1px, transparent 1px)
  `,
  backgroundSize: "48px 48px",
}

// ── Feature card ──────────────────────────────────────────────────────────────
function FeatureCard({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <div style={{
      background: "#0d1117",
      border: "1px solid #1f2937",
      borderRadius: 12,
      padding: "28px 24px",
      display: "flex", flexDirection: "column", gap: 14,
      transition: "border-color 0.2s, transform 0.2s",
      cursor: "default",
    }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "#22c55e44"
        ;(e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px)"
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "#1f2937"
        ;(e.currentTarget as HTMLDivElement).style.transform = "translateY(0)"
      }}
    >
      <div style={{ fontSize: 28 }}>{icon}</div>
      <div style={{ fontFamily: "'Georgia', serif", fontSize: 17, fontWeight: 700, color: "#f9fafb", lineHeight: 1.3 }}>{title}</div>
      <div style={{ fontSize: 13, color: "#6b7280", lineHeight: 1.7 }}>{body}</div>
    </div>
  )
}

// ── Step ──────────────────────────────────────────────────────────────────────
function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
      <div style={{
        width: 40, height: 40, borderRadius: "50%", flexShrink: 0,
        background: "transparent",
        border: "1px solid #22c55e44",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "monospace", fontSize: 13, color: "#22c55e",
      }}>{n}</div>
      <div>
        <div style={{ fontFamily: "'Georgia', serif", fontSize: 16, fontWeight: 700, color: "#f9fafb", marginBottom: 6 }}>{title}</div>
        <div style={{ fontSize: 13, color: "#6b7280", lineHeight: 1.7 }}>{body}</div>
      </div>
    </div>
  )
}

// ── Main landing page ─────────────────────────────────────────────────────────
export default function Landing() {
  const [email, setEmail] = useState("")
  const [submitted, setSubmitted] = useState(false)

  return (
    <div style={{
      minHeight: "100vh",
      background: "#030712",
      color: "#f9fafb",
      fontFamily: "monospace",
      overflowX: "hidden",
    }}>
      <div style={noiseStyle} />
      <div style={gridStyle} />

      {/* ── Nav ── */}
      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 40px", height: 56,
        background: "rgba(3,7,18,0.85)",
        backdropFilter: "blur(12px)",
        borderBottom: "1px solid #111827",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Spiral size={28} />
          <span style={{ fontFamily: "'Georgia', serif", fontSize: 17, fontWeight: 700, letterSpacing: "-0.5px" }}>
            True<span style={{ color: "#22c55e" }}>Fit</span>
            <span style={{ color: "#374151", fontSize: 11, fontFamily: "monospace", fontWeight: 400, marginLeft: 6 }}>.ai</span>
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          {["Product", "For Hirers", "For Candidates", "Pricing"].map(l => (
            <a key={l} href="#" style={{
              fontSize: 13, color: "#6b7280", textDecoration: "none",
              transition: "color 0.15s",
            }}
              onMouseEnter={e => (e.currentTarget.style.color = "#f9fafb")}
              onMouseLeave={e => (e.currentTarget.style.color = "#6b7280")}
            >{l}</a>
          ))}
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button style={{
            padding: "7px 16px", background: "transparent",
            border: "1px solid #1f2937", borderRadius: 6,
            color: "#9ca3af", fontSize: 13, fontFamily: "monospace", cursor: "pointer",
            transition: "all 0.15s",
          }}
            onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#374151"; (e.currentTarget as HTMLButtonElement).style.color = "#f9fafb" }}
            onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#1f2937"; (e.currentTarget as HTMLButtonElement).style.color = "#9ca3af" }}
          >Log in</button>
          <button style={{
            padding: "7px 16px", background: "#22c55e",
            border: "none", borderRadius: 6,
            color: "#000", fontSize: 13, fontFamily: "monospace",
            fontWeight: 700, cursor: "pointer", transition: "filter 0.15s",
          }}
            onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.filter = "brightness(1.1)")}
            onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.filter = "brightness(1)")}
          >Get Early Access</button>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section style={{
        position: "relative",
        minHeight: "100vh",
        display: "flex", alignItems: "center", justifyContent: "center",
        flexDirection: "column",
        textAlign: "center",
        padding: "120px 24px 80px",
      }}>
        {/* Glow */}
        <div style={{
          position: "absolute", top: "30%", left: "50%", transform: "translate(-50%,-50%)",
          width: 600, height: 600, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(34,197,94,0.08) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />

        {/* Badge */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "5px 14px",
          background: "rgba(34,197,94,0.08)",
          border: "1px solid rgba(34,197,94,0.2)",
          borderRadius: 20,
          fontSize: 11, color: "#22c55e",
          letterSpacing: "0.15em", textTransform: "uppercase",
          marginBottom: 32,
        }}>
          <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#22c55e", animation: "pulse 2s infinite" }} />
          Now in Early Access
        </div>

        <div style={{ position: "relative", marginBottom: 28 }}>
          <Spiral size={80} color="#22c55e" opacity={0.15} style={{ position: "absolute", top: -20, right: -40 }} />
          <h1 style={{
            fontFamily: "'Georgia', serif",
            fontSize: "clamp(40px, 6vw, 76px)",
            fontWeight: 700,
            lineHeight: 1.08,
            letterSpacing: "-2px",
            margin: 0,
            color: "#f9fafb",
          }}>
            Hire the right people.<br />
            <span style={{ color: "#22c55e" }}>Fast. Accurately.</span><br />
            At scale.
          </h1>
        </div>

        <p style={{
          fontSize: "clamp(15px, 2vw, 18px)",
          color: "#6b7280",
          maxWidth: 560,
          lineHeight: 1.7,
          marginBottom: 44,
        }}>
          TrueFit runs AI-powered voice interviews that screen candidates, generate structured evaluations,
          and surface the right hires — so your team focuses on decisions, not scheduling.
        </p>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center" }}>
          <button style={{
            padding: "14px 32px",
            background: "#22c55e", border: "none", borderRadius: 8,
            color: "#000", fontSize: 15, fontWeight: 700, fontFamily: "monospace",
            letterSpacing: "0.05em", cursor: "pointer",
            transition: "all 0.15s",
            boxShadow: "0 0 32px rgba(34,197,94,0.25)",
          }}
            onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 0 48px rgba(34,197,94,0.4)" }}
            onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 0 32px rgba(34,197,94,0.25)" }}
          >
            Start Hiring Smarter →
          </button>
          <button style={{
            padding: "14px 32px",
            background: "transparent",
            border: "1px solid #1f2937", borderRadius: 8,
            color: "#9ca3af", fontSize: 15, fontFamily: "monospace",
            cursor: "pointer", transition: "all 0.15s",
          }}
            onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#374151"; (e.currentTarget as HTMLButtonElement).style.color = "#f9fafb" }}
            onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#1f2937"; (e.currentTarget as HTMLButtonElement).style.color = "#9ca3af" }}
          >
            I'm a Candidate
          </button>
        </div>

        {/* Terminal preview */}
        <div style={{
          marginTop: 72,
          width: "100%", maxWidth: 720,
          background: "#0d1117",
          border: "1px solid #1f2937",
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 32px 80px rgba(0,0,0,0.6), 0 0 0 1px #1f2937",
          textAlign: "left",
        }}>
          {/* Window chrome */}
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "12px 16px",
            background: "#111827",
            borderBottom: "1px solid #1f2937",
          }}>
            {["#ef4444", "#f59e0b", "#22c55e"].map(c => (
              <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c, opacity: 0.7 }} />
            ))}
            <span style={{ marginLeft: 8, fontSize: 11, color: "#374151" }}>truefit · interview session</span>
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", animation: "pulse 2s infinite" }} />
              <span style={{ fontSize: 10, color: "#22c55e" }}>LIVE</span>
            </div>
          </div>
          {/* Fake transcript */}
          <div style={{ padding: "20px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
            {[
              { who: "AI INTERVIEWER", color: "#22c55e", bg: "#0d1f13", border: "#166534", text: "Tell me about a time you had to make a technical decision under significant time pressure. What was your process?" },
              { who: "CANDIDATE", color: "#60a5fa", bg: "#0d1527", border: "#1e3a5f", text: "During our last product launch, our primary database started showing latency spikes 2 hours before go-live. I had to decide between rolling back migrations or hot-patching the query planner..." },
              { who: "AI INTERVIEWER", color: "#22c55e", bg: "#0d1f13", border: "#166534", text: "Interesting. How did you weigh the risk of the hot-patch against the rollback timeline?" },
            ].map((m, i) => (
              <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: m.who === "CANDIDATE" ? "flex-end" : "flex-start" }}>
                <span style={{ fontSize: 10, color: m.color, letterSpacing: "0.1em" }}>{m.who}</span>
                <div style={{
                  maxWidth: "85%", background: m.bg, border: `1px solid ${m.border}`,
                  borderRadius: m.who === "CANDIDATE" ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
                  padding: "10px 14px", fontSize: 13, color: "#d1d5db", lineHeight: 1.6,
                  fontFamily: "'Georgia', serif",
                }}>{m.text}</div>
              </div>
            ))}
            {/* Typing indicator */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 10, color: "#22c55e", letterSpacing: "0.1em" }}>AI INTERVIEWER</span>
              <div style={{ display: "flex", gap: 4 }}>
                {[0, 1, 2].map(i => (
                  <div key={i} style={{
                    width: 5, height: 5, borderRadius: "50%", background: "#22c55e",
                    animation: `pulse 1.2s infinite ${i * 0.2}s`,
                  }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats ── */}
      <section style={{
        borderTop: "1px solid #111827", borderBottom: "1px solid #111827",
        padding: "48px 40px",
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 0,
        maxWidth: 900, margin: "0 auto",
        textAlign: "center",
      }}>
        {[
          { val: 90, suffix: "%", label: "Reduction in time-to-screen" },
          { val: 3, suffix: "x", label: "More candidates evaluated" },
          { val: 30, suffix: " min", label: "Average interview duration" },
          { val: 98, suffix: "%", label: "Candidate satisfaction" },
        ].map((s, i) => (
          <div key={i} style={{
            padding: "20px 24px",
            borderRight: i < 3 ? "1px solid #111827" : "none",
          }}>
            <div style={{
              fontFamily: "'Georgia', serif",
              fontSize: 40, fontWeight: 700,
              color: "#22c55e",
              letterSpacing: "-1px",
            }}>
              <Counter to={s.val} suffix={s.suffix} />
            </div>
            <div style={{ fontSize: 12, color: "#6b7280", marginTop: 6, lineHeight: 1.5 }}>{s.label}</div>
          </div>
        ))}
      </section>

      {/* ── Features ── */}
      <section style={{ maxWidth: 1080, margin: "0 auto", padding: "100px 40px" }}>
        <div style={{ textAlign: "center", marginBottom: 60 }}>
          <div style={{ fontSize: 10, letterSpacing: "0.3em", textTransform: "uppercase", color: "#22c55e", marginBottom: 14 }}>
            What TrueFit Does
          </div>
          <h2 style={{
            fontFamily: "'Georgia', serif",
            fontSize: "clamp(28px, 4vw, 44px)",
            fontWeight: 700, letterSpacing: "-1px",
            color: "#f9fafb", margin: 0,
          }}>
            The complete interview infrastructure
          </h2>
        </div>

        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 16,
        }}>
          <FeatureCard
            icon="🎙"
            title="Real-time Voice Interviews"
            body="AI conducts full spoken interviews over WebRTC. Natural conversation, no scripts — the agent adapts to each answer and asks intelligent follow-ups."
          />
          <FeatureCard
            icon="⚡"
            title="Instant Structured Evaluation"
            body="Every interview generates a structured scorecard: technical depth, communication clarity, culture signals — with verbatim evidence from the conversation."
          />
          <FeatureCard
            icon="🎯"
            title="Role-specific Intelligence"
            body="Configure interview depth, topics, and question weighting per job. A senior backend engineer interview is nothing like a product manager screen."
          />
          <FeatureCard
            icon="📊"
            title="Comparative Candidate Ranking"
            body="See every candidate scored on the same rubric, side by side. Remove unconscious bias from the top of your funnel."
          />
          <FeatureCard
            icon="🔄"
            title="Resume-aware Questioning"
            body="TrueFit reads candidate resumes and probes their actual experience — not generic questions. Every interview is personalised."
          />
          <FeatureCard
            icon="🛡"
            title="Candidate-grade Experience"
            body="Candidates get a fair, stress-reduced interview. No scheduling friction, no intimidating panels for a first screen."
          />
        </div>
      </section>

      {/* ── How it works ── */}
      <section style={{
        borderTop: "1px solid #111827",
        padding: "100px 40px",
      }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: 60 }}>
            <div style={{ fontSize: 10, letterSpacing: "0.3em", textTransform: "uppercase", color: "#22c55e", marginBottom: 14 }}>
              How It Works
            </div>
            <h2 style={{
              fontFamily: "'Georgia', serif",
              fontSize: "clamp(28px, 4vw, 44px)",
              fontWeight: 700, letterSpacing: "-1px",
              color: "#f9fafb", margin: 0,
            }}>
              From job post to shortlist<br />in hours
            </h2>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
            <Step n="01" title="Post a role and configure your interview"
              body="Define the skills, topics, and depth. Set max questions, duration, and any custom focus areas. TrueFit builds the interview brief." />
            <div style={{ width: 1, height: 24, background: "linear-gradient(#22c55e22, transparent)", margin: "0 20px" }} />
            <Step n="02" title="Candidates join via a link — no app required"
              body="They open a browser tab, grant mic access, and the AI interviewer begins. The whole experience takes under 30 minutes." />
            <div style={{ width: 1, height: 24, background: "linear-gradient(#22c55e22, transparent)", margin: "0 20px" }} />
            <Step n="03" title="Receive scored evaluations instantly"
              body="The moment the interview ends, you get a structured scorecard with transcript evidence, red flags, and a hire/no-hire signal." />
            <div style={{ width: 1, height: 24, background: "linear-gradient(#22c55e22, transparent)", margin: "0 20px" }} />
            <Step n="04" title="Shortlist and schedule the right people"
              body="Use TrueFit's ranking to decide who moves forward. Spend your human interview time where it actually matters." />
          </div>
        </div>
      </section>

      {/* ── For candidates ── */}
      <section style={{
        borderTop: "1px solid #111827",
        padding: "100px 40px",
        background: "linear-gradient(180deg, transparent, rgba(34,197,94,0.02), transparent)",
      }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 80, alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 10, letterSpacing: "0.3em", textTransform: "uppercase", color: "#22c55e", marginBottom: 14 }}>
              For Candidates
            </div>
            <h2 style={{
              fontFamily: "'Georgia', serif",
              fontSize: "clamp(28px, 3.5vw, 40px)",
              fontWeight: 700, letterSpacing: "-1px",
              color: "#f9fafb", marginBottom: 20, lineHeight: 1.15,
            }}>
              Practice until you're<br />
              <span style={{ color: "#22c55e" }}>genuinely ready</span>
            </h2>
            <p style={{ fontSize: 14, color: "#6b7280", lineHeight: 1.8, marginBottom: 28 }}>
              TrueFit gives candidates unlimited AI mock interviews on real job descriptions.
              Get detailed feedback on your answers, filler word analysis, and
              specific guidance on what to improve before the real thing.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                "Interviews based on actual job descriptions — not generic questions",
                "Detailed feedback on content, clarity, and confidence signals",
                "Track improvement across multiple sessions",
                "Get recommended to companies hiring for your profile",
              ].map(t => (
                <div key={t} style={{ display: "flex", gap: 10, fontSize: 13, color: "#9ca3af" }}>
                  <span style={{ color: "#22c55e", flexShrink: 0 }}>✓</span>
                  {t}
                </div>
              ))}
            </div>
          </div>

          <div style={{
            background: "#0d1117",
            border: "1px solid #1f2937",
            borderRadius: 12,
            padding: 28,
            display: "flex", flexDirection: "column", gap: 16,
          }}>
            <div style={{ fontSize: 11, letterSpacing: "0.15em", textTransform: "uppercase", color: "#374151" }}>
              Post-interview feedback
            </div>
            {[
              { label: "Technical Depth", score: 87, color: "#22c55e" },
              { label: "Communication Clarity", score: 72, color: "#60a5fa" },
              { label: "Problem Structuring", score: 91, color: "#22c55e" },
              { label: "Culture Alignment", score: 68, color: "#f59e0b" },
            ].map(m => (
              <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#9ca3af" }}>
                  <span>{m.label}</span>
                  <span style={{ color: m.color, fontWeight: 700 }}>{m.score}</span>
                </div>
                <div style={{ height: 4, background: "#111827", borderRadius: 2 }}>
                  <div style={{
                    height: "100%", width: `${m.score}%`, background: m.color,
                    borderRadius: 2, transition: "width 1s ease",
                    boxShadow: `0 0 8px ${m.color}66`,
                  }} />
                </div>
              </div>
            ))}
            <div style={{
              marginTop: 8,
              padding: "14px",
              background: "rgba(34,197,94,0.05)",
              border: "1px solid rgba(34,197,94,0.15)",
              borderRadius: 8,
              fontSize: 12, color: "#6b7280", lineHeight: 1.6,
              fontFamily: "'Georgia', serif", fontStyle: "italic",
            }}>
              "Strong candidate. Demonstrates clear system design thinking and communicates trade-offs well.
              Recommend for technical round."
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA / Waitlist ── */}
      <section style={{
        borderTop: "1px solid #111827",
        padding: "100px 40px",
        textAlign: "center",
        position: "relative",
        overflow: "hidden",
      }}>
        <div style={{
          position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          width: 500, height: 500, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(34,197,94,0.06) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />

        <div style={{ position: "relative" }}>
          <Spiral size={60} color="#22c55e" opacity={0.2} />
          <h2 style={{
            fontFamily: "'Georgia', serif",
            fontSize: "clamp(32px, 5vw, 56px)",
            fontWeight: 700, letterSpacing: "-1.5px",
            color: "#f9fafb", marginBottom: 16,
          }}>
            Ready to hire better?
          </h2>
          <p style={{ fontSize: 16, color: "#6b7280", marginBottom: 40, lineHeight: 1.6 }}>
            Join companies already using TrueFit to screen smarter<br />
            and candidates building real interview confidence.
          </p>

          {submitted ? (
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 10,
              padding: "16px 28px",
              background: "rgba(34,197,94,0.1)",
              border: "1px solid rgba(34,197,94,0.3)",
              borderRadius: 8, fontSize: 14, color: "#22c55e",
            }}>
              ✓ You're on the list — we'll be in touch soon
            </div>
          ) : (
            <div style={{
              display: "flex", gap: 0, maxWidth: 440, margin: "0 auto",
              border: "1px solid #1f2937", borderRadius: 8, overflow: "hidden",
            }}>
              <input
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="your@email.com"
                type="email"
                style={{
                  flex: 1, padding: "14px 16px",
                  background: "#0d1117", border: "none", outline: "none",
                  color: "#f9fafb", fontSize: 14, fontFamily: "monospace",
                }}
              />
              <button
                onClick={() => { if (email.includes("@")) setSubmitted(true) }}
                style={{
                  padding: "14px 24px",
                  background: "#22c55e", border: "none",
                  color: "#000", fontSize: 13, fontWeight: 700,
                  fontFamily: "monospace", cursor: "pointer",
                  letterSpacing: "0.05em", whiteSpace: "nowrap",
                  transition: "filter 0.15s",
                }}
                onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.filter = "brightness(1.1)")}
                onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.filter = "brightness(1)")}
              >
                Join Waitlist →
              </button>
            </div>
          )}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer style={{
        borderTop: "1px solid #111827",
        padding: "32px 40px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Spiral size={20} />
          <span style={{ fontFamily: "'Georgia', serif", fontSize: 14, fontWeight: 700 }}>
            True<span style={{ color: "#22c55e" }}>Fit</span>.ai
          </span>
        </div>
        <div style={{ fontSize: 12, color: "#374151" }}>
          © 2025 TrueFit.ai · All rights reserved
        </div>
        <div style={{ display: "flex", gap: 20 }}>
          {["Privacy", "Terms", "Contact"].map(l => (
            <a key={l} href="#" style={{ fontSize: 12, color: "#374151", textDecoration: "none" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#6b7280")}
              onMouseLeave={e => (e.currentTarget.style.color = "#374151")}
            >{l}</a>
          ))}
        </div>
      </footer>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @media (max-width: 768px) {
          nav > div:nth-child(2) { display: none; }
        }
      `}</style>
    </div>
  )
}