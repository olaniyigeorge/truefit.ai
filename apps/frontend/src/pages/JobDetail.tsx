import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router"
import { jobsApi, type Job} from "@/helpers/api/jobs.api"
import {type Application } from "@/helpers/api/applications.api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
// import { Separator } from "@/components/ui/separator"
import {
    ArrowLeft, Play, Pause, X,
     Clock, Users, BookOpen, CheckCircle2,
    ChevronRight, AlertCircle,
} from "lucide-react"
import { applicationsApi as appApi } from "@/helpers/api/applications.api"
import {StatusBadgeComp, AppStatusBadge} from "@/components/Badges"

// ── Helpers ─────





function InfoRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex justify-between items-center py-2.5 border-b border-border last:border-0">
            <span className="text-[12px] text-muted-foreground">{label}</span>
            <span className="text-[12px] font-mono text-foreground capitalize">{value}</span>
        </div>
    )
}

// ── Page 

export default function JobDetailPage() {
    const { jobId } = useParams<{ jobId: string }>()
    const navigate = useNavigate()

    const [job, setJob] = useState<Job | null>(null)
    const [applications, setApplications] = useState<Application[]>([])
    const [loading, setLoading] = useState(true)
    const [acting, setActing] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!jobId) return
        const load = async () => {
            try {
                setLoading(true)
                const [jobData, appData] = await Promise.all([
                    jobsApi.getById(jobId),
                    appApi.list({ job_id: jobId, limit: 50 }).catch(() => []),
                ])
                setJob(jobData)
                setApplications(appData)
            } catch {
                setError("Failed to load job")
            } finally {
                setLoading(false)
            }
        }
        load()
    }, [jobId])

    const handleStatusChange = async (action: "activate" | "pause" | "close") => {
        if (!job) return
        setActing(true)
        try {
            let updated: Job
            if (action === "activate") updated = await jobsApi.activate(job.id)
            else if (action === "pause") updated = await jobsApi.pause(job.id)
            else updated = await jobsApi.close(job.id)
            setJob(updated)
        } catch {
            setError(`Failed to ${action} job`)
        } finally {
            setActing(false)
        }
    }

    if (loading) {
        return (
            <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
                <Skeleton className="h-8 w-48" />
                <div className="grid lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 space-y-4">
                        <Skeleton className="h-48 w-full" />
                        <Skeleton className="h-32 w-full" />
                    </div>
                    <Skeleton className="h-64 w-full" />
                </div>
            </main>
        )
    }

    if (error || !job) {
        return (
            <main className="flex-1 overflow-y-auto p-6 lg:p-8">
                <div className="flex items-center gap-2.5 p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {error ?? "Job not found"}
                </div>
            </main>
        )
    }

    const requiredSkills = job.skills.filter(s => s.required)
    const preferredSkills = job.skills.filter(s => !s.required)

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            {/* Back + header */}
            <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-4">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 mt-0.5 shrink-0"
                        onClick={() => navigate("/jobs")}
                    >
                        <ArrowLeft className="h-4 w-4" />
                    </Button>
                    <div>
                        <div className="flex items-center gap-2.5 mb-1.5">
                            <StatusBadgeComp status={job.status} />
                            <span className="text-[11px] text-muted-foreground font-mono capitalize">
                                {job.requirements.experience_level}
                            </span>
                        </div>
                        <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">
                            {job.title}
                        </h1>
                    </div>
                </div>

                {/* Status actions */}
                <div className="flex items-center gap-2 shrink-0">
                    {job.status === "draft" && (
                        <Button
                            size="sm"
                            className="font-mono text-[12px]"
                            disabled={acting}
                            onClick={() => handleStatusChange("activate")}
                        >
                            <Play className="h-3.5 w-3.5 mr-1.5" /> Activate
                        </Button>
                    )}
                    {job.status === "active" && (
                        <>
                            <Button
                                variant="outline"
                                size="sm"
                                className="font-mono text-[12px]"
                                disabled={acting}
                                onClick={() => handleStatusChange("pause")}
                            >
                                <Pause className="h-3.5 w-3.5 mr-1.5" /> Pause
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                className="font-mono text-[12px] text-muted-foreground"
                                disabled={acting}
                                onClick={() => handleStatusChange("close")}
                            >
                                <X className="h-3.5 w-3.5 mr-1.5" /> Close
                            </Button>
                        </>
                    )}
                    {job.status === "paused" && (
                        <>
                            <Button
                                size="sm"
                                className="font-mono text-[12px]"
                                disabled={acting}
                                onClick={() => handleStatusChange("activate")}
                            >
                                <Play className="h-3.5 w-3.5 mr-1.5" /> Reactivate
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                className="font-mono text-[12px] text-muted-foreground"
                                disabled={acting}
                                onClick={() => handleStatusChange("close")}
                            >
                                <X className="h-3.5 w-3.5 mr-1.5" /> Close
                            </Button>
                        </>
                    )}
                </div>
            </div>

            {error && (
                <div className="p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    {error}
                </div>
            )}

            {/* Main layout */}
            <div className="grid lg:grid-cols-3 gap-6">
                {/* Left column — content */}
                <div className="lg:col-span-2 space-y-5">
                    {/* Description */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="font-serif text-base font-bold flex items-center gap-2">
                                <BookOpen className="h-4 w-4 text-muted-foreground" /> Description
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <p className="text-[13px] text-muted-foreground leading-relaxed whitespace-pre-wrap">
                                {job.description}
                            </p>
                        </CardContent>
                    </Card>

                    {/* Skills */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="font-serif text-base font-bold flex items-center gap-2">
                                <CheckCircle2 className="h-4 w-4 text-muted-foreground" /> Skills
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            {requiredSkills.length > 0 && (
                                <div>
                                    <p className="text-[10px] tracking-[0.15em] uppercase text-muted-foreground mb-2.5">Required</p>
                                    <div className="flex flex-wrap gap-2">
                                        {requiredSkills.map(s => (
                                            <div key={s.name} className="flex items-center gap-1.5 px-2.5 py-1 bg-primary/5 border border-primary/15 rounded-sm">
                                                <span className="text-[12px] font-mono text-foreground">{s.name}</span>
                                                {s.min_years && (
                                                    <span className="text-[10px] text-muted-foreground">{s.min_years}y+</span>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {preferredSkills.length > 0 && (
                                <div>
                                    <p className="text-[10px] tracking-[0.15em] uppercase text-muted-foreground mb-2.5">Preferred</p>
                                    <div className="flex flex-wrap gap-2">
                                        {preferredSkills.map(s => (
                                            <div key={s.name} className="flex items-center gap-1.5 px-2.5 py-1 bg-secondary border border-border rounded-sm">
                                                <span className="text-[12px] font-mono text-muted-foreground">{s.name}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    {/* Applications */}
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between pb-3">
                            <CardTitle className="font-serif text-base font-bold flex items-center gap-2">
                                <Users className="h-4 w-4 text-muted-foreground" />
                                Applications
                                <span className="text-[12px] font-mono text-muted-foreground ml-1">
                                    ({applications.length})
                                </span>
                            </CardTitle>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="text-[12px] text-muted-foreground font-mono gap-1"
                                onClick={() => navigate("/applications")}
                            >
                                View all <ChevronRight className="h-3 w-3" />
                            </Button>
                        </CardHeader>
                        <CardContent>
                            {applications.length === 0 ? (
                                <p className="text-[13px] text-muted-foreground text-center py-6">
                                    No applications yet
                                </p>
                            ) : (
                                <div className="space-y-1">
                                    {applications.slice(0, 5).map(app => (
                                        <div
                                            key={app.id}
                                            className="flex items-center justify-between p-3 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                                            onClick={() => navigate("/applications")}
                                        >
                                            <span className="text-[12px] font-mono text-muted-foreground">
                                                {app.candidate_id.slice(0, 8)}…
                                            </span>
                                            <AppStatusBadge status={app.status} />
                                        </div>
                                    ))}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </div>

                {/* Right column — metadata */}
                <div className="space-y-5">
                    {/* Job details */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="font-serif text-base font-bold">Details</CardTitle>
                        </CardHeader>
                        <CardContent className="px-6 pb-6 pt-0">
                            <InfoRow label="Experience"     value={job.requirements.experience_level} />
                            <InfoRow label="Arrangement"    value={job.requirements.work_arrangement ?? "—"} />
                            <InfoRow label="Location"       value={job.requirements.location ?? "—"} />
                            {job.requirements.min_total_years && (
                                <InfoRow label="Min. Years"  value={`${job.requirements.min_total_years}+ years`} />
                            )}
                            {job.requirements.education && (
                                <InfoRow label="Education"   value={job.requirements.education} />
                            )}
                            <InfoRow label="Created"        value={new Date(job.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} />
                        </CardContent>
                    </Card>

                    {/* Interview config */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="font-serif text-base font-bold flex items-center gap-2">
                                <Clock className="h-4 w-4 text-muted-foreground" /> Interview Setup
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="px-6 pb-6 pt-0">
                            <InfoRow label="Questions"  value={`${job.interview_config.max_questions} max`} />
                            <InfoRow label="Duration"   value={`${job.interview_config.max_duration_minutes} min`} />
                            {job.interview_config.topics.length > 0 && (
                                <div className="pt-3">
                                    <p className="text-[10px] tracking-[0.15em] uppercase text-muted-foreground mb-2">Topics</p>
                                    <div className="flex flex-wrap gap-1.5">
                                        {job.interview_config.topics.map(t => (
                                            <span key={t} className="px-2 py-0.5 bg-secondary text-muted-foreground text-[11px] font-mono rounded-sm border border-border capitalize">
                                                {t}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {job.interview_config.custom_instructions && (
                                <div className="pt-3 mt-1 border-t border-border">
                                    <p className="text-[10px] tracking-[0.15em] uppercase text-muted-foreground mb-2">Custom Instructions</p>
                                    <p className="text-[12px] text-muted-foreground leading-relaxed">
                                        {job.interview_config.custom_instructions}
                                    </p>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </div>
            </div>
        </main>
    )
}