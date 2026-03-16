import {Label} from "@/components/ui/label"
import {Input} from "@/components/ui/input"

export function Field({
  id, label, value, onChange, placeholder, hint,
}: {
  id: string; label: string; value: string; onChange: (v: string) => void
  placeholder: string; hint: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-[10px] tracking-[0.15em] uppercase text-muted-foreground">
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        className="bg-background font-mono text-[12px]"
      />
      <p className="text-[11px] text-muted-foreground/50">{hint}</p>
    </div>
  )
}