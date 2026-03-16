import { useEffect, useState } from "react"
import { useAuthContext } from "@/hooks/useAuthContext"
import { jobsApi, type Job } from "@/helpers/api/jobs.api"
import { applicationsApi } from "@/helpers/api/applications.api"
import { candidatesApi, type Candidate } from "@/helpers/api/candidates.api"
import { orgsApi, type Org } from "@/helpers/api/orgs.api"
import { JobListingCard } from "@/components/JobListingCard"
import { Button } from "@/components/ui/button"
import {Card, CardContent} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
    Dialog, DialogContent, DialogHeader,
    DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog"
import {
    Search, Briefcase, CheckCircle2, AlertCircle,
} from "lucide-react"



function EmptyState({ filtered }: { filtered: boolean }) {
    return (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="p-4 rounded-full bg-secondary">
                <Briefcase className="h-8 w-8 text-muted-foreground" />
            </div>
            <div className="text-center">
                <p className="font-serif text-lg font-bold text-foreground mb-1">
                    {filtered ? "No jobs match your search" : "No active jobs right now"}
                </p>
                <p className="text-[13px] text-muted-foreground">
                    {filtered ? "Try a different search term" : "Check back later for new opportunities"}
                </p>
            </div>
        </div>
    )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function JobListingsPage() {
    const { backendUser } = useAuthContext()

    const [jobs,       setJobs]       = useState<Job[]>([])
    const [orgs,       setOrgs]       = useState<Record<string, Org>>({})
    const [candidate,  setCandidate]  = useState<Candidate | null>(null)
    const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set())
    const [applying,   setApplying]   = useState<string | null>(null)
    const [loading,    setLoading]    = useState(true)
    const [error,      setError]      = useState<string | null>(null)
    const [search,     setSearch]     = useState("")
    const [successJob, setSuccessJob] = useState<Job | null>(null)

    useEffect(() => {
        if (!backendUser?.id) return

        const load = async () => {
            try {
                setLoading(true)

                // Load jobs, candidate profile and existing applications in parallel
                const [activeJobs, allCandidates, myApplications] = await Promise.all([
                    jobsApi.listActive({ limit: 100 }),
                    candidatesApi.list({ limit: 100 }),
                    applicationsApi.list({ candidate_id: backendUser.id, limit: 100 }).catch(() => []),
                ])

                setJobs(activeJobs)

                // Find this user's candidate profile
                const mine = allCandidates.find(c => c.user_id === backendUser.id)
                setCandidate(mine ?? null)

                // Track already-applied job IDs
                setAppliedIds(new Set(myApplications.map(a => a.job_id)))

                // Fetch org details for each unique org_id
                const uniqueOrgIds = [...new Set(activeJobs.map(j => j.org_id))]
                const orgResults = await Promise.allSettled(
                    uniqueOrgIds.map(id => orgsApi.getById(id))
                )
                const orgMap: Record<string, Org> = {}
                orgResults.forEach((result, i) => {
                    if (result.status === "fulfilled") {
                        orgMap[uniqueOrgIds[i]] = result.value
                    }
                })
                setOrgs(orgMap)

            } catch {
                setError("Failed to load jobs")
            } finally {
                setLoading(false)
            }
        }

        load()
    }, [backendUser])

    const handleApply = async (job: Job) => {
        if (!candidate) {
            setError("No candidate profile found. Please complete your profile first.")
            return
        }

        setApplying(job.id)
        try {
            await applicationsApi.create({
                job_id: job.id,
                candidate_id: candidate.id,
                source: "applied",
            })
            setAppliedIds(prev => new Set([...prev, job.id]))
            setSuccessJob(job)
        } catch (e: any) {
            const detail = e?.response?.data?.detail
            if (typeof detail === "string" && detail.includes("already exists")) {
                setAppliedIds(prev => new Set([...prev, job.id]))
            } else {
                setError("Failed to submit application. Please try again.")
            }
        } finally {
            setApplying(null)
        }
    }

    const filtered = jobs.filter(j =>
        j.title.toLowerCase().includes(search.toLowerCase()) ||
        j.description.toLowerCase().includes(search.toLowerCase()) ||
        j.skills.some(s => s.name.toLowerCase().includes(search.toLowerCase())) ||
        j.requirements.location?.toLowerCase().includes(search.toLowerCase())
    )

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            {/* Header */}
            <div>
                <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">Candidate</p>
                <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">Browse Jobs</h1>
            </div>

            {/* No profile warning */}
            {!loading && !candidate && (
                <div className="flex items-center gap-2.5 p-4 bg-amber-500/5 border border-amber-500/20 rounded-lg text-[13px] text-amber-400">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    You don't have a candidate profile yet. Go to Profile to set one up before applying.
                </div>
            )}

            {error && (
                <div className="flex items-center gap-2.5 p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0" />{error}
                </div>
            )}

            {/* Search */}
            <div className="relative max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                    placeholder="Search by title, skill or location…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="pl-9 bg-background"
                />
            </div>

            {!loading && (
                <p className="text-[12px] text-muted-foreground font-mono">
                    {filtered.length} {filtered.length === 1 ? "job" : "jobs"} available
                </p>
            )}

            {/* Grid */}
            {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {[...Array(6)].map((_, i) => (
                        <Card key={i}><CardContent className="p-6"><Skeleton className="h-48 w-full" /></CardContent></Card>
                    ))}
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState filtered={search !== ""} />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filtered.map(job => (
                        <JobListingCard
                            key={job.id}
                            job={job}
                            org={orgs[job.org_id] ?? null}
                            applied={appliedIds.has(job.id)}
                            applying={applying === job.id}
                            onApply={() => handleApply(job)}
                        />
                    ))}
                </div>
            )}

            {/* Success dialog */}
            <Dialog open={!!successJob} onOpenChange={() => setSuccessJob(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle className="font-serif text-xl font-bold flex items-center gap-2">
                            <CheckCircle2 className="h-5 w-5 text-primary" />
                            Application Submitted
                        </DialogTitle>
                        <DialogDescription className="text-[13px] text-muted-foreground">
                            You've successfully applied for <strong>{successJob?.title}</strong>.
                            The recruiter will review your application and you'll be contacted if you're selected for an interview.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button
                            className="font-mono text-[12px]"
                            onClick={() => setSuccessJob(null)}
                        >
                            Got it
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </main>
    )
}