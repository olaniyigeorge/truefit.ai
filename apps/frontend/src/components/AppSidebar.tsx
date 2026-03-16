import {
    Sidebar, 
    SidebarContent, 
    SidebarFooter, 
    SidebarHeader, 
    SidebarGroup,
    SidebarGroupLabel,
    SidebarMenuButton,
    SidebarMenu,
    SidebarMenuItem} from "@/components/ui/sidebar";
import CustomTrigger from "@/components/CustomTrigger";     
import { useAuthContext } from "@/hooks/useAuthContext";
import {Button} from "@/components/ui/button"
import {Avatar, AvatarFallback} from "@/components/ui/avatar"
import {
    LayoutDashboard,
    Briefcase,
    Users,
    FileText,
    Building2,
    LogOut,
    List,
    UserCircle,
} from "lucide-react"
import { NavLink } from "react-router";



const recruiterNav = [
    {label: "Dashboard", to: "/dashboard", icon: LayoutDashboard},
    {label: "Jobs", to: "/jobs", icon: Briefcase},
    {label: "Candidates", to: "/candidates", icon: Users},
    {label: "Applications", to: "/applications", icon: FileText},
    {label: "Organisation", to: "/org", icon: Building2},
]

const candidateNav = [
    {label: "Dashboard", to: "/dashboard", icon: LayoutDashboard},
    {label: "Browse Jobs", to: "/listings",    icon: List }, 
    {label: "Applications", to: "/applications", icon: FileText},
    {label: "Profile", to: "/profile", icon: UserCircle},
]



const AppSidebar = () => {
    const {backendUser, logout} = useAuthContext()

    const isRecruiter = backendUser?.role === "recruiter" || backendUser?.role === "admin"
    const navItems = isRecruiter ? recruiterNav : candidateNav


    const initials = backendUser?.email ? backendUser.email.slice(0, 2).toUpperCase() : "?" 



    return(
        <Sidebar collapsible="icon" variant="inset">
            <CustomTrigger />
            <SidebarHeader className="pt-10 pb-4 px-4">
                <div className="flex items-center gap-2.5">
                    <span className="font-serif text-base font-bold">
                        True<span className="text-primary">Fit</span>.ai
                    </span>
                </div>
            </SidebarHeader>
            <SidebarContent>
                <SidebarGroup>
                    <SidebarGroupLabel className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground/50">
                        {isRecruiter ? "Recruiter" : "Candidate"}
                    </SidebarGroupLabel>
                    <SidebarMenu>
                        {navItems.map(({ label, to, icon: Icon }) => (
                            <SidebarMenuItem key={to}>
                                <SidebarMenuButton asChild tooltip={label}>
                                    <NavLink
                                        to={to}
                                        className={({ isActive }) =>
                                            isActive ? "text-primary" : "text-muted-foreground"
                                        }
                                    >
                                        <Icon className="h-4 w-4" />
                                        <span>{label}</span>
                                    </NavLink>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                        ))}
                    </SidebarMenu>
                </SidebarGroup>
            </SidebarContent>
            <SidebarFooter className="p-4 border-t border-border">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5 min-w-0">
                        <Avatar className="h-7 w-7 shrink-0">
                            <AvatarFallback className="bg-primary/10 text-primary text-[11px] font-bold">
                                {initials}
                            </AvatarFallback>
                        </Avatar>
                        <div className="min-w-0">
                            <p className="text-[12px] font-medium text-foreground truncate">
                                {backendUser?.email ?? "—"}
                            </p>
                            <p className="text-[10px] text-muted-foreground capitalize">
                                {backendUser?.role ?? "—"}
                            </p>
                        </div>
                    </div>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                        onClick={logout}
                    >
                        <LogOut className="h-3.5 w-3.5" />
                    </Button>
                </div>
            </SidebarFooter>
        </Sidebar>
    )
}

export default AppSidebar