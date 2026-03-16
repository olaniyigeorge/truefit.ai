import {useState, useEffect} from "react"
import {useAuthContext} from "@/hooks/useAuthContext"
import { useNavigate } from "react-router"
import {jobsApi , type Job} from "@/helpers/api/jobs.api"
import {applicationsApi, type Application} from "@/helpers/api/applications.api"
import {StatCard} from "@/components/StatCard"
import {StatusBadge, JobStatusBadge} from "@/components/Badges"
import {Skeleton} from "@/components/ui/skeleton"
import {Card, CardContent, CardHeader, CardTitle} from "@/components/ui/card"
import {Button} from "@/components/ui/button"
import { Briefcase, Users, FileText, Mic, ArrowRight, Clock, CheckCircle2, XCircle, AlertCircle } from "lucide-react"


type DashboardData = {
    activeJobs: Job[]
    recentApplications: Application[]
    totalCandidates: number
    totalInterviews: number
}


function formatDate(iso: string) {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

function EmptyState({ message }: { message: string }) {
    return (
        <div className="flex flex-col items-center justify-center py-12 gap-2">
            <div className="text-3xl opacity-20">◎</div>
            <p className="text-[13px] text-muted-foreground">{message}</p>
        </div>
    )
}



const Dashboard = () => {
    const { backendUser } = useAuthContext()
    const navigate = useNavigate()
 
    const [data, setData] = useState<DashboardData | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
 
    const isRecruiter = backendUser?.role === "recruiter" || backendUser?.role === "admin"
 
    useEffect(() => {
        if (!backendUser) return
 
        const load = async () => {
            try {
                setLoading(true)
 
                if (isRecruiter && backendUser.org_id) {
                    const [jobs, applications] = await Promise.all([
                        jobsApi.list({ org_id: backendUser.org_id, limit: 100 }),
                        applicationsApi.list({ job_id: undefined, candidate_id: undefined, limit: 20 }),
                    ])
 
                    setData({
                        activeJobs: jobs.filter(j => j.status === "active").slice(0, 5),
                        recentApplications: applications.slice(0, 8),
                        totalCandidates: 0,
                        totalInterviews: 0,
                    })
                } else {
                    // Candidate view
                    const applications = await applicationsApi.list({
                        candidate_id: backendUser.id,
                        limit: 20,
                    })
                    setData({
                        activeJobs: [],
                        recentApplications: applications.slice(0, 8),
                        totalCandidates: 0,
                        totalInterviews: applications.filter(a => a.status === "interviewing").length,
                    })
                }
            } catch (e: any) {
                setError("Failed to load dashboard data")
            } finally {
                setLoading(false)
            }
        }
 
        load()
    }, [backendUser])
 
    const greeting = () => {
        const hour = new Date().getHours()
        if (hour < 12) return "Good morning"
        if (hour < 17) return "Good afternoon"
        return "Good evening"
    }
 
    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-8">
            {/* Header */}
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">
                        {isRecruiter ? "Recruiter Dashboard" : "Candidate Dashboard"}
                    </p>
                    <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">
                        {greeting()}{backendUser?.display_name ? `, ${backendUser.display_name.split(" ")[0]}` : ""}
                    </h1>
                </div>
                {isRecruiter && (
                    <Button
                        onClick={() => navigate("/jobs")}
                        className="font-mono text-[12px] tracking-wide"
                    >
                        Post a Job →
                    </Button>
                )}
            </div>
 
            {error && (
                <div className="flex items-center gap-2.5 p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {error}
                </div>
            )}
 
            {/* Stats */}
            {loading ? (
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {[...Array(4)].map((_, i) => (
                        <Card key={i}><CardContent className="p-6"><Skeleton className="h-20 w-full" /></CardContent></Card>
                    ))}
                </div>
            ) : isRecruiter ? (
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <StatCard
                        icon={Briefcase}
                        label="Active Jobs"
                        value={data?.activeJobs.length ?? 0}
                        sub="Open positions"
                        accent
                    />
                    <StatCard
                        icon={FileText}
                        label="Applications"
                        value={data?.recentApplications.length ?? 0}
                        sub="Total received"
                    />
                    <StatCard
                        icon={Users}
                        label="Shortlisted"
                        value={data?.recentApplications.filter(a => a.status === "shortlisted").length ?? 0}
                        sub="Ready to advance"
                    />
                    <StatCard
                        icon={Mic}
                        label="Interviewing"
                        value={data?.recentApplications.filter(a => a.status === "interviewing").length ?? 0}
                        sub="In progress"
                    />
                </div>
            ) : (
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <StatCard icon={FileText}  label="Applications"  value={data?.recentApplications.length ?? 0} sub="Total submitted" accent />
                    <StatCard icon={Mic}       label="Interviews"    value={data?.totalInterviews ?? 0}           sub="In progress" />
                    <StatCard icon={CheckCircle2} label="Shortlisted" value={data?.recentApplications.filter(a => a.status === "shortlisted").length ?? 0} sub="Moving forward" />
                    <StatCard icon={XCircle}   label="Closed"       value={data?.recentApplications.filter(a => a.status === "rejected" || a.status === "hired").length ?? 0} sub="Completed" />
                </div>
            )}
 
            {/* Main grid */}
            <div className="grid lg:grid-cols-2 gap-6">
 
                {/* Recent applications */}
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between pb-4">
                        <CardTitle className="font-serif text-base font-bold">Recent Applications</CardTitle>
                        <Button
                            variant="ghost"
                            size="sm"
                            className="text-[12px] text-muted-foreground font-mono gap-1"
                            onClick={() => navigate("/applications")}
                        >
                            View all <ArrowRight className="h-3 w-3" />
                        </Button>
                    </CardHeader>
                    <CardContent className="pt-0">
                        {loading ? (
                            <div className="space-y-3">
                                {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
                            </div>
                        ) : !data?.recentApplications.length ? (
                            <EmptyState message="No applications yet" />
                        ) : (
                            <div className="space-y-1">
                                {data.recentApplications.map(app => (
                                    <div
                                        key={app.id}
                                        className="flex items-center justify-between p-3 rounded-lg hover:bg-secondary cursor-pointer transition-colors group"
                                        onClick={() => navigate(`/applications`)}
                                    >
                                        <div className="min-w-0">
                                            <p className="text-[12px] font-mono text-foreground truncate">
                                                {app.job_id.slice(0, 8)}…
                                            </p>
                                            <p className="text-[11px] text-muted-foreground flex items-center gap-1 mt-0.5">
                                                <Clock className="h-3 w-3" />
                                                {formatDate(app.created_at)}
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-2 shrink-0">
                                            {StatusBadge(app.status)}
                                            <ArrowRight className="h-3 w-3 text-muted-foreground/0 group-hover:text-muted-foreground/50 transition-colors" />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </CardContent>
                </Card>
 
                {/* Active jobs (recruiter) or Interview history (candidate) */}
                {isRecruiter ? (
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between pb-4">
                            <CardTitle className="font-serif text-base font-bold">Active Jobs</CardTitle>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="text-[12px] text-muted-foreground font-mono gap-1"
                                onClick={() => navigate("/jobs")}
                            >
                                View all <ArrowRight className="h-3 w-3" />
                            </Button>
                        </CardHeader>
                        <CardContent className="pt-0">
                            {loading ? (
                                <div className="space-y-3">
                                    {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
                                </div>
                            ) : !data?.activeJobs.length ? (
                                <EmptyState message="No active jobs — post one to get started" />
                            ) : (
                                <div className="space-y-1">
                                    {data.activeJobs.map(job => (
                                        <div
                                            key={job.id}
                                            className="flex items-center justify-between p-3 rounded-lg hover:bg-secondary cursor-pointer transition-colors group"
                                            onClick={() => navigate(`/jobs/${job.id}`)}
                                        >
                                            <div className="min-w-0">
                                                <p className="text-[13px] font-medium text-foreground truncate">
                                                    {job.title}
                                                </p>
                                                <p className="text-[11px] text-muted-foreground mt-0.5 capitalize">
                                                    {job.requirements.experience_level} · {job.requirements.work_arrangement ?? "—"}
                                                </p>
                                            </div>
                                            <div className="flex items-center gap-2 shrink-0">
                                                {JobStatusBadge(job.status)}
                                                <ArrowRight className="h-3 w-3 text-muted-foreground/0 group-hover:text-muted-foreground/50 transition-colors" />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                ) : (
                    <Card>
                        <CardHeader className="pb-4">
                            <CardTitle className="font-serif text-base font-bold">Application Status</CardTitle>
                        </CardHeader>
                        <CardContent className="pt-0">
                            {loading ? (
                                <div className="space-y-3">
                                    {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
                                </div>
                            ) : !data?.recentApplications.length ? (
                                <EmptyState message="No applications submitted yet" />
                            ) : (
                                <div className="space-y-3">
                                    {(["new", "interviewing", "shortlisted", "rejected", "hired"] as Application["status"][]).map(s => {
                                        const count = data.recentApplications.filter(a => a.status === s).length
                                        if (!count) return null
                                        return (
                                            <div key={s} className="flex items-center justify-between">
                                                {StatusBadge(s)}
                                                <span className="font-serif text-lg font-bold text-foreground">{count}</span>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                )}
            </div>
        </main>
    )
}

export default Dashboard