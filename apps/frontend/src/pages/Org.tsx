import { useEffect, useState } from "react"
import { useAuthContext } from "@/hooks/useAuthContext"
import { orgsApi, type Org, type UpdateOrgPayload } from "@/helpers/api/orgs.api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"

import { Building2, Globe, Mail, Phone, AlertCircle, Pencil } from "lucide-react"
import { OrgHeader } from "@/components/OrgHeader"
import {EditForm} from "@/components/OrgEditForm"

// ── Schema ────────────────────────────────────────────────────────────────────




// ── Sub-components ────────────────────────────────────────────────────────────



function BillingCard({ org }: { org: Org }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">Plan & Usage</CardTitle>
            </CardHeader>
            <CardContent className="space-y-0">
                {[
                    { label: "Plan",              value: org.billing.plan },
                    { label: "Active Job Limit",  value: String(org.billing.max_active_jobs) },
                    { label: "Monthly Interviews",value: String(org.billing.max_interviews_per_month) },
                ].map(({ label, value }) => (
                    <div key={label} className="flex justify-between items-center py-2.5 border-b border-border last:border-0">
                        <span className="text-[12px] text-muted-foreground">{label}</span>
                        <span className="text-[12px] font-mono text-foreground capitalize">{value}</span>
                    </div>
                ))}
            </CardContent>
        </Card>
    )
}

function ContactCard({ org }: { org: Org }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">Contact</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5">
                <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                    <Mail className="h-3.5 w-3.5 shrink-0" />
                    <span>{org.contact.email}</span>
                </div>
                {org.contact.phone && (
                    <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                        <Phone className="h-3.5 w-3.5 shrink-0" />
                        <span>{org.contact.phone}</span>
                    </div>
                )}
                {org.contact.website && (
                    <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
                        <Globe className="h-3.5 w-3.5 shrink-0" />
                        <a href={org.contact.website} target="_blank" rel="noopener noreferrer" className="hover:text-primary transition-colors truncate">
                            {org.contact.website}
                        </a>
                    </div>
                )}
            </CardContent>
        </Card>
    )
}




// ── Page ──────────────────────────────────────────────────────────────────────

export default function OrgPage() {
    const { backendUser } = useAuthContext()
    const [org,     setOrg]     = useState<Org | null>(null)
    const [loading, setLoading] = useState(true)
    const [error,   setError]   = useState<string | null>(null)
    const [editing, setEditing] = useState(false)

    useEffect(() => {
        if (!backendUser?.org_id) { setLoading(false); return }
        orgsApi.getById(backendUser.org_id)
            .then(setOrg)
            .catch(() => setError("Failed to load organisation"))
            .finally(() => setLoading(false))
    }, [backendUser])

    const handleSave = async (payload: UpdateOrgPayload) => {
        if (!org) return
        try {
            const updated = await orgsApi.update(org.id, payload)
            setOrg(updated)
            setEditing(false)
        } catch {
            setError("Failed to save changes")
        }
    }

    if (loading) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <Skeleton className="h-16 w-full" />
            <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2"><Skeleton className="h-48 w-full" /></div>
                <div className="space-y-4"><Skeleton className="h-32 w-full" /><Skeleton className="h-32 w-full" /></div>
            </div>
        </main>
    )

    if (!backendUser?.org_id) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
            <div className="flex items-center gap-2.5 p-4 bg-muted border border-border rounded-lg text-[13px] text-muted-foreground">
                <Building2 className="h-4 w-4 shrink-0" />
                You are not part of an organisation yet.
            </div>
        </main>
    )

    if (error || !org) return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
            <div className="flex items-center gap-2.5 p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />{error ?? "Organisation not found"}
            </div>
        </main>
    )

    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6">
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground mb-1">Settings</p>
                    <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">Organisation</h1>
                </div>
                {!editing && (
                    <Button variant="outline" size="sm" className="font-mono text-[12px] gap-1.5" onClick={() => setEditing(true)}>
                        <Pencil className="h-3.5 w-3.5" /> Edit
                    </Button>
                )}
            </div>

            <OrgHeader org={org} />
            <Separator />

            <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-5">
                    {editing ? (
                        <Card>
                            <CardHeader className="pb-4">
                                <CardTitle className="font-serif text-base font-bold">Edit Organisation</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <EditForm org={org} onSave={handleSave} onCancel={() => setEditing(false)} />
                            </CardContent>
                        </Card>
                    ) : (
                        <Card>
                            <CardHeader className="pb-3">
                                <CardTitle className="font-serif text-base font-bold">About</CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-0">
                                {org.description && (
                                    <p className="text-[13px] text-muted-foreground leading-relaxed mb-4">{org.description}</p>
                                )}
                                {[
                                    { label: "Industry",  value: org.industry ?? "—" },
                                    { label: "Headcount", value: org.headcount ?? "—" },
                                ].map(({ label, value }) => (
                                    <div key={label} className="flex justify-between items-center py-2.5 border-b border-border last:border-0">
                                        <span className="text-[12px] text-muted-foreground">{label}</span>
                                        <span className="text-[12px] font-mono text-foreground">{value}</span>
                                    </div>
                                ))}
                            </CardContent>
                        </Card>
                    )}
                </div>

                <div className="space-y-5">
                    <ContactCard org={org} />
                    <BillingCard org={org} />
                </div>
            </div>
        </main>
    )
}