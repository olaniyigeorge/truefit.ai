import {type Org} from "@/helpers/api/orgs.api"
import { Building2 } from "lucide-react"


export function OrgHeader({ org }: { org: Org }) {
    return (
        <div className="flex items-start gap-4">
            <div className="h-14 w-14 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
                <Building2 className="h-7 w-7 text-primary" />
            </div>
            <div>
                <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">{org.name}</h1>
                <div className="flex items-center gap-2 mt-1.5">
                    <span className="text-[11px] font-mono text-muted-foreground bg-secondary px-2 py-0.5 rounded border border-border">
                        {org.slug}
                    </span>
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                        org.status === "active"
                            ? "bg-primary/10 text-primary border-primary/20"
                            : "bg-muted text-muted-foreground border-border"
                    }`}>
                        {org.status}
                    </span>
                </div>
            </div>
        </div>
    )
}