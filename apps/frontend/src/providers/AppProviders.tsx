
import { BrowserRouter as Router } from "react-router"
import {AuthProvider} from "@/context/authContext"



type AppProviderProp = {
    children: React.ReactNode
}


const AppProviders = ({ children }: AppProviderProp) => {
    return (
        <AuthProvider>
        <Router>
                <main>
                    {children}
                </main>
        </Router>
        </AuthProvider>
    )
}


export default AppProviders