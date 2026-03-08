import {createContext, useContext, useEffect, useState} from "react"
import { onAuthStateChanged, signOut, type User } from "firebase/auth"
import {auth} from "@/firebase" 

//define context data shape
interface AuthContextType {
    user: User | null;
    loading: boolean;
    logout: () => Promise<void>;
}

//create the context with an uninitialized undefined value
export const AuthContext = createContext<AuthContextType | undefined>(undefined)

//provider component
export const AuthProvider = ({children}: {children: React.ReactNode}) => {
    const [user, setUser] = useState<User | null>(null)
    const [loading, setLoading] = useState<boolean>(true)


    useEffect(() => {
        const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
            setUser(currentUser)
            setLoading(false)
        })

        return () => unsubscribe()

    }, [])


    const logout = () => signOut(auth)

    const value = {
        user,
        loading,
        logout
    }

    return (
        <AuthContext.Provider value={value}>
            {!loading && children}
        </AuthContext.Provider>
    )
}