import { useEffect, useState } from "react"
import { useAuthContext } from "@/hooks/useAuthContext"
import { candidatesApi, type Candidate, type UpdateCandidatePayload } from "@/helpers/api/candidates.api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {ResumeCard} from "@/components/ProfileResumeCard"
import {EditForm} from "@/components/ProfileEditForm"
import config from "@/config"
import {
    Mail, Phone, Linkedin, MapPin,
    Pencil, AlertCircle
} from "lucide-react"






function ProfileHeader({ candidate }: { candidate: Candidate }) {
    const initials = candidate.full_name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase()

    return (
        <div className="flex items-center gap-5">
            <Avatar className="h-16 w-16">
                <AvatarFallback className="bg-primary/10 text-primary text-lg font-bold">
                    {initials}
                </AvatarFallback>
            </Avatar>
            <div>
                <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">
                    {candidate.full_name}
                </h1>
                {candidate.headline && (
                    <p className="text-[13px] text-muted-foreground mt-0.5">{candidate.headline}</p>
                )}
            </div>
        </div>
    )
}

function ContactInfo({ candidate }: { candidate: Candidate }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">Contact</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5">
                <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                    <Mail className="h-3.5 w-3.5 shrink-0" />{candidate.contact.email}
                </div>
                {candidate.contact.phone && (
                    <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                        <Phone className="h-3.5 w-3.5 shrink-0" />{candidate.contact.phone}
                    </div>
                )}
                {candidate.contact.linkedin_url && (
                    <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                        <Linkedin className="h-3.5 w-3.5 shrink-0" />
                        <a href={candidate.contact.linkedin_url} target="_blank" rel="noopener noreferrer" className="hover:text-primary transition-colors truncate">
                            {candidate.contact.linkedin_url}
                        </a>
                    </div>
                )}
                {candidate.location && (
                    <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                        <MapPin className="h-3.5 w-3.5 shrink-0" />{candidate.location}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}

function SkillsCard({ skills }: { skills: string[] }) {
    if (skills.length === 0) return null
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">Skills</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
                {skills.map(s => (
                    <Badge key={s} variant="secondary" className="font-mono text-[11px] px-2.5 py-1">{s}</Badge>
                ))}
            </CardContent>
        </Card>
    )
}



export default function ProfilePage() {
    const { backendUser } = useAuthContext()

    const [candidate, setCandidate] = useState<Candidate | null>(null)
    const [loading,   setLoading]   = useState(true)
    const [error,     setError]     = useState<string | null>(null)
    const [editing,   setEditing]   = useState(false)

    useEffect(() => {
        if (!backendUser?.id) return
        // Candidate profile is linked to the user — fetch by user context
        // The /candidates endpoint requires a candidate_id, not user_id
        // For now we list and find the matching one
        candidatesApi.list({ limit: 100 })
            .then(all => {
                const mine = all.find(c => c.user_id === backendUser.id)
                if (mine) setCandidate(mine)
                else setError("No candidate profile found for your account")
            })
            .catch(() => setError("Failed to load profile"))
            .finally(() => setLoading(false))
    }, [backendUser])

    const handleSave = async (payload: UpdateCandidatePayload) => {
        if (!candidate) return
        try {
            const updated = await candidatesApi.update(candidate.id, payload)
            setCandidate(updated)
            setEditing(false)
        } catch {
            setError("Failed to save profile")
        }
    }

    const handleUpload = async (file: File) => {
        if (!candidate) return
        try {
            const formData = new FormData()
            formData.append("file", file)
            // Resume upload is multipart — use fetch directly
            const res = await fetch(
                `${config.publicApiUrl ?? "http://localhost:8000"}/api/v1/candidates/${candidate.id}/resume`,
                { method: "POST", body: formData }
            )
            if (!res.ok) throw new Error()
            const updated = await res.json()
            setCandidate(updated)
        } catch {
            setError("Failed to upload resume")
        }
    }

    const handleDeleteResume = async () => {
        if (!candidate) return
        try {
            await candidatesApi.deleteResume(candidate.id)
            // Re-fetch to get updated resume state
            const fresh = await candidatesApi.getById(candidate.id)
            setCandidate(fresh)
        } catch {
            setError("Failed to remove resume")
        }
    }

    if (loading) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <Skeleton className="h-16 w-full" />
            <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-4"><Skeleton className="h-32 w-full" /></div>
                <div className="space-y-4"><Skeleton className="h-32 w-full" /><Skeleton className="h-40 w-full" /></div>
            </div>
        </main>
    )

    if (error || !candidate) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
            <div className="flex items-center gap-2.5 p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error ?? "Profile not found"}
            </div>
        </main>
    )

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">Candidate</p>
                    <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">My Profile</h1>
                </div>
                {!editing && (
                    <Button variant="outline" size="sm" className="font-mono text-[12px] gap-1.5" onClick={() => setEditing(true)}>
                        <Pencil className="h-3.5 w-3.5" /> Edit
                    </Button>
                )}
            </div>

            <ProfileHeader candidate={candidate} />
            <Separator />

            <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-5">
                    {editing ? (
                        <Card>
                            <CardHeader className="pb-4">
                                <CardTitle className="font-serif text-base font-bold">Edit Profile</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <EditForm candidate={candidate} onSave={handleSave} onCancel={() => setEditing(false)} />
                            </CardContent>
                        </Card>
                    ) : (
                        <ContactInfo candidate={candidate} />
                    )}
                    {candidate.skills && <SkillsCard skills={candidate.skills} />}
                </div>

                <div className="space-y-5">
                    <ResumeCard
                        candidate={candidate}
                        onUpload={handleUpload}
                        onDelete={handleDeleteResume}
                    />
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="font-serif text-base font-bold">Details</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-0">
                            {[
                                { label: "Status",  value: candidate.status },
                                { label: "Member since", value: new Date(candidate.created_at).toLocaleDateString("en-US", { month: "short", year: "numeric" }) },
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