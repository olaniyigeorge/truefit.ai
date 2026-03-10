import axios from 'axios'

const API = axios.create({
    baseURL: "https://localhost:8000",
    timeout: 10000,
    headers: {
        'Content-Type': "application/json"
    },
    withCredentials: false
})

export default API