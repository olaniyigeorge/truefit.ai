import {useState, useEffect} from "react"
import {useNavigate} from "react-router"
import {type JobStatus, jobsApi, type Job} from "@/helpers/api/jobs.api"
import {useAuthContext} from "@/hooks/useAuthContext"
import {Briefcase, Plus, Search} from "lucide-react"
import {Input} from "@/components/ui/input"
import {Skeleton} from "@/components/ui/skeleton"
import {Card,CardContent} from "@/components/ui/card"
import {Button} from "@/components/ui/button"
import { JobCard } from "@/components/JobCard";



const STATUS_FILTERS: { label: string; value: JobStatus | "all" }[] = [
    { label: "All",    value: "all" },
    { label: "Active", value: "active" },
    { label: "Draft",  value: "draft" },
    { label: "Paused", value: "paused" },
    { label: "Closed", value: "closed" },
]


function EmptyState({ filtered, onCreate }: { filtered: boolean; onCreate: () => void }) {
    return (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="p-4 rounded-full bg-secondary">
                <Briefcase className="h-8 w-8 text-muted-foreground" />
            </div>
            <div className="text-center">
                <p className="font-serif text-lg font-bold text-foreground mb-1">
                    {filtered ? "No jobs match your filters" : "No jobs yet"}
                </p>
                <p className="text-[13px] text-muted-foreground">
                    {filtered ? "Try adjusting your search or filter" : "Post your first job to start screening candidates"}
                </p>
            </div>
            {!filtered && (
                <Button onClick={onCreate} className="font-mono text-[12px] tracking-wide mt-2">
                    <Plus className="h-4 w-4 mr-2" /> Post a Job
                </Button>
            )}
        </div>
    )
}


export default function JobsPage() {
    const { backendUser } = useAuthContext()
    const navigate = useNavigate()
 
    const [jobs, setJobs] = useState<Job[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [search, setSearch] = useState("")
    const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all")
    const [acting, setActing] = useState<string | null>(null)
 
    useEffect(() => {
        if (!backendUser?.org_id) return
        const load = async () => {
            try {
                setLoading(true)
                const data = await jobsApi.list({ org_id: backendUser.org_id!, limit: 100 })
                setJobs(data)
            } catch {
                setError("Failed to load jobs")
            } finally {
                setLoading(false)
            }
        }
        load()
    }, [backendUser])
 
    const handleStatusChange = async (job: Job, action: "activate" | "pause" | "close") => {
        setActing(job.id)
        try {
            let updated: Job
            if (action === "activate") updated = await jobsApi.activate(job.id)
            else if (action === "pause") updated = await jobsApi.pause(job.id)
            else updated = await jobsApi.close(job.id)
            setJobs(prev => prev.map(j => j.id === updated.id ? updated : j))
        } catch {
            setError(`Failed to ${action} job`)
        } finally {
            setActing(null)
        }
    }
 
    const handleDelete = async (jobId: string) => {
        setActing(jobId)
        try {
            await jobsApi.delete(jobId)
            setJobs(prev => prev.filter(j => j.id !== jobId))
        } catch {
            setError("Failed to delete job")
        } finally {
            setActing(null)
        }
    }
 
    const filtered = jobs.filter(j => {
        const matchesSearch = j.title.toLowerCase().includes(search.toLowerCase()) ||
            j.description.toLowerCase().includes(search.toLowerCase())
        const matchesStatus = statusFilter === "all" || j.status === statusFilter
        return matchesSearch && matchesStatus
    })
 
    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">Recruiter</p>
                    <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">Jobs</h1>
                </div>
                <Button
                    onClick={() => navigate("/jobs/new")}
                    className="font-mono text-[12px] tracking-wide"
                >
                    <Plus className="h-4 w-4 mr-2" /> Post a Job
                </Button>
            </div>
 
            {/* Error */}
            {error && (
                <div className="p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    {error}
                </div>
            )}
 
            {/* Filters */}
            <div className="flex flex-col sm:flex-row gap-3">
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="Search jobs…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        className="pl-9 bg-background"
                    />
                </div>
                <div className="flex gap-1.5">
                    {STATUS_FILTERS.map(f => (
                        <button
                            key={f.value}
                            onClick={() => setStatusFilter(f.value)}
                            className={`px-3 py-1.5 rounded text-[12px] font-mono transition-colors ${
                                statusFilter === f.value
                                    ? "bg-primary text-primary-foreground"
                                    : "bg-secondary text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
            </div>
 
            {/* Count */}
            {!loading && (
                <p className="text-[12px] text-muted-foreground font-mono">
                    {filtered.length} {filtered.length === 1 ? "job" : "jobs"}
                    {statusFilter !== "all" ? ` · ${statusFilter}` : ""}
                </p>
            )}
 
            {/* Grid */}
            {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {[...Array(6)].map((_, i) => (
                        <Card key={i}><CardContent className="p-6"><Skeleton className="h-44 w-full" /></CardContent></Card>
                    ))}
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState
                    filtered={search !== "" || statusFilter !== "all"}
                    onCreate={() => navigate("/jobs/new")}
                />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {filtered.map(job => (
                        <div key={job.id} className={acting === job.id ? "opacity-50 pointer-events-none" : ""}>
                            <JobCard
                                job={job}
                                onView={() => navigate(`/jobs/${job.id}`)}
                                onStatusChange={action => handleStatusChange(job, action)}
                                onDelete={() => handleDelete(job.id)}
                            />
                        </div>
                    ))}
                </div>
            )}
        </main>
    )
}