import { type Application, type ApplicationStatus } from "@/helpers/api/applications.api"
import { Clock } from "lucide-react"
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "./ui/dropdown-menu"
import { Button } from "./ui/button"
import { MoreHorizontal } from "lucide-react"
import { AppStatusBadge } from "./Badges"
import { useNavigate } from "react-router"
import { Mic } from "lucide-react"


const RECRUITER_ACTIONS: Partial<Record<ApplicationStatus, ApplicationStatus[]>> = {
    new: ["interviewing", "shortlisted", "rejected"],
    interviewing: ["shortlisted", "rejected"],
    shortlisted: ["hired", "rejected"],
}


export function ApplicationRow({
    app, isRecruiter, acting, onStatusChange, onWithdraw, candidateProfileId
}: {
    app: Application
    isRecruiter: boolean
    acting: boolean
    candidateProfileId?: string
    onStatusChange: (status: ApplicationStatus) => void
    onWithdraw: () => void
}) {
    const navigate = useNavigate()
    const actions = isRecruiter ? RECRUITER_ACTIONS[app.status] ?? [] : []

    const canStartInterview = !isRecruiter && app.status === "interviewing" && candidateProfileId

    console.log(canStartInterview)
    return (
        <div className={`flex items-center justify-between p-4 rounded-lg border border-border bg-card hover:bg-secondary/50 transition-colors ${acting ? "opacity-50 pointer-events-none" : ""}`}>
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2.5 mb-1">
                    <AppStatusBadge status={app.status} />
                    <span className="text-[10px] text-muted-foreground font-mono capitalize">{app.source}</span>
                </div>
                <p className="text-[13px] font-mono text-foreground">
                    Job: <span className="text-muted-foreground">{app.job_id.slice(0, 8)}…</span>
                </p>
                {isRecruiter && (
                    <p className="text-[12px] text-muted-foreground mt-0.5">
                        Candidate: {app.candidate_id.slice(0, 8)}…
                    </p>
                )}
            </div>

            <div className="flex items-center gap-3 shrink-0">
                {/* Candidate: Start Interview button */}
                {/* TODO: Remove check after test and switch "itv" for "interview" in link -  {canStartInterview && ( */}
                    <Button
                        size="sm"
                        className="font-mono text-[11px] gap-1.5 bg-primary text-primary-foreground"
                        onClick={() =>
                            navigate(`/itv/${app.job_id}/${candidateProfileId}`)
                        }
                    >
                        <Mic className="h-3.5 w-3.5" />
                        Start Interview
                    </Button>
                {/* )} */}

                <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(app.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                </span>

                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-7 w-7">
                            <MoreHorizontal className="h-4 w-4" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-44">
                        {actions.map(s => (
                            <DropdownMenuItem key={s} onClick={() => onStatusChange(s)}>
                                Move to <span className="ml-1 capitalize">{s}</span>
                            </DropdownMenuItem>
                        ))}
                        {!isRecruiter && app.status === "new" && (
                            <DropdownMenuItem
                                className="text-destructive focus:text-destructive"
                                onClick={onWithdraw}
                            >
                                Withdraw
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    )
}