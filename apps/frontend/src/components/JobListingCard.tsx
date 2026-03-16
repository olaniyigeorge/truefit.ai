
import {type Job} from "@/helpers/api/jobs.api"
import {type Org} from "@/helpers/api/orgs.api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {Card, CardContent} from "@/components/ui/card"
import { Briefcase, CheckCircle2, MapPin, Users, Clock } from "lucide-react"


export function JobListingCard({
    job,
    org,
    applied,
    applying,
    onApply,
}: {
    job: Job
    org: Org | null
    applied: boolean
    applying: boolean
    onApply: () => void
}) {
    const requiredSkills = job.skills.filter(s => s.required).slice(0, 5)
    const extraSkills = job.skills.filter(s => s.required).length - 5

    return (
        <Card className="hover:border-border/80 transition-all duration-200">
            <CardContent className="p-6 flex flex-col gap-4">
                {/* Header */}
                <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                            <span className="text-[11px] font-mono text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-sm capitalize">
                                {job.requirements.experience_level}
                            </span>
                            {job.requirements.work_arrangement && (
                                <span className="text-[11px] font-mono text-muted-foreground bg-secondary border border-border px-2 py-0.5 rounded-sm capitalize">
                                    {job.requirements.work_arrangement}
                                </span>
                            )}
                        </div>
                        <h3 className="font-serif text-lg font-bold text-foreground leading-snug">
                            {job.title}
                        </h3>
                        {org && (
                            <p className="text-[13px] text-muted-foreground mt-0.5 flex items-center gap-1.5">
                                <Briefcase className="h-3.5 w-3.5" />
                                {org.name}
                            </p>
                        )}
                    </div>

                    {applied ? (
                        <div className="flex items-center gap-1.5 text-primary text-[12px] font-mono shrink-0">
                            <CheckCircle2 className="h-4 w-4" />
                            Applied
                        </div>
                    ) : (
                        <Button
                            size="sm"
                            disabled={applying}
                            onClick={onApply}
                            className="font-mono text-[12px] shrink-0"
                        >
                            {applying ? "Applying…" : "Apply"}
                        </Button>
                    )}
                </div>

                {/* Description */}
                <p className="text-[13px] text-muted-foreground leading-relaxed line-clamp-3">
                    {job.description}
                </p>

                {/* Meta */}
                <div className="flex flex-wrap gap-4 text-[11px] text-muted-foreground">
                    {job.requirements.location && (
                        <span className="flex items-center gap-1.5">
                            <MapPin className="h-3 w-3" />
                            {job.requirements.location}
                        </span>
                    )}
                    {job.requirements.min_total_years && (
                        <span className="flex items-center gap-1.5">
                            <Users className="h-3 w-3" />
                            {job.requirements.min_total_years}+ years
                        </span>
                    )}
                    <span className="flex items-center gap-1.5">
                        <Clock className="h-3 w-3" />
                        {job.interview_config.max_duration_minutes}min interview
                    </span>
                </div>

                {/* Skills */}
                {requiredSkills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                        {requiredSkills.map(s => (
                            <Badge key={s.name} variant="secondary" className="font-mono text-[10px] px-2 py-0.5">
                                {s.name}
                            </Badge>
                        ))}
                        {extraSkills > 0 && (
                            <span className="text-[11px] text-muted-foreground/50 font-mono self-center">
                                +{extraSkills} more
                            </span>
                        )}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}