import { useEffect, useState } from "react"
import { useAuthContext } from "@/hooks/useAuthContext"
import { applicationsApi, type Application, type ApplicationStatus } from "@/helpers/api/applications.api"
import { Card, CardContent } from "@/components/ui/card"
import { ApplicationRow } from "@/components/ApplicationRow"
import { Skeleton } from "@/components/ui/skeleton"
import { FileText, AlertCircle} from "lucide-react"



const STATUS_FILTERS: { label: string; value: ApplicationStatus | "all" }[] = [
    { label: "All",          value: "all" },
    { label: "New",          value: "new" },
    { label: "Interviewing", value: "interviewing" },
    { label: "Shortlisted",  value: "shortlisted" },
    { label: "Rejected",     value: "rejected" },
    { label: "Hired",        value: "hired" },
]





function FilterTabs({
    active, onChange,
}: {
    active: ApplicationStatus | "all"
    onChange: (v: ApplicationStatus | "all") => void
}) {
    return (
        <div className="flex gap-1.5 flex-wrap">
            {STATUS_FILTERS.map(f => (
                <button
                    key={f.value}
                    onClick={() => onChange(f.value)}
                    className={`px-3 py-1.5 rounded text-[12px] font-mono transition-colors ${
                        active === f.value
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary text-muted-foreground hover:text-foreground"
                    }`}
                >
                    {f.label}
                </button>
            ))}
        </div>
    )
}



function EmptyState({ filtered }: { filtered: boolean }) {
    return (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="p-4 rounded-full bg-secondary">
                <FileText className="h-8 w-8 text-muted-foreground" />
            </div>
            <div className="text-center">
                <p className="font-serif text-lg font-bold text-foreground mb-1">
                    {filtered ? "No applications match this filter" : "No applications yet"}
                </p>
                <p className="text-[13px] text-muted-foreground">
                    {filtered ? "Try a different filter" : "Applications will appear here once submitted"}
                </p>
            </div>
        </div>
    )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ApplicationsPage() {
    const { backendUser } = useAuthContext()
    const isRecruiter = backendUser?.role === "recruiter" || backendUser?.role === "admin"

    const [applications, setApplications] = useState<Application[]>([])
    const [loading,      setLoading]      = useState(true)
    const [error,        setError]        = useState<string | null>(null)
    const [filter,       setFilter]       = useState<ApplicationStatus | "all">("all")
    const [acting,       setActing]       = useState<string | null>(null)

    useEffect(() => {
        if (!backendUser) return
        const params = isRecruiter
            ? { job_id: undefined, candidate_id: undefined, limit: 100 }
            : { candidate_id: backendUser.id, limit: 100 }

        applicationsApi.list(params)
            .then(setApplications)
            .catch(() => setError("Failed to load applications"))
            .finally(() => setLoading(false))
    }, [backendUser])

    const handleStatusChange = async (app: Application, status: ApplicationStatus) => {
        setActing(app.id)
        try {
            const updated = await applicationsApi.updateStatus(app.id, { status })
            setApplications(prev => prev.map(a => a.id === updated.id ? updated : a))
        } catch {
            setError("Failed to update status")
        } finally {
            setActing(null)
        }
    }

    const handleWithdraw = async (app: Application) => {
        setActing(app.id)
        try {
            await applicationsApi.withdraw(app.id)
            setApplications(prev => prev.filter(a => a.id !== app.id))
        } catch {
            setError("Failed to withdraw application")
        } finally {
            setActing(null)
        }
    }

    const filtered = filter === "all"
        ? applications
        : applications.filter(a => a.status === filter)

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <div>
                <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">
                    {isRecruiter ? "Recruiter" : "Candidate"}
                </p>
                <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">Applications</h1>
            </div>

            {error && (
                <div className="flex items-center gap-2.5 p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0" />{error}
                </div>
            )}

            <FilterTabs active={filter} onChange={setFilter} />

            {!loading && (
                <p className="text-[12px] text-muted-foreground font-mono">
                    {filtered.length} {filtered.length === 1 ? "application" : "applications"}
                </p>
            )}

            {loading ? (
                <div className="space-y-3">
                    {[...Array(5)].map((_, i) => (
                        <Card key={i}><CardContent className="p-4"><Skeleton className="h-16 w-full" /></CardContent></Card>
                    ))}
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState filtered={filter !== "all"} />
            ) : (
                <div className="space-y-2">
                    {filtered.map(app => (
                        <ApplicationRow
                            key={app.id}
                            app={app}
                            isRecruiter={isRecruiter}
                            acting={acting === app.id}
                            onStatusChange={status => handleStatusChange(app, status)}
                            onWithdraw={() => handleWithdraw(app)}
                        />
                    ))}
                </div>
            )}
        </main>
    )
}