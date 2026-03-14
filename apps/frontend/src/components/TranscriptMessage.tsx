
import {cn} from "@/helpers/utils"
import type { TranscriptEntry } from "@/hooks/useInterviewSession"
import { Separator } from "@/components/ui/separator"


 
export function Message({ entry }: { entry: TranscriptEntry }) {
  const isAgent  = entry.speaker === "agent"
  const isSystem = entry.speaker === "system"
 
  if (isSystem) {
    return (
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground/50 tracking-widest">
        <Separator className="flex-1" />
        {entry.text}
        <Separator className="flex-1" />
      </div>
    )
  }
 
  return (
    <div className={cn("flex flex-col gap-1", isAgent ? "items-start" : "items-end")}>
      <span className={cn("text-[10px] tracking-widest", isAgent ? "text-primary" : "text-blue-400")}>
        {isAgent ? "AI Interviewer" : "You"} · {entry.timestamp.toLocaleTimeString("en-US", { hour12: false })}
      </span>
      <div
        className={cn(
          "max-w-[80%] px-3.5 py-2.5 text-sm leading-relaxed font-serif border",
          isAgent
            ? "bg-[#0d1f13] border-[#166534] text-[#dcfce7] rounded-tr-2xl rounded-br-2xl rounded-bl-2xl"
            : "bg-[#0d1527] border-[#1e3a5f] text-[#dbeafe] rounded-tl-2xl rounded-bl-2xl rounded-br-2xl"
        )}
      >
        {entry.text}
      </div>
    </div>
  )
}