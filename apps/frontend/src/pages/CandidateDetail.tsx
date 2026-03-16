import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router"
import { candidatesApi, type Candidate } from "@/helpers/api/candidates.api"
import { applicationsApi, type Application } from "@/helpers/api/applications.api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import {
    ArrowLeft, AlertCircle,
} from "lucide-react"
import { CandidateHeader } from "@/components/CandidateHeader"
import { ApplicationsCard } from "@/components/ApplicationsCard"
import { ResumeCard } from "@/components/ResumeCard"




function SkillsList({ skills }: { skills: string[] }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">Skills</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
                {skills.map(s => (
                    <Badge key={s} variant="secondary" className="font-mono text-[11px] px-2.5 py-1">
                        {s}
                    </Badge>
                ))}
            </CardContent>
        </Card>
    )
}

function BioCard({ bio }: { bio: string }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">About</CardTitle>
            </CardHeader>
            <CardContent>
                <p className="text-[13px] text-muted-foreground leading-relaxed">{bio}</p>
            </CardContent>
        </Card>
    )
}




export default function CandidateDetailPage() {
    const { candidateId } = useParams<{ candidateId: string }>()
    const navigate = useNavigate()

    const [candidate,    setCandidate]    = useState<Candidate | null>(null)
    const [applications, setApplications] = useState<Application[]>([])
    const [loading,      setLoading]      = useState(true)
    const [error,        setError]        = useState<string | null>(null)

    useEffect(() => {
        if (!candidateId) return
        Promise.all([
            candidatesApi.getById(candidateId),
            applicationsApi.list({ candidate_id: candidateId, limit: 50 }).catch(() => []),
        ])
            .then(([c, apps]) => { setCandidate(c); setApplications(apps) })
            .catch(() => setError("Failed to load candidate"))
            .finally(() => setLoading(false))
    }, [candidateId])

    const handleDownloadResume = async () => {
        if (!candidateId) return
        try {
            const { url } = await candidatesApi.getResumeUrl(candidateId)
            window.open(url, "_blank")
        } catch {
            setError("Failed to get resume download link")
        }
    }

    if (loading) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-24 w-full" />
            <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-4">
                    <Skeleton className="h-40 w-full" />
                    <Skeleton className="h-32 w-full" />
                </div>
                <Skeleton className="h-48 w-full" />
            </div>
        </main>
    )

    if (error || !candidate) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
            <div className="flex items-center gap-2.5 p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error ?? "Candidate not found"}
            </div>
        </main>
    )

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            {/* Back */}
            <Button variant="ghost" size="sm" className="gap-1.5 font-mono text-[12px] -ml-2" onClick={() => navigate("/candidates")}>
                <ArrowLeft className="h-3.5 w-3.5" /> Candidates
            </Button>

            <CandidateHeader candidate={candidate} />

            <Separator />

            <div className="grid lg:grid-cols-3 gap-6">
                {/* Left */}
                <div className="lg:col-span-2 space-y-5">
                    {candidate.bio && <BioCard bio={candidate.bio} />}
                    {candidate.skills && candidate.skills.length > 0 && (
                        <SkillsList skills={candidate.skills} />
                    )}
                    <ApplicationsCard applications={applications} />
                </div>

                {/* Right */}
                <div className="space-y-5">
                    <ResumeCard candidate={candidate} onDownload={handleDownloadResume} />
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="font-serif text-base font-bold">Details</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-0">
                            {[
                                { label: "Status",  value: candidate.status },
                                { label: "Joined",  value: new Date(candidate.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) },
                            ].map(({ label, value }) => (
                                <div key={label} className="flex justify-between items-center py-2.5 border-b border-border last:border-0">
                                    <span className="text-[12px] text-muted-foreground">{label}</span>
                                    <span className="text-[12px] font-mono text-foreground capitalize">{value}</span>
                                </div>
                            ))}
                        </CardContent>
                    </Card>
                </div>
            </div>
        </main>
    )
}