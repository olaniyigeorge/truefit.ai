import {Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarGroup} from "@/components/ui/sidebar";
import CustomTrigger from "@/components/CustomTrigger";     
import { NavLink } from "react-router";

const AppSidebar = () => {
    return(
        <Sidebar collapsible="icon" variant="inset">
            <CustomTrigger />
            <SidebarHeader />
            <SidebarContent>
                <SidebarGroup>

                </SidebarGroup>
            </SidebarContent>
            <SidebarFooter>
            </SidebarFooter>
        </Sidebar>
    )
}

export default AppSidebar