import axios from 'axios'
import config from "@/config"

const API = axios.create({
    baseURL: config.publicApiUrl ?? "http://localhost:8000",
    timeout: 10000,
    headers: {
        'Content-Type': "application/json"
    },
    withCredentials: false
})

export default API