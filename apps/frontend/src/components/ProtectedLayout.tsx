import { Outlet } from "react-router"
import { SidebarProvider } from "./ui/sidebar"
import AppSidebar from "./AppSidebar"


export const ProtectedLayout = () => {



    return (
        <SidebarProvider>
            <AppSidebar />
            <Outlet />
        </SidebarProvider>
    )
}

