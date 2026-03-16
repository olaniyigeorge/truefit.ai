

export function FeatureCard({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <div className="bg-card border border-border rounded-xl p-7 flex flex-col gap-3.5 cursor-default transition-all duration-200 hover:border-primary/25 hover:-translate-y-0.5">
      <div className="text-3xl">{icon}</div>
      <div className="font-serif text-[17px] font-bold text-foreground leading-snug">{title}</div>
      <div className="text-[13px] text-muted-foreground leading-relaxed">{body}</div>
    </div>
  )
}