import { createContext, useEffect, useState } from "react"
import { onAuthStateChanged, signOut, type User } from "firebase/auth"
import { auth } from "@/helpers/firebase"

//define context data shape


export type BackendUser = {
    id: string
    email: string
    display_name: string | null
    role: "candidate" | "recruiter" | "admin"
    org_id: string | null
    is_active: boolean
}


interface AuthContextType {
    user: User | null;
    backendUser: BackendUser | null
    loading: boolean;
    logout: () => Promise<void>;
}

//create the context with an uninitialized undefined value
export const AuthContext = createContext<AuthContextType | undefined>(undefined)

//provider component
export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null)
    const [backendUser, setBackendUser] = useState<BackendUser | null>(null)
    const [loading, setLoading] = useState<boolean>(true)


    useEffect(() => {
        const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
            setUser(currentUser)
            if(!currentUser){
                setBackendUser(null)
            }
            setLoading(false)
        })

        return () => unsubscribe()

    }, [])

    useEffect (() => {
        const match = document.cookie.match(/(?:^|;\s*)jwt=([^;]*)/)
        if(!match) return
            try{
                const payload = JSON.parse(atob(match[1].split(".")[1]))
                setBackendUser({
                    id: payload.sub,
                    email: payload.email,
                    display_name: null,
                    role: payload.role,
                    org_id: payload.org_id ?? null,
                    is_active: true
                })
            }catch(err) {

            }
    }, [user])
    const logout = async () => {
        document.cookie = "jwt=; path=/; max-age=0"
        setBackendUser(null)
        await signOut(auth)
    }

    const value = {
        user,
        backendUser,
        loading,
        logout
    }

    return (
        <AuthContext.Provider value={value}>
            {!loading && children}
        </AuthContext.Provider>
    )
}