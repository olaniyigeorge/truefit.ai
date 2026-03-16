

export function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="flex gap-5 items-start">
      <div className="w-10 h-10 rounded-full shrink-0 border border-primary/25 flex items-center justify-center font-mono text-[13px] text-primary">
        {n}
      </div>
      <div>
        <div className="font-serif text-base font-bold text-foreground mb-1.5">{title}</div>
        <div className="text-[13px] text-muted-foreground leading-relaxed">{body}</div>
      </div>
    </div>
  )
}