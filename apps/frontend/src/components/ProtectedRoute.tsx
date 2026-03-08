import { Navigate, Outlet, useLocation } from "react-router";
import {useAuthContext} from "@/hooks/useAuthContext"



export default function ProtectedRoute () {

    const {user, loading} = useAuthContext()
    const location = useLocation()

    if(loading) return <span>Loading ...</span>

    if(!user){
        return <Navigate to="/login" state={{from: location}} replace />
    }
    
    return <Outlet />
}
