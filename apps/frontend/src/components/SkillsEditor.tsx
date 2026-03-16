
import { useState } from "react"
import type { JobSkill } from "@/helpers/api/jobs.api"
import { Input } from "./ui/input"
import { Button } from "./ui/button"
import {Plus, X} from "lucide-react"



export function SkillsEditor({
    skills,
    onChange,
}: {
    skills: JobSkill[]
    onChange: (skills: JobSkill[]) => void
}) {
    const [nameInput, setNameInput] = useState("")
    const [yearsInput, setYearsInput] = useState("")
    const [required, setRequired] = useState(true)
 
    const add = () => {
        if (!nameInput.trim()) return
        if (skills.some(s => s.name.toLowerCase() === nameInput.trim().toLowerCase())) return
        onChange([
            ...skills,
            {
                name: nameInput.trim(),
                required,
                weight: required ? 1.0 : 0.5,
                min_years: yearsInput ? parseInt(yearsInput) : null,
            },
        ])
        setNameInput("")
        setYearsInput("")
    }
 
    const remove = (name: string) => onChange(skills.filter(s => s.name !== name))
 
    return (
        <div className="space-y-3">
            <div className="flex gap-2">
                <Input
                    placeholder="Skill name"
                    value={nameInput}
                    onChange={e => setNameInput(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && (e.preventDefault(), add())}
                    className="bg-background flex-1"
                />
                <Input
                    placeholder="Min yrs"
                    value={yearsInput}
                    onChange={e => setYearsInput(e.target.value)}
                    type="number"
                    min={0}
                    className="bg-background w-24"
                />
                <button
                    type="button"
                    onClick={() => setRequired(r => !r)}
                    className={`px-3 py-2 rounded text-[11px] font-mono border transition-colors ${
                        required
                            ? "bg-primary/10 text-primary border-primary/20"
                            : "bg-secondary text-muted-foreground border-border"
                    }`}
                >
                    {required ? "Required" : "Preferred"}
                </button>
                <Button type="button" size="icon" onClick={add} variant="outline">
                    <Plus className="h-4 w-4" />
                </Button>
            </div>
 
            {skills.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {skills.map(s => (
                        <div
                            key={s.name}
                            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-sm border text-[12px] font-mono ${
                                s.required
                                    ? "bg-primary/5 border-primary/15 text-foreground"
                                    : "bg-secondary border-border text-muted-foreground"
                            }`}
                        >
                            {s.name}
                            {s.min_years ? <span className="text-[10px] text-muted-foreground">{s.min_years}y+</span> : null}
                            <button type="button" onClick={() => remove(s.name)} className="ml-0.5 hover:text-destructive transition-colors">
                                <X className="h-3 w-3" />
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}