import API from "@/helpers/api"
import type{User} from "firebase/auth"

export type SessionResult = {
    is_new_user: boolean
    role: string
}

export const createSession = async (firebaseUser: User): Promise<SessionResult> => {
    const idToken = await firebaseUser.getIdToken()
    console.log("\nCreating session with Firebase ID token:", idToken, "\n")
    const response =  await API.post('/api/v1/auth/oauth/token',{
        token: idToken,
        provider: 'firebase'
    })
    const {access_token, is_new_user, user} = response.data
    document.cookie = `jwt=${access_token}; path=/; SameSite=Strict`
    return {is_new_user, role: user.role}
};

export const refreshSession = async (): Promise<void> => {
    try {
        const res = await API.post('/api/v1/auth/refresh')
        const { access_token } = res.data
        document.cookie = `jwt=${access_token}; path=/; SameSite=Strict`
    } catch (e: any) {
        console.error("Refresh failed:", e?.response?.data)
        throw e
    }
}