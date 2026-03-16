import { createContext, useEffect, useState, useCallback } from "react"
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
    refreshBackendUser: () => void
}

//create the context with an uninitialized undefined value
export const AuthContext = createContext<AuthContextType | undefined>(undefined)

//provider component
export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null)
    const [backendUser, setBackendUser] = useState<BackendUser | null>(null)
    const [loading, setLoading] = useState<boolean>(true)

    const hydrateFromCookie = useCallback(() => {
        const match = document.cookie.match(/(?:^|;\s*)jwt=([^;]*)/)
        if (!match) return
        const token = match[1]
        try {
            const payload = JSON.parse(atob(token.split(".")[1]))
            setBackendUser({
                id:           payload.sub,
                email:        payload.email,
                display_name: null,
                role:         payload.role,
                org_id:       payload.org_id ?? null,
                is_active:    true,
            })
        } catch(_){
            // malformed token
        }
    }, [])


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

    useEffect(() => {
        hydrateFromCookie()
    }, [user, hydrateFromCookie])

    const logout = async () => {
        document.cookie = "jwt=; path=/; max-age=0"
        setBackendUser(null)
        await signOut(auth)
    }

    const value = {
        user,
        backendUser,
        loading,
        logout,
        refreshBackendUser: hydrateFromCookie
    }

    return (
        <AuthContext.Provider value={value}>
            {!loading && children}
        </AuthContext.Provider>
    )
}