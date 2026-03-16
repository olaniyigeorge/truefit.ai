import { useState } from "react";
import {type Org, type UpdateOrgPayload } from "@/helpers/api/orgs.api";
import {
    Form, FormField, FormItem, FormLabel, FormControl, FormMessage,
} from "@/components/ui/form"
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { zodResolver } from "@hookform/resolvers/zod"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "./ui/button";
import { Check, X } from "lucide-react";




const schema = z.object({
    name:        z.string().min(2, "Name is required"),
    description: z.string().optional(),
    industry:    z.string().optional(),
    headcount:   z.enum(["1-10", "11-50", "51-200", "200+"]).optional(),
    contact_email:   z.string().email("Invalid email"),
    contact_phone:   z.string().optional(),
    contact_website: z.string().optional(),
})


type FormValues = z.infer<typeof schema>





export function EditForm({ org, onSave, onCancel }: { org: Org; onSave: (data: UpdateOrgPayload) => Promise<void>; onCancel: () => void }) {
    const [saving, setSaving] = useState(false)

    const form = useForm<FormValues>({
        resolver: zodResolver(schema),
        defaultValues: {
            name:            org.name,
            description:     org.description ?? "",
            industry:        org.industry ?? "",
            headcount:       org.headcount ?? undefined,
            contact_email:   org.contact.email,
            contact_phone:   org.contact.phone ?? "",
            contact_website: org.contact.website ?? "",
        },
    })

    const handleSubmit = async (values: FormValues) => {
        setSaving(true)
        await onSave({
            name:        values.name,
            description: values.description || undefined,
            industry:    values.industry || undefined,
            headcount:   values.headcount,
            contact: {
                email:   values.contact_email,
                phone:   values.contact_phone || undefined,
                website: values.contact_website || undefined,
            },
        })
        setSaving(false)
    }

    return (
        <Form {...form}>
            <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-5">
                <div className="grid sm:grid-cols-2 gap-5">
                    <FormField control={form.control} name="name" render={({ field }) => (
                        <FormItem>
                            <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Name</FormLabel>
                            <FormControl><Input className="bg-background" {...field} /></FormControl>
                            <FormMessage />
                        </FormItem>
                    )} />
                    <FormField control={form.control} name="industry" render={({ field }) => (
                        <FormItem>
                            <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Industry</FormLabel>
                            <FormControl><Input placeholder="e.g. Technology" className="bg-background" {...field} /></FormControl>
                            <FormMessage />
                        </FormItem>
                    )} />
                    <FormField control={form.control} name="headcount" render={({ field }) => (
                        <FormItem>
                            <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Headcount</FormLabel>
                            <Select onValueChange={field.onChange} defaultValue={field.value}>
                                <FormControl>
                                    <SelectTrigger className="bg-background"><SelectValue placeholder="Select…" /></SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                    {["1-10", "11-50", "51-200", "200+"].map(v => (
                                        <SelectItem key={v} value={v}>{v}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <FormMessage />
                        </FormItem>
                    )} />
                    <FormField control={form.control} name="contact_email" render={({ field }) => (
                        <FormItem>
                            <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Contact Email</FormLabel>
                            <FormControl><Input type="email" className="bg-background" {...field} /></FormControl>
                            <FormMessage />
                        </FormItem>
                    )} />
                    <FormField control={form.control} name="contact_phone" render={({ field }) => (
                        <FormItem>
                            <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Phone</FormLabel>
                            <FormControl><Input placeholder="+1 555 000 0000" className="bg-background" {...field} /></FormControl>
                            <FormMessage />
                        </FormItem>
                    )} />
                    <FormField control={form.control} name="contact_website" render={({ field }) => (
                        <FormItem>
                            <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Website</FormLabel>
                            <FormControl><Input placeholder="https://…" className="bg-background" {...field} /></FormControl>
                            <FormMessage />
                        </FormItem>
                    )} />
                </div>
                <FormField control={form.control} name="description" render={({ field }) => (
                    <FormItem>
                        <FormLabel className="text-[11px] tracking-[0.1em] uppercase text-muted-foreground">Description</FormLabel>
                        <FormControl><Textarea rows={4} className="bg-background resize-none" {...field} /></FormControl>
                        <FormMessage />
                    </FormItem>
                )} />
                <div className="flex gap-2">
                    <Button type="submit" disabled={saving} size="sm" className="font-mono text-[12px] gap-1.5">
                        <Check className="h-3.5 w-3.5" />{saving ? "Saving…" : "Save Changes"}
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="font-mono text-[12px] gap-1.5">
                        <X className="h-3.5 w-3.5" />Cancel
                    </Button>
                </div>
            </form>
        </Form>
    )
}