import type{Application} from "@/helpers/api/applications.api"
import type{Job} from "@/helpers/api/jobs.api"



export function statusBadge(status: Application["status"]) {
    const map: Record<Application["status"], { label: string; className: string }> = {
        new:          { label: "New",          className: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
        interviewing: { label: "Interviewing", className: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
        shortlisted:  { label: "Shortlisted",  className: "bg-primary/10 text-primary border-primary/20" },
        rejected:     { label: "Rejected",     className: "bg-destructive/10 text-destructive border-destructive/20" },
        hired:        { label: "Hired",        className: "bg-primary/20 text-primary border-primary/30" },
    }
    const { label, className } = map[status] ?? { label: status, className: "" }
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[10px] font-mono tracking-wide border ${className}`}>
            {label}
        </span>
    )
}
 
export function jobStatusBadge(status: Job["status"]) {
    const map: Record<Job["status"], { label: string; className: string }> = {
        draft:  { label: "Draft",  className: "bg-muted text-muted-foreground border-border" },
        active: { label: "Active", className: "bg-primary/10 text-primary border-primary/20" },
        paused: { label: "Paused", className: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
        closed: { label: "Closed", className: "bg-muted/50 text-muted-foreground/50 border-border/50" },
    }
    const { label, className } = map[status] ?? { label: status, className: "" }
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[10px] font-mono tracking-wide border ${className}`}>
            {label}
        </span>
    )
}