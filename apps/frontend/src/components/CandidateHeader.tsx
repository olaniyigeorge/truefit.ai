import { type Candidate } from "@/helpers/api/candidates.api"
import { Avatar, AvatarFallback } from "./ui/avatar"
import {MapPin, Mail, Phone, Linkedin} from "lucide-react"


export function CandidateHeader({ candidate }: { candidate: Candidate }) {
    const initials = candidate.full_name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase()

    return (
        <div className="flex items-start gap-5">
            <Avatar className="h-16 w-16 shrink-0">
                <AvatarFallback className="bg-primary/10 text-primary text-lg font-bold">
                    {initials}
                </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
                <h1 className="font-serif text-3xl font-bold text-foreground tracking-tight">
                    {candidate.full_name}
                </h1>
                {candidate.headline && (
                    <p className="text-[14px] text-muted-foreground mt-1">{candidate.headline}</p>
                )}
                <div className="flex flex-wrap gap-3 mt-2.5 text-[12px] text-muted-foreground">
                    {candidate.location && (
                        <span className="flex items-center gap-1.5">
                            <MapPin className="h-3.5 w-3.5" />{candidate.location}
                        </span>
                    )}
                    <span className="flex items-center gap-1.5">
                        <Mail className="h-3.5 w-3.5" />{candidate.contact.email}
                    </span>
                    {candidate.contact.phone && (
                        <span className="flex items-center gap-1.5">
                            <Phone className="h-3.5 w-3.5" />{candidate.contact.phone}
                        </span>
                    )}
                    {candidate.contact.linkedin_url && (
                        <a
                            href={candidate.contact.linkedin_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1.5 hover:text-primary transition-colors"
                        >
                            <Linkedin className="h-3.5 w-3.5" />LinkedIn
                        </a>
                    )}
                </div>
            </div>
        </div>
    )
}