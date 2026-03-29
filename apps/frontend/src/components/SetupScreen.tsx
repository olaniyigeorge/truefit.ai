import {Card, CardContent} from "@/components/ui/card"
import {Button} from "@/components/ui/button"


type SetupProps = {
  jobId: string; candidateId: string
  onStart: () => void; isConnecting: boolean
}
 
export function SetupScreen({ jobId, candidateId, onStart, isConnecting }: SetupProps) {
  const canStart = jobId.trim() && candidateId.trim() && !isConnecting
 
  return (
    <div className="relative w-full max-w-[480px] flex flex-col gap-8">
      {/* Header */}
      <div>
        <p className="text-[11px] tracking-[0.3em] text-primary uppercase mb-2">TrueFit · Interview System</p>
        <h1 className="font-serif text-[36px] font-extrabold text-foreground leading-[1.1] tracking-tight">
          Start Your<br />
          <span className="text-primary">Interview</span>
        </h1>
        <p className="mt-3 text-[13px] text-muted-foreground leading-relaxed">
          AI-powered voice interview. You'll need microphone access.
        </p>
      </div>
 
      {/* Form card */}
      <Card>
        <CardContent className="p-7 flex flex-col gap-5">
          <div className="rounded-lg border border-border bg-secondary/40 px-4 py-3">
            <p className="text-[12px] text-muted-foreground leading-relaxed">
              Your interview session is ready. When you start, we&apos;ll connect your microphone
              and begin the live AI conversation.
            </p>
          </div>
          <Button
            onClick={onStart}
            disabled={!canStart}
            className="mt-1 w-full font-bold font-mono tracking-[0.1em] uppercase"
          >
            {isConnecting ? "Connecting…" : "▶  Begin Interview"}
          </Button>
        </CardContent>
      </Card>
 
      <p className="text-[11px] text-muted-foreground/50 text-center leading-relaxed">
        By starting, you grant microphone access for the duration of this session.
        Audio is processed in real-time and not stored beyond transcript generation.
      </p>
    </div>
  )
}
