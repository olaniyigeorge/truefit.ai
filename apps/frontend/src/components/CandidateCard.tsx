

import { useNavigate } from "react-router"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { MapPin, Briefcase, ChevronRight } from "lucide-react"
import type { Candidate } from "@/helpers/api/candidates.api"

function initials(name: string) {
    return name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase()
}

export function CandidateCard({ candidate }: { candidate: Candidate }) {
    const navigate = useNavigate()

    return (
        <Card
            className="group cursor-pointer hover:border-border/80 transition-all duration-200"
            onClick={() => navigate(`/candidates/${candidate.id}`)}
        >
            <CardContent className="p-5 flex flex-col gap-4">
                {/* Header */}
                <div className="flex items-start gap-3">
                    <Avatar className="h-10 w-10 shrink-0">
                        <AvatarFallback className="bg-primary/10 text-primary text-[12px] font-bold">
                            {initials(candidate.full_name)}
                        </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                        <h3 className="font-serif text-[15px] font-bold text-foreground group-hover:text-primary transition-colors truncate">
                            {candidate.full_name}
                        </h3>
                        {candidate.headline && (
                            <p className="text-[12px] text-muted-foreground truncate mt-0.5">
                                {candidate.headline}
                            </p>
                        )}
                    </div>
                </div>

                {/* Meta */}
                <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                    {candidate.location && (
                        <span className="flex items-center gap-1">
                            <MapPin className="h-3 w-3" />{candidate.location}
                        </span>
                    )}
                    {candidate.contact.linkedin_url && (
                        <span className="flex items-center gap-1">
                            <Briefcase className="h-3 w-3" />LinkedIn
                        </span>
                    )}
                </div>

                {/* Skills */}
                {candidate.skills && candidate.skills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                        {candidate.skills.slice(0, 4).map(s => (
                            <Badge key={s} variant="secondary" className="text-[10px] font-mono px-2 py-0.5">
                                {s}
                            </Badge>
                        ))}
                        {candidate.skills.length > 4 && (
                            <span className="text-[11px] text-muted-foreground/50 font-mono self-center">
                                +{candidate.skills.length - 4}
                            </span>
                        )}
                    </div>
                )}

                {/* Footer */}
                <div className="flex items-center justify-between pt-1 border-t border-border">
                    <span className="text-[11px] text-muted-foreground">
                        {candidate.contact.email}
                    </span>
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/0 group-hover:text-muted-foreground/50 transition-colors" />
                </div>
            </CardContent>
        </Card>
    )
}