import {cn} from "@/helpers/utils"

export function InfoRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex justify-between text-[11px]">
      <span className="text-indigo-500">{label}</span>
      <span className={cn("font-mono", accent ? "text-primary" : "text-[#6f7f9f]")}>{value}</span>
    </div>
  )
}