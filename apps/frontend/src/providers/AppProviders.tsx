
import { BrowserRouter as Router } from "react-router"
import { SidebarProvider} from "@/components/ui/sidebar"
import AppSidebar from "@/components/AppSidebar"
import {AuthProvider} from "@/context/authContext"



type AppProviderProp = {
    children: React.ReactNode
}


const AppProviders = ({ children }: AppProviderProp) => {
    return (
        <AuthProvider>
        <Router>
            <SidebarProvider>
                {/* <AppSidebar /> */}
                <main>
                    {children}
                </main>
            </SidebarProvider>
        </Router>
        </AuthProvider>
    )
}


export default AppProviders