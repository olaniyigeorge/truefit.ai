import { useState } from "react"
import { type Candidate, type UpdateCandidatePayload } from "@/helpers/api/candidates.api"
import {
    Form, FormField, FormItem, FormLabel, FormControl, FormMessage,
} from "@/components/ui/form"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { zodResolver } from "@hookform/resolvers/zod"
import { Input } from "@/components/ui/input"
import { Button } from "./ui/button"
import { Check, X } from "lucide-react"



const schema = z.object({
    full_name:    z.string().min(2, "Name is required"),
    phone:        z.string().optional(),
    linkedin_url: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

export function EditForm({
    candidate, onSave, onCancel,
}: {
    candidate: Candidate
    onSave: (data: UpdateCandidatePayload) => Promise<void>
    onCancel: () => void
}) {
    const [saving, setSaving] = useState(false)

    const form = useForm<FormValues>({
        resolver: zodResolver(schema),
        defaultValues: {
            full_name:    candidate.full_name,
            phone:        candidate.contact.phone ?? "",
            linkedin_url: candidate.contact.linkedin_url ?? "",
        },
    })

    const handleSubmit = async (values: FormValues) => {
        setSaving(true)
        await onSave({
            full_name:    values.full_name,
            phone:        values.phone || undefined,
            linkedin_url: values.linkedin_url || undefined,
        })
        setSaving(false)
    }

    return (
        <Form {...form}>
            <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
                <FormField control={form.control} name="full_name" render={({ field }) => (
                    <FormItem>
                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Full Name</FormLabel>
                        <FormControl><Input className="bg-background" {...field} /></FormControl>
                        <FormMessage />
                    </FormItem>
                )} />
                <FormField control={form.control} name="phone" render={({ field }) => (
                    <FormItem>
                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Phone</FormLabel>
                        <FormControl><Input placeholder="+1 555 000 0000" className="bg-background" {...field} /></FormControl>
                        <FormMessage />
                    </FormItem>
                )} />
                <FormField control={form.control} name="linkedin_url" render={({ field }) => (
                    <FormItem>
                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">LinkedIn URL</FormLabel>
                        <FormControl><Input placeholder="https://linkedin.com/in/…" className="bg-background" {...field} /></FormControl>
                        <FormMessage />
                    </FormItem>
                )} />
                <div className="flex gap-2 pt-1">
                    <Button type="submit" disabled={saving} size="sm" className="font-mono text-[12px] gap-1.5">
                        <Check className="h-3.5 w-3.5" />{saving ? "Saving…" : "Save"}
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="font-mono text-[12px] gap-1.5">
                        <X className="h-3.5 w-3.5" />Cancel
                    </Button>
                </div>
            </form>
        </Form>
    )
}