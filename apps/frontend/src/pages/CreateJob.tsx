import { useState } from "react"
import { useAuthContext } from "@/hooks/useAuthContext"
import type { JobSkill } from "@/helpers/api/jobs.api"
import { useNavigate } from "react-router"
import {type CreateJobPayload, jobsApi } from "@/helpers/api/jobs.api"
import { Button } from "@/components/ui/button"
import {Card, CardHeader, CardContent, CardTitle} from "@/components/ui/card"
import {Input} from "@/components/ui/input"
import { ArrowLeft, AlertCircle } from "lucide-react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import {
    Form, FormField, FormItem, FormLabel, FormControl, FormMessage
} from "@/components/ui/form"
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {SkillsEditor} from "@/components/SkillsEditor"


// type FormState = {
//     title: string
//     description: string
//     experience_level: string
//     min_total_years: string
//     location: string
//     work_arrangement: string
//     education: string
//     max_questions: string
//     max_duration_minutes: string
//     topics: string
//     custom_instructions: string
// }
 
// const INITIAL_FORM: FormState = {
//     title: "",
//     description: "",
//     experience_level: "mid",
//     min_total_years: "",
//     location: "",
//     work_arrangement: "remote",
//     education: "",
//     max_questions: "8",
//     max_duration_minutes: "30",
//     topics: "",
//     custom_instructions: "",
// }


const schema = z.object({
    title:                z.string().min(2, "Title is required"),
    description:          z.string().min(10, "Description must be at least 10 characters"),
    experience_level:     z.enum(["junior", "mid", "senior", "lead", "principal"]),
    min_total_years:      z.string().optional(),
    location:             z.string().optional(),
    work_arrangement:     z.enum(["remote", "hybrid", "onsite"]),
    education:            z.string().optional(),
    max_questions:        z.string().min(1),
    max_duration_minutes: z.string().min(1),
    topics:               z.string().optional(),
    custom_instructions:  z.string().optional(),
})
 
type FormValues = z.infer<typeof schema>




