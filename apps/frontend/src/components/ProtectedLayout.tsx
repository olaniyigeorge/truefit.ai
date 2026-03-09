import { Outlet } from "react-router"
import AppSidebar from "./AppSidebar"
import { SidebarProvider } from "./ui/sidebar"


const ProtectedLayout = () => {
    
  return (
    <SidebarProvider>
        <AppSidebar />
        <Outlet />
    </SidebarProvider>
  )
}

export default ProtectedLayout