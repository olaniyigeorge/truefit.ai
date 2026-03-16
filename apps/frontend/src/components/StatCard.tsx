
import {Card, CardContent} from "@/components/ui/card"


export function StatCard({
    icon: Icon, label, value, sub, accent = false,
}: {
    icon: React.ElementType
    label: string
    value: number | string
    sub?: string
    accent?: boolean
}) {
    return (
        <Card className="relative overflow-hidden">
            <CardContent className="p-6">
                <div className="flex items-start justify-between">
                    <div>
                        <p className="text-[11px] tracking-[0.15em] uppercase text-muted-foreground mb-3">
                            {label}
                        </p>
                        <p className={`font-serif text-4xl font-bold tracking-tight ${accent ? "text-primary" : "text-foreground"}`}>
                            {value}
                        </p>
                        {sub && (
                            <p className="text-[12px] text-muted-foreground mt-1.5">{sub}</p>
                        )}
                    </div>
                    <div className={`p-2.5 rounded-lg ${accent ? "bg-primary/10" : "bg-secondary"}`}>
                        <Icon className={`h-5 w-5 ${accent ? "text-primary" : "text-muted-foreground"}`} />
                    </div>
                </div>
                {accent && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-primary/60 to-primary/20" />
                )}
            </CardContent>
        </Card>
    )
}