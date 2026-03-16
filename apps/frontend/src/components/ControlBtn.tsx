import { Button } from "./ui/button";


export function ControlBtn({
  onClick, label, disabled, variant = "ghost", active,
}: {
  onClick: () => void; label: string; disabled?: boolean
  variant?: "ghost" | "danger"; active?: boolean
}) {
  return (
    <Button
      onClick={onClick}
      disabled={disabled}
      variant={variant === "danger" ? "destructive" : active ? "secondary" : "outline"}
      size="sm"
      className="w-full justify-start font-mono text-[12px]"
    >
      {label}
    </Button>
  )
}