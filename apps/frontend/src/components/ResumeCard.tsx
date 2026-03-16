import {type Candidate } from "@/helpers/api/candidates.api";
import { Card, CardTitle, CardHeader, CardContent } from "./ui/card";
import { Button } from "./ui/button";
import { Download } from "lucide-react";



export function ResumeCard({ candidate, onDownload }: { candidate: Candidate; onDownload: () => void }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold">Resume</CardTitle>
            </CardHeader>
            <CardContent>
                {candidate.resume ? (
                    <div className="flex items-center justify-between p-3 bg-secondary rounded-lg">
                        <div className="min-w-0">
                            <p className="text-[13px] font-medium text-foreground truncate">{candidate.resume.filename}</p>
                            <p className="text-[11px] text-muted-foreground mt-0.5">
                                {new Date(candidate.resume.uploaded_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                            </p>
                        </div>
                        <Button variant="outline" size="sm" className="shrink-0 gap-1.5 font-mono text-[11px]" onClick={onDownload}>
                            <Download className="h-3.5 w-3.5" /> Download
                        </Button>
                    </div>
                ) : (
                    <p className="text-[13px] text-muted-foreground text-center py-4">No resume uploaded</p>
                )}
            </CardContent>
        </Card>
    )
}