import API from "./api"
import {auth} from "@/helpers/firebase"
import {signOut} from "firebase/auth"

const getJwt = (): string | null  => {
    const match = document.cookie.match(/(?:^|;\s*)jwt=([^;]*)/)
    return match ? decodeURIComponent(match[1]) : null
}


API.interceptors.request.use(
    async (config) => {
        //attach token from storage
        const token = getJwt()
        if(token){
            config.headers.authorization = `Bearer ${token}`
        }
        //add correlative ID for tracing
        config.headers['X-Request-ID'] = crypto.randomUUID?.() || Date.now().toString(36)
        return config
    },
    (error) => Promise.reject(error)
)

API.interceptors.response.use(
    (response) => response,
    async (error) => {
        const {response, config} = error
        //basic telementary
        if(import.meta.env.DEV){
            console.warn('API error:', {
                url: config?.url,
                method: config?.method,
                status: response?.status
            })
        }


        //handle expired access token
        if(response?.status === 401){
            document.cookie = 'jwt=; path=/; max-age=0'
            await signOut(auth)
            window.location.href = "/auth"
        }
        return Promise.reject(error)
    }
)