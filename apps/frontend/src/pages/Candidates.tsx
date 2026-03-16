import { useEffect, useState } from "react"
import { candidatesApi, type Candidate } from "@/helpers/api/candidates.api"
import { CandidateCard } from "@/components/CandidateCard"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent } from "@/components/ui/card"
import { Users, Search } from "lucide-react"

function EmptyState({ filtered }: { filtered: boolean }) {
    return (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="p-4 rounded-full bg-secondary">
                <Users className="h-8 w-8 text-muted-foreground" />
            </div>
            <div className="text-center">
                <p className="font-serif text-lg font-bold text-foreground mb-1">
                    {filtered ? "No candidates match your search" : "No candidates yet"}
                </p>
                <p className="text-[13px] text-muted-foreground">
                    {filtered ? "Try a different search term" : "Candidates will appear here once they apply"}
                </p>
            </div>
        </div>
    )
}

export default function CandidatesPage() {
    const [candidates, setCandidates] = useState<Candidate[]>([])
    const [loading, setLoading]       = useState(true)
    const [error, setError]           = useState<string | null>(null)
    const [search, setSearch]         = useState("")

    useEffect(() => {
        candidatesApi.list({ limit: 100 })
            .then(setCandidates)
            .catch(() => setError("Failed to load candidates"))
            .finally(() => setLoading(false))
    }, [])

    const filtered = candidates.filter(c =>
        c.full_name.toLowerCase().includes(search.toLowerCase()) ||
        c.contact.email.toLowerCase().includes(search.toLowerCase()) ||
        c.headline?.toLowerCase().includes(search.toLowerCase()) ||
        c.skills?.some(s => s.toLowerCase().includes(search.toLowerCase()))
    )

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <div>
                <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">Recruiter</p>
                <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">Candidates</h1>
            </div>

            {error && (
                <div className="p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                    {error}
                </div>
            )}

            <div className="relative max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                    placeholder="Search by name, email or skill…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="pl-9 bg-background"
                />
            </div>

            {!loading && (
                <p className="text-[12px] text-muted-foreground font-mono">
                    {filtered.length} {filtered.length === 1 ? "candidate" : "candidates"}
                </p>
            )}

            {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {[...Array(6)].map((_, i) => (
                        <Card key={i}><CardContent className="p-5"><Skeleton className="h-36 w-full" /></CardContent></Card>
                    ))}
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState filtered={search !== ""} />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {filtered.map(c => <CandidateCard key={c.id} candidate={c} />)}
                </div>
            )}
        </main>
    )
}