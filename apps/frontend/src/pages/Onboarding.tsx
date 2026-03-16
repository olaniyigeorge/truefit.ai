
import { useState } from "react"
import {useNavigate} from "react-router"
import {useAuthContext} from "@/hooks/useAuthContext"
import { usersApi } from "@/helpers/api/users.api"
import { orgsApi } from "@/helpers/api/orgs.api"
import { SpiralLogo } from "@/components/Spiral"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
// import { Separator } from "@/components/ui/separator"
import { signOut } from "firebase/auth"
import { auth } from "@/helpers/firebase"
import { Users, Briefcase, ArrowRight, AlertCircle, Building2 } from "lucide-react"



type Role = "candidate" | "recruiter"
type OrgAction = "create" | "join"


function Steps({ current, total }: { current: number; total: number }) {
    return (
        <div className="flex items-center gap-2">
            {Array.from({ length: total }).map((_, i) => (
                <div
                    key={i}
                    className={`h-1 rounded-full transition-all duration-300 ${
                        i < current
                            ? "w-8 bg-primary"
                            : i === current
                            ? "w-8 bg-primary/60"
                            : "w-4 bg-border"
                    }`}
                />
            ))}
        </div>
    )
}

const Onboarding = () => {
    const navigate = useNavigate()
    const { backendUser } = useAuthContext()
 
    const [step, setStep] = useState<"role" | "org">("role")
    const [role, setRole] = useState<Role | null>(null)
    const [orgAction, setOrgAction] = useState<OrgAction>("create")
 
    // Org create fields
    const [orgName, setOrgName] = useState("")
    const [orgSlug, setOrgSlug] = useState("")
    const [orgEmail, setOrgEmail] = useState("")
 
    // Org join fields
    const [joinSlug, setJoinSlug] = useState("")
 
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
 
    const totalSteps = role === "recruiter" ? 2 : 1
    const currentStep = step === "role" ? 0 : 1
 
    const handleRoleSelect = async (selected: Role) => {
        setRole(selected)
        if (selected === "candidate") {
            // Update role to candidate (it already is, but confirm) and go to dashboard
            await finalize(selected)
        } else {
            setStep("org")
        }
    }


     const finalize = async (selectedRole: Role) => {
        if (!backendUser?.id) return
        setLoading(true)
        setError(null)
        try {
            await usersApi.update(backendUser.id, { role: selectedRole })
            document.cookie = "jwt=; path=/; max-age=0"
            await signOut(auth)
            // Re-hydrate context by navigating — context reads role from JWT cookie on next load
            // For now navigate to dashboard; a full re-auth would refresh the JWT with new role
            navigate("/auth", { replace: true })
        } catch {
            setError("Failed to save your role. Please try again.")
        } finally {
            setLoading(false)
        }
    }


    const handleOrgSubmit = async () => {
        if (!backendUser?.id) return
        setLoading(true)
        setError(null)
 
        try {
            // First update role to recruiter
            await usersApi.update(backendUser.id, { role: "recruiter" })
 
            if (orgAction === "create") {
                if (!orgName.trim() || !orgEmail.trim()) {
                    setError("Org name and contact email are required.")
                    setLoading(false)
                    return
                }
                const slug = orgSlug.trim() || orgName.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")
                await orgsApi.create({
                    name: orgName.trim(),
                    slug,
                    created_by: backendUser.id,
                    contact: { email: orgEmail.trim() },
                })
            } else {
                // Join existing org by slug
                if (!joinSlug.trim()) {
                    setError("Please enter your organisation's slug.")
                    setLoading(false)
                    return
                }
                const org = await orgsApi.getBySlug(joinSlug.trim())
                await usersApi.joinOrg(backendUser.id, org.id)
            }
 
            document.cookie = "jwt=; path=/; max-age=0"
            await signOut(auth)
            navigate("/auth", { replace: true })
        } catch (e: any) {
            const detail = e?.response?.data?.detail
            setError(typeof detail === "string" ? detail : "Something went wrong. Please try again.")
        } finally {
            setLoading(false)
        }
    }

  return (
    <div className="relative min-h-screen bg-background flex items-center justify-center p-6 overflow-hidden">
            {/* Overlays */}
            <div className="overlay-noise" />
            <div className="overlay-grid" />
            <div
                className="fixed pointer-events-none"
                style={{
                    top: "40%", left: "50%", transform: "translate(-50%, -50%)",
                    width: 500, height: 500, borderRadius: "50%",
                    background: "radial-gradient(circle, rgba(34,197,94,0.06) 0%, transparent 70%)",
                }}
            />
 
            <div className="relative z-10 w-full max-w-md flex flex-col gap-8">
                {/* Logo */}
                <div className="flex flex-col items-center gap-3 text-center">
                    <div className="flex items-center gap-2.5">
                        <SpiralLogo size={28} />
                        <span className="font-serif text-xl font-bold">
                            True<span className="text-primary">Fit</span>.ai
                        </span>
                    </div>
                    <Steps current={currentStep} total={totalSteps} />
                </div>
 
                {/* ── Step 1: Role selection ── */}
                {step === "role" && (
                    <div className="flex flex-col gap-5">
                        <div className="text-center">
                            <h1 className="font-serif text-2xl font-bold text-foreground tracking-tight mb-1.5">
                                How are you using TrueFit?
                            </h1>
                            <p className="text-[13px] text-muted-foreground leading-relaxed">
                                This helps us personalise your experience.
                            </p>
                        </div>
 
                        <div className="grid grid-cols-2 gap-3">
                            <button
                                onClick={() => handleRoleSelect("recruiter")}
                                disabled={loading}
                                className="group flex flex-col items-center gap-4 p-6 bg-card border border-border rounded-xl hover:border-primary/40 hover:bg-primary/5 transition-all duration-200 text-left disabled:opacity-50"
                            >
                                <div className="p-3 rounded-lg bg-secondary group-hover:bg-primary/10 transition-colors">
                                    <Briefcase className="h-6 w-6 text-muted-foreground group-hover:text-primary transition-colors" />
                                </div>
                                <div>
                                    <p className="font-serif text-base font-bold text-foreground mb-1">I'm Hiring</p>
                                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                                        Screen candidates with AI interviews
                                    </p>
                                </div>
                            </button>
 
                            <button
                                onClick={() => handleRoleSelect("candidate")}
                                disabled={loading}
                                className="group flex flex-col items-center gap-4 p-6 bg-card border border-border rounded-xl hover:border-primary/40 hover:bg-primary/5 transition-all duration-200 text-left disabled:opacity-50"
                            >
                                <div className="p-3 rounded-lg bg-secondary group-hover:bg-primary/10 transition-colors">
                                    <Users className="h-6 w-6 text-muted-foreground group-hover:text-primary transition-colors" />
                                </div>
                                <div>
                                    <p className="font-serif text-base font-bold text-foreground mb-1">I'm Job Seeking</p>
                                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                                        Practice and apply for roles
                                    </p>
                                </div>
                            </button>
                        </div>
 
                        {error && (
                            <div className="flex items-center gap-2.5 p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[12px] text-destructive">
                                <AlertCircle className="h-4 w-4 shrink-0" />
                                {error}
                            </div>
                        )}
                    </div>
                )}
 
                {/* ── Step 2: Org setup (recruiter only) ── */}
                {step === "org" && (
                    <div className="flex flex-col gap-5">
                        <div className="text-center">
                            <h1 className="font-serif text-2xl font-bold text-foreground tracking-tight mb-1.5">
                                Set up your organisation
                            </h1>
                            <p className="text-[13px] text-muted-foreground leading-relaxed">
                                Create a new org or join an existing one.
                            </p>
                        </div>
 
                        {/* Toggle */}
                        <div className="flex gap-1 p-1 bg-secondary rounded-lg">
                            {(["create", "join"] as OrgAction[]).map(a => (
                                <button
                                    key={a}
                                    onClick={() => { setOrgAction(a); setError(null) }}
                                    className={`flex-1 py-2 rounded-md text-[12px] font-mono transition-all ${
                                        orgAction === a
                                            ? "bg-card text-foreground shadow-sm"
                                            : "text-muted-foreground hover:text-foreground"
                                    }`}
                                >
                                    {a === "create" ? "Create New" : "Join Existing"}
                                </button>
                            ))}
                        </div>
 
                        <Card>
                            <CardContent className="p-5 flex flex-col gap-4">
                                {orgAction === "create" ? (
                                    <>
                                        <div className="space-y-1.5">
                                            <Label className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">
                                                Organisation Name
                                            </Label>
                                            <Input
                                                value={orgName}
                                                onChange={e => {
                                                    setOrgName(e.target.value)
                                                    setOrgSlug(e.target.value.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, ""))
                                                }}
                                                placeholder="Acme Corp"
                                                className="bg-background"
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">
                                                Slug
                                            </Label>
                                            <Input
                                                value={orgSlug}
                                                onChange={e => setOrgSlug(e.target.value)}
                                                placeholder="acme-corp"
                                                className="bg-background font-mono text-[12px]"
                                            />
                                            <p className="text-[11px] text-muted-foreground/60">Auto-generated from name. Lowercase, hyphens only.</p>
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">
                                                Contact Email
                                            </Label>
                                            <Input
                                                value={orgEmail}
                                                onChange={e => setOrgEmail(e.target.value)}
                                                type="email"
                                                placeholder="hiring@acme.com"
                                                className="bg-background"
                                            />
                                        </div>
                                    </>
                                ) : (
                                    <div className="space-y-1.5">
                                        <Label className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">
                                            Organisation Slug
                                        </Label>
                                        <Input
                                            value={joinSlug}
                                            onChange={e => setJoinSlug(e.target.value)}
                                            placeholder="acme-corp"
                                            className="bg-background font-mono text-[12px]"
                                        />
                                        <p className="text-[11px] text-muted-foreground/60">
                                            Ask your team admin for your org's slug.
                                        </p>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
 
                        {error && (
                            <div className="flex items-center gap-2.5 p-3.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[12px] text-destructive">
                                <AlertCircle className="h-4 w-4 shrink-0" />
                                {error}
                            </div>
                        )}
 
                        <div className="flex gap-3">
                            <Button
                                variant="ghost"
                                className="font-mono text-[12px]"
                                onClick={() => { setStep("role"); setError(null) }}
                                disabled={loading}
                            >
                                ← Back
                            </Button>
                            <Button
                                className="flex-1 font-mono text-[12px] gap-2"
                                onClick={handleOrgSubmit}
                                disabled={loading}
                            >
                                <Building2 className="h-4 w-4" />
                                {loading ? "Setting up…" : "Continue to Dashboard"}
                                {!loading && <ArrowRight className="h-3.5 w-3.5" />}
                            </Button>
                        </div>
                    </div>
                )}
            </div>
        </div>
  )
}

export default Onboarding