import { type Job } from "@/helpers/api/jobs.api"
import {Card, CardContent} from "@/components/ui/card"
import { DropdownMenu, DropdownMenuItem, DropdownMenuContent, DropdownMenuTrigger, DropdownMenuSeparator } from "@/components/ui/dropdown-menu"
import {Button} from "@/components/ui/button"
import {Trash2, MoreHorizontal, Pause, Play, ChevronRight, Clock, Users, MapPin, X} from "lucide-react"
import { StatusBadgeComp } from "./Badges"




export function JobCard({
    job,
    onView,
    onStatusChange,
    onDelete,
}: {
    job: Job
    onView: () => void
    onStatusChange: (action: "activate" | "pause" | "close") => void
    onDelete: () => void
}) {
    const requiredSkills = job.skills.filter(s => s.required).slice(0, 4)
    const extraSkills = job.skills.filter(s => s.required).length - 4
 
    return (
        <Card className="group hover:border-border/80 transition-all duration-200 cursor-pointer" onClick={onView}>
            <CardContent className="p-6 flex flex-col gap-4">
                {/* Header */}
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1.5">
                            <StatusBadgeComp status={job.status} />
                            <span className="text-[10px] text-muted-foreground font-mono capitalize">
                                {job.requirements.experience_level}
                            </span>
                        </div>
                        <h3 className="font-serif text-[17px] font-bold text-foreground leading-snug group-hover:text-primary transition-colors truncate">
                            {job.title}
                        </h3>
                    </div>
 
                    {/* Actions menu - stop propagation so click doesn't navigate */}
                    <div onClick={e => e.stopPropagation()}>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <MoreHorizontal className="h-4 w-4" />
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-44">
                                {job.status === "draft" && (
                                    <DropdownMenuItem onClick={() => onStatusChange("activate")}>
                                        <Play className="h-3.5 w-3.5 mr-2 text-primary" /> Activate
                                    </DropdownMenuItem>
                                )}
                                {job.status === "active" && (
                                    <DropdownMenuItem onClick={() => onStatusChange("pause")}>
                                        <Pause className="h-3.5 w-3.5 mr-2 text-amber-400" /> Pause
                                    </DropdownMenuItem>
                                )}
                                {(job.status === "active" || job.status === "paused") && (
                                    <DropdownMenuItem onClick={() => onStatusChange("close")}>
                                        <X className="h-3.5 w-3.5 mr-2 text-muted-foreground" /> Close
                                    </DropdownMenuItem>
                                )}
                                {job.status === "draft" && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem
                                            onClick={onDelete}
                                            className="text-destructive focus:text-destructive"
                                        >
                                            <Trash2 className="h-3.5 w-3.5 mr-2" /> Delete
                                        </DropdownMenuItem>
                                    </>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </div>
 
                {/* Description */}
                <p className="text-[13px] text-muted-foreground leading-relaxed line-clamp-2">
                    {job.description}
                </p>
 
                {/* Meta */}
                <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
                    {job.requirements.location && (
                        <span className="flex items-center gap-1">
                            <MapPin className="h-3 w-3" />
                            {job.requirements.location}
                        </span>
                    )}
                    {job.requirements.work_arrangement && (
                        <span className="flex items-center gap-1 capitalize">
                            <Users className="h-3 w-3" />
                            {job.requirements.work_arrangement}
                        </span>
                    )}
                    <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {job.interview_config.max_duration_minutes}min interview
                    </span>
                </div>
 
                {/* Skills */}
                {requiredSkills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                        {requiredSkills.map(s => (
                            <span
                                key={s.name}
                                className="px-2 py-0.5 bg-secondary text-muted-foreground text-[11px] font-mono rounded-sm border border-border"
                            >
                                {s.name}
                            </span>
                        ))}
                        {extraSkills > 0 && (
                            <span className="px-2 py-0.5 text-muted-foreground/50 text-[11px] font-mono">
                                +{extraSkills} more
                            </span>
                        )}
                    </div>
                )}
 
                {/* Footer */}
                <div className="flex items-center justify-between pt-1 border-t border-border">
                    <span className="text-[11px] text-muted-foreground font-mono">
                        {new Date(job.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                    </span>
                    <span className="text-[11px] text-muted-foreground flex items-center gap-1 group-hover:text-primary transition-colors">
                        View detail <ChevronRight className="h-3 w-3" />
                    </span>
                </div>
            </CardContent>
        </Card>
    )
}