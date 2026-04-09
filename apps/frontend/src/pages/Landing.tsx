
import { useState } from "react"
import {FeatureCard} from "@/components/FeatureCard"
import {Step} from "@/components/NumberedStep"
import { SpiralLogo } from "@/components/Spiral"
import {Counter} from "@/components/AnimatedCounter"
import { ChevronRight } from "lucide-react"


// ── Main landing page ─
export default function Landing() {
  const [email, setEmail] = useState("")
  const [submitted, setSubmitted] = useState(false)
 
  return (
    <div className="min-h-screen bg-background text-foreground font-mono overflow-x-hidden">
      {/* Background overlays */}
      <div className="overlay-noise" />
      <div className="overlay-grid" />
 
      {/* ── Nav ── */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-10 h-14 bg-background/85 backdrop-blur-md border-b border-border">
        <div className="flex items-center gap-2.5">
          <SpiralLogo size={24} />
          <span className="font-serif text-base font-bold">
            True<span className="text-primary">Fit</span>.ai
          </span>
        </div>
 
        <div className="hidden md:flex items-center gap-8">
          {["Product", "For Hirers", "For Candidates", "Pricing"].map(l => (
            <a
              key={l}
              href="#"
              className="text-[13px] text-muted-foreground hover:text-foreground transition-colors no-underline"
            >
              {l}
            </a>
          ))}
        </div>
 
        <div className="flex items-center gap-3">
          <a href="/auth" className="text-[13px] text-muted-foreground hover:text-foreground transition-colors no-underline">
            Join
          </a>
          <a
            href={`/itv/183c3d37-c69d-490a-8618-f06e97254317/aa6f4e32-67b9-489e-b000-4de830d85cb1`}
            className="px-4 py-2 bg-primary text-primary-foreground text-[13px] font-bold tracking-wide rounded hover:brightness-110 transition-all no-underline"
          >
            Get Early Access
          </a>
        </div>
      </nav>
 
      {/* ── Hero ── */}
      <section className="relative min-h-screen flex flex-col items-center justify-center text-center px-6 pt-[120px] pb-20">
        {/* Glow */}
        <div
          className="absolute pointer-events-none"
          style={{
            top: "30%", left: "50%", transform: "translate(-50%,-50%)",
            width: 600, height: 600, borderRadius: "50%",
            background: "radial-gradient(circle, rgba(34,197,94,0.08) 0%, transparent 70%)",
          }}
        />
 
        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-primary/8 border border-primary/20 rounded-full text-[11px] text-primary tracking-[0.15em] uppercase mb-8">
          <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          Now in Early Access
        </div>
 
        <div className="relative mb-7">
          <h1 className="font-serif text-[clamp(40px,6vw,76px)] font-bold leading-[1.08] tracking-[-2px] text-foreground">
            Hire the right people.<br />
            <span className="text-primary">Fast. Accurately.</span><br />
            At scale.
          </h1>
        </div>
 
        <p className="text-[clamp(15px,2vw,18px)] text-muted-foreground max-w-[560px] leading-relaxed mb-11">
          TrueFit runs AI-powered voice interviews that screen candidates, generate structured evaluations,
          and surface the right hires - so your team focuses on decisions, not scheduling.
        </p>
 
        <div className="flex flex-wrap gap-3 justify-center mb-16">
          <a
            href="/auth"
            className="px-6 py-3.5 flex items-center gap-2 bg-primary text-primary-foreground text-[13px] font-bold tracking-wide rounded hover:brightness-110 transition-all no-underline"
          >
            <>Start Hiring Smarter</>
            <ChevronRight size={16} className="ml-1" />
          </a>
          <a
            href="#"
            className="px-6 py-3.5 bg-transparent border border-border text-foreground text-[13px] font-bold tracking-wide rounded hover:bg-accent transition-all no-underline"
          >
            I'm a Candidate
          </a>
        </div>
 
        {/* Chat preview */}
        <div className="w-full max-w-lg bg-card border border-border rounded-xl overflow-hidden text-left">
          <div className="flex items-center gap-1.5 px-4 py-3 border-b border-border">
            {["#ef4444", "#f59e0b", "#22c55e"].map(c => (
              <div key={c} className="w-3 h-3 rounded-full" style={{ background: c }} />
            ))}
            <span className="ml-2 text-[11px] text-muted-foreground tracking-widest">AI INTERVIEWER</span>
          </div>
          <div className="p-5 flex flex-col gap-4">
            {[
              {
                who: "AI INTERVIEWER", color: "text-primary",
                bg: "bg-[#0d1f13]", border: "border-[#166534]",
                text: "Tell me about a time you had to make a technical decision under significant time pressure. What was your process?",
                align: "items-start",
                radius: "rounded-tr-2xl rounded-br-2xl rounded-bl-2xl",
              },
              {
                who: "CANDIDATE", color: "text-blue-400",
                bg: "bg-[#0d1527]", border: "border-[#1e3a5f]",
                text: "During our last product launch, our privacy decisions started showing latency spikes - a few hours before go live. I had to decide between rolling back the query optimisation or patching the cache pipeline...",
                align: "items-end",
                radius: "rounded-tl-2xl rounded-bl-2xl rounded-br-2xl",
              },
              {
                who: "AI INTERVIEWER", color: "text-primary",
                bg: "bg-[#0d1f13]", border: "border-[#166534]",
                text: "How did you weigh the risk of the hot-patch against the rollback timeline?",
                align: "items-start",
                radius: "rounded-tr-2xl rounded-br-2xl rounded-bl-2xl",
              },
            ].map((m, i) => (
              <div key={i} className={`flex flex-col gap-1 ${m.align}`}>
                <span className={`text-[10px] tracking-[0.1em] ${m.color}`}>{m.who}</span>
                <div className={`max-w-[85%] ${m.bg} border ${m.border} ${m.radius} px-3.5 py-2.5 text-[13px] text-gray-300 leading-relaxed font-serif`}>
                  {m.text}
                </div>
              </div>
            ))}
            {/* Typing indicator */}
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-primary tracking-[0.1em]">AI INTERVIEWER</span>
              <div className="flex gap-1">
                {[0, 1, 2].map(i => (
                  <div
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse-dot"
                    style={{ animationDelay: `${i * 0.2}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
 
      {/* ── Stats ── */}
      <section className="border-t border-b border-border py-12 px-10 grid grid-cols-2 md:grid-cols-4 max-w-[900px] mx-auto text-center">
        {[
          { val: 90, suffix: "%", label: "Reduction in time-to-screen" },
          { val: 3,  suffix: "x", label: "More candidates evaluated" },
          { val: 30, suffix: " min", label: "Average interview duration" },
          { val: 98, suffix: "%", label: "Candidate satisfaction" },
        ].map((s, i) => (
          <div key={i} className={`px-6 py-5 ${i < 3 ? "border-r border-border" : ""}`}>
            <div className="font-serif text-[40px] font-bold text-primary tracking-[-1px]">
              <Counter to={s.val} suffix={s.suffix} />
            </div>
            <div className="text-[12px] text-muted-foreground mt-1.5 leading-snug">{s.label}</div>
          </div>
        ))}
      </section>
 
      {/* ── Features ── */}
      <section className="max-w-[1080px] mx-auto px-10 py-24">
        <div className="text-center mb-14">
          <div className="text-[10px] tracking-[0.3em] uppercase text-primary mb-3.5">What TrueFit Does</div>
          <h2 className="font-serif text-[clamp(28px,4vw,44px)] font-bold tracking-tight text-foreground">
            The complete interview infrastructure
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <FeatureCard icon="🎙" title="Real-time Voice Interviews" body="AI conducts full spoken interviews over WebRTC. Natural conversation, no scripts - the agent adapts to each answer and asks intelligent follow-ups." />
          <FeatureCard icon="⚡" title="Instant Structured Evaluation" body="Every interview generates a structured scorecard: technical depth, communication clarity, culture signals - with verbatim evidence from the conversation." />
          <FeatureCard icon="🎯" title="Role-specific Intelligence" body="Configure interview depth, topics, and question weighting per job. A senior backend engineer interview is nothing like a product manager screen." />
          <FeatureCard icon="📊" title="Comparative Candidate Ranking" body="See every candidate scored on the same rubric, side by side. Remove unconscious bias from the top of your funnel." />
          <FeatureCard icon="🔄" title="Resume-aware Questioning" body="TrueFit reads candidate resumes and probes their actual experience - not generic questions. Every interview is personalised." />
          <FeatureCard icon="🛡" title="Candidate-grade Experience" body="Candidates get a fair, stress-reduced interview. No scheduling friction, no intimidating panels for a first screen." />
        </div>
      </section>
 
      {/* ── How it works ── */}
      <section className="border-t border-border max-w-[720px] mx-auto px-10 py-24">
        <div className="text-center mb-14">
          <div className="text-[10px] tracking-[0.3em] uppercase text-muted-foreground mb-3.5">For Hirers</div>
          <h2 className="font-serif text-[clamp(24px,4vw,40px)] font-bold tracking-tight text-foreground">
            From job post to shortlist in hours
          </h2>
        </div>
        <div className="flex flex-col gap-10">
          <Step n="01" title="Post a role and configure your interview" body="Define the skills, topics, and depth you need. Set duration, focus areas. TrueFit builds the interview brief." />
          <Step n="02" title="Candidates join via a link - no app required" body="Share a link. Each candidate accesses a unique interview session from any browser. No app, no scheduling friction." />
          <Step n="03" title="Receive scored evaluations instantly" body="The moment the interview ends, you get a structured scorecard with transcript citations and a hire/no-hire signal." />
          <Step n="04" title="Shortlist and schedule the right people" body="Use TrueFit's scoring to decide who moves forward. Spend your team interview time on actually deciding." />
        </div>
      </section>
 
      {/* ── Candidate section ── */}
      <section className="border-t border-border">
        <div className="max-w-[1080px] mx-auto px-10 py-24 grid md:grid-cols-2 gap-16 items-center">
          <div className="flex flex-col gap-6">
            <div>
              <div className="text-[10px] tracking-[0.3em] uppercase text-muted-foreground mb-3.5">For Candidates</div>
              <h2 className="font-serif text-[clamp(28px,4vw,44px)] font-bold tracking-tight text-foreground leading-tight">
                Practice until you're <span className="text-primary">genuinely ready</span>
              </h2>
            </div>
            <p className="text-[13px] text-muted-foreground leading-relaxed">
              TrueFit gives candidates simulated AI mock interviews in real job descriptions, detailed feedback on your answers, filler word analysis, and specific guidance on what to improve before the real thing.
            </p>
            <div className="flex flex-col gap-3">
              {[
                "Interviews based on actual job descriptions - not generic questions",
                "Detailed feedback on content, clarity, and confidence signals",
                "Track improvement across multiple sessions",
                "Get recommended to companies hiring for your profile",
              ].map(t => (
                <div key={t} className="flex gap-2.5 text-[13px] text-muted-foreground">
                  <span className="text-primary shrink-0">✓</span>
                  {t}
                </div>
              ))}
            </div>
          </div>
 
          {/* Score card mockup */}
          <div className="bg-card border border-border rounded-xl p-7 flex flex-col gap-4">
            <div className="text-[11px] tracking-[0.15em] uppercase text-muted-foreground/50">Post-interview feedback</div>
            {[
              { label: "Technical Depth",       score: 87, color: "#22c55e" },
              { label: "Communication Clarity", score: 72, color: "#60a5fa" },
              { label: "Problem Structuring",   score: 91, color: "#22c55e" },
              { label: "Culture Alignment",     score: 68, color: "#f59e0b" },
            ].map(m => (
              <div key={m.label} className="flex flex-col gap-1.5">
                <div className="flex justify-between text-[12px] text-muted-foreground">
                  <span>{m.label}</span>
                  <span className="font-bold" style={{ color: m.color }}>{m.score}</span>
                </div>
                <div className="h-1 bg-secondary rounded-sm">
                  <div
                    className="h-full rounded-sm transition-all duration-1000"
                    style={{ width: `${m.score}%`, background: m.color, boxShadow: `0 0 8px ${m.color}66` }}
                  />
                </div>
              </div>
            ))}
            <div className="mt-2 p-3.5 bg-primary/5 border border-primary/15 rounded-lg text-[12px] text-muted-foreground leading-relaxed font-serif italic">
              "Strong candidate. Demonstrates clear system design thinking and communicates trade-offs well. Recommend for technical round."
            </div>
          </div>
        </div>
      </section>
 
      {/* ── CTA / Waitlist ── */}
      <section className="border-t border-border py-24 px-6 text-center">
        <h2 className="font-serif text-[clamp(28px,5vw,56px)] font-bold tracking-tight text-foreground mb-4">
          Ready to hire better?
        </h2>
        <p className="text-[13px] text-muted-foreground mb-10 max-w-sm mx-auto leading-relaxed">
          Sixty companies already using TrueFit to screen smarter and make confident hiring decisions.
        </p>
        {submitted ? (
          <div className="inline-flex items-center gap-2 px-5 py-3 bg-primary/10 border border-primary/25 rounded text-[13px] text-primary">
            ✓ You're on the list
          </div>
        ) : (
          <div className="flex gap-0 max-w-sm mx-auto">
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="flex-1 px-4 py-3.5 bg-card border border-border rounded-l text-[13px] text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/40 transition-colors"
            />
            <button
              onClick={() => { if (email.includes("@")) setSubmitted(true) }}
              className="px-6 py-3.5 flex items-center gap-2 bg-primary text-primary-foreground text-[13px] font-bold tracking-wide rounded-r hover:brightness-110 transition-all whitespace-nowrap"
            >
              <>Join Waitlist</>
              <ChevronRight size={16} className="ml-1" />
            </button>
          </div>
        )}
      </section>
 
      {/* ── Footer ── */}
      <footer className="border-t border-border px-10 py-8 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <SpiralLogo size={20} />
          <span className="font-serif text-sm font-bold">
            True<span className="text-primary">Fit</span>.ai
          </span>
        </div>
        <div className="text-[12px] text-muted-foreground/50">© 2025 TrueFit.ai · All rights reserved</div>
        <div className="flex gap-5">
          {["Privacy", "Terms", "Contact"].map(l => (
            <a key={l} href="#" className="text-[12px] text-muted-foreground/50 hover:text-muted-foreground transition-colors no-underline">
              {l}
            </a>
          ))}
        </div>
      </footer>
    </div>
  )
}