export default function CreateJobPage() {
   const { backendUser } = useAuthContext()
    const navigate = useNavigate()
    const [skills, setSkills] = useState<JobSkill[]>([])
    const [submitting, setSubmitting] = useState(false)
    const [apiError, setApiError] = useState<string | null>(null)
 
    const form = useForm<FormValues>({
        resolver: zodResolver(schema),
        defaultValues: { title: "", description: "", experience_level: "mid", min_total_years: "", location: "", work_arrangement: "remote", education: "", max_questions: "8", max_duration_minutes: "30", topics: "", custom_instructions: "" },
    })
 
    const submit = async (values: FormValues, activate = false) => {
        if (!backendUser?.org_id || !backendUser?.id) { setApiError("Missing org or user info."); return }
        if (skills.length === 0) { setApiError("Add at least one skill."); return }
        setSubmitting(true); setApiError(null)
        try {
            const payload: CreateJobPayload = {
                org_id: backendUser.org_id, 
                created_by: backendUser.id,
                title: values.title, 
                description: values.description,
                requirements: { experience_level: values.experience_level as any, min_total_years: values.min_total_years ? parseInt(values.min_total_years) : null, location: values.location?.trim() || null, work_arrangement: values.work_arrangement as any, education: values.education?.trim() || null, certifications: [] },
                skills,
                interview_config: { max_questions: parseInt(values.max_questions), max_duration_minutes: parseInt(values.max_duration_minutes), topics: values.topics ? values.topics.split(",").map(t => t.trim()).filter(Boolean) : [], custom_instructions: values.custom_instructions?.trim() || null },
            }
            const job = await jobsApi.create(payload)
            if (activate) await jobsApi.activate(job.id)
            navigate(`/jobs/${job.id}`)
        } catch (e: any) {
            setApiError(e?.response?.data?.detail ?? "Failed to create job")
        } finally { setSubmitting(false) }
    }
 
    return (
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
            <Form {...form}>
                <form onSubmit={form.handleSubmit(v => submit(v, false))} className="max-w-3xl space-y-6">
                    <div className="flex items-center gap-4">
                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => navigate("/jobs")}><ArrowLeft className="h-4 w-4" /></Button>
                        <div>
                            <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground">Recruiter</p>
                            <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">Post a Job</h1>
                        </div>
                    </div>
 
                    {apiError && (
                        <div className="flex items-center gap-2.5 p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-[13px] text-destructive">
                            <AlertCircle className="h-4 w-4 shrink-0" />{apiError}
                        </div>
                    )}
 
                    <Card>
                        <CardHeader className="pb-4"><CardTitle className="font-serif text-base font-bold">Basic Info</CardTitle></CardHeader>
                        <CardContent className="space-y-5">
                            <FormField control={form.control} name="title" render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Job Title</FormLabel>
                                    <FormControl><Input placeholder="e.g. Senior Backend Engineer" className="bg-background" {...field} /></FormControl>
                                    <FormMessage />
                                </FormItem>
                            )} />
                            <FormField control={form.control} name="description" render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Description</FormLabel>
                                    <FormControl><Textarea placeholder="Describe the role, team, and what the candidate will be working on…" rows={5} className="bg-background resize-none" {...field} /></FormControl>
                                    <FormMessage />
                                </FormItem>
                            )} />
                        </CardContent>
                    </Card>
 
                    <Card>
                        <CardHeader className="pb-4"><CardTitle className="font-serif text-base font-bold">Requirements</CardTitle></CardHeader>
                        <CardContent className="space-y-5">
                            <div className="grid sm:grid-cols-2 gap-5">
                                <FormField control={form.control} name="experience_level" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Experience Level</FormLabel>
                                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                                            <FormControl><SelectTrigger className="bg-background"><SelectValue /></SelectTrigger></FormControl>
                                            <SelectContent>
                                                <SelectItem value="junior">Junior</SelectItem>
                                                <SelectItem value="mid">Mid</SelectItem>
                                                <SelectItem value="senior">Senior</SelectItem>
                                                <SelectItem value="lead">Lead</SelectItem>
                                                <SelectItem value="principal">Principal</SelectItem>
                                            </SelectContent>
                                        </Select>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="min_total_years" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Min. Years Experience</FormLabel>
                                        <FormControl><Input type="number" min={0} placeholder="e.g. 5" className="bg-background" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="work_arrangement" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Work Arrangement</FormLabel>
                                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                                            <FormControl><SelectTrigger className="bg-background"><SelectValue /></SelectTrigger></FormControl>
                                            <SelectContent>
                                                <SelectItem value="remote">Remote</SelectItem>
                                                <SelectItem value="hybrid">Hybrid</SelectItem>
                                                <SelectItem value="onsite">Onsite</SelectItem>
                                            </SelectContent>
                                        </Select>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="location" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Location</FormLabel>
                                        <FormControl><Input placeholder="e.g. Remote - Global" className="bg-background" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                            </div>
                            <FormField control={form.control} name="education" render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Education <span className="text-muted-foreground/50 normal-case tracking-normal">(optional)</span></FormLabel>
                                    <FormControl><Input placeholder="e.g. Bachelor's in Computer Science or equivalent" className="bg-background" {...field} /></FormControl>
                                    <FormMessage />
                                </FormItem>
                            )} />
                        </CardContent>
                    </Card>
 
                    <Card>
                        <CardHeader className="pb-4"><CardTitle className="font-serif text-base font-bold">Skills</CardTitle></CardHeader>
                        <CardContent>
                            <SkillsEditor skills={skills} onChange={setSkills} />
                            {skills.length === 0 && form.formState.isSubmitted && (
                                <p className="text-[12px] text-destructive mt-2">Add at least one skill.</p>
                            )}
                        </CardContent>
                    </Card>
 
                    <Card>
                        <CardHeader className="pb-4"><CardTitle className="font-serif text-base font-bold">Interview Setup</CardTitle></CardHeader>
                        <CardContent className="space-y-5">
                            <div className="grid sm:grid-cols-2 gap-5">
                                <FormField control={form.control} name="max_questions" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Max Questions <span className="text-muted-foreground/50 normal-case tracking-normal">(1–50)</span></FormLabel>
                                        <FormControl><Input type="number" min={1} max={50} className="bg-background" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="max_duration_minutes" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Duration (minutes) <span className="text-muted-foreground/50 normal-case tracking-normal">(5–120)</span></FormLabel>
                                        <FormControl><Input type="number" min={5} max={120} className="bg-background" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                            </div>
                            <FormField control={form.control} name="topics" render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Topics <span className="text-muted-foreground/50 normal-case tracking-normal">(comma-separated)</span></FormLabel>
                                    <FormControl><Input placeholder="system design, python, databases" className="bg-background" {...field} /></FormControl>
                                    <FormMessage />
                                </FormItem>
                            )} />
                            <FormField control={form.control} name="custom_instructions" render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Custom Instructions <span className="text-muted-foreground/50 normal-case tracking-normal">(optional)</span></FormLabel>
                                    <FormControl><Textarea placeholder="e.g. Focus on async Python and distributed systems…" rows={3} className="bg-background resize-none" {...field} /></FormControl>
                                    <FormMessage />
                                </FormItem>
                            )} />
                        </CardContent>
                    </Card>
 
                    <div className="flex items-center gap-3 pb-8">
                        <Button type="submit" variant="outline" disabled={submitting} className="font-mono text-[12px]">Save as Draft</Button>
                        <Button type="button" disabled={submitting} className="font-mono text-[12px]" onClick={form.handleSubmit(v => submit(v, true))}>
                            {submitting ? "Creating…" : "Create & Activate ->"}
                        </Button>
                    </div>
                </form>
            </Form>
        </main>
    )
}