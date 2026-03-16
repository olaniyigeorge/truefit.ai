import { type Application } from "@/helpers/api/applications.api"
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card"
import { FileText } from "lucide-react"




const APP_STATUS_STYLES: Record<Application["status"], string> = {
    new:          "bg-blue-500/10 text-blue-400 border-blue-500/20",
    interviewing: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    shortlisted:  "bg-primary/10 text-primary border-primary/20",
    rejected:     "bg-destructive/10 text-destructive border-destructive/20",
    hired:        "bg-primary/20 text-primary border-primary/30",
}

export function ApplicationsCard({ applications }: { applications: Application[] }) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="font-serif text-base font-bold flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    Applications
                    <span className="text-[12px] font-mono text-muted-foreground">({applications.length})</span>
                </CardTitle>
            </CardHeader>
            <CardContent>
                {applications.length === 0 ? (
                    <p className="text-[13px] text-muted-foreground text-center py-4">No applications yet</p>
                ) : (
                    <div className="space-y-1">
                        {applications.map(app => (
                            <div key={app.id} className="flex items-center justify-between p-3 rounded-lg hover:bg-secondary transition-colors">
                                <span className="text-[12px] font-mono text-muted-foreground">
                                    {app.job_id.slice(0, 8)}…
                                </span>
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[10px] font-mono tracking-wide border ${APP_STATUS_STYLES[app.status]}`}>
                                    {app.status}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}