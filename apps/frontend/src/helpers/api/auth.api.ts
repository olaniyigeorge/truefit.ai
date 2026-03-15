import API from "@/helpers/api"
import type{User} from "firebase/auth"

export const createSession = async (firebaseUser: User): Promise<void> => {
    const idToken = await firebaseUser.getIdToken()
    const response =  await API.post('/api/v1/auth/oauth/token',{
        token: idToken,
        provider: 'firebase'
    })
    const {access_token} = response.data
    document.cookie = `jwt=${access_token}; path=/; SameSite=Strict`
};