import { useState } from "react"
import { type Candidate } from "@/helpers/api/candidates.api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "./ui/button"
import { FileText, Upload, Trash2 } from "lucide-react"



export function ResumeCard({
    candidate, onUpload, onDelete,
}: {
    candidate: Candidate
    onUpload: (file: File) => Promise<void>
    onDelete: () => Promise<void>
}) {
    const [uploading, setUploading] = useState(false)

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return
        setUploading(true)
        await onUpload(file)
        setUploading(false)
    }

    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" /> Resume
                </CardTitle>
            </CardHeader>
            <CardContent>
                {candidate.resume ? (
                    <div className="flex items-center justify-between p-3 bg-secondary rounded-lg">
                        <div className="min-w-0">
                            <p className="text-[13px] font-medium text-foreground truncate">{candidate.resume.filename}</p>
                            <p className="text-[11px] text-muted-foreground mt-0.5">
                                Uploaded {new Date(candidate.resume.uploaded_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                            </p>
                        </div>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                            onClick={onDelete}
                        >
                            <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                    </div>
                ) : (
                    <label className="flex flex-col items-center justify-center gap-3 p-6 border-2 border-dashed border-border rounded-lg cursor-pointer hover:border-primary/40 hover:bg-primary/5 transition-colors">
                        <Upload className="h-6 w-6 text-muted-foreground" />
                        <div className="text-center">
                            <p className="text-[13px] font-medium text-foreground">
                                {uploading ? "Uploading…" : "Upload Resume"}
                            </p>
                            <p className="text-[11px] text-muted-foreground mt-0.5">PDF or Word, max 10MB</p>
                        </div>
                        <input type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={handleFileChange} disabled={uploading} />
                    </label>
                )}
            </CardContent>
        </Card>
    )
}