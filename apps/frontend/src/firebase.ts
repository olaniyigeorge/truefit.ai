import {initializeApp} from "firebase/app"
import {getAuth} from "firebase/auth"



const firebaseConfig = {
    apiKey: "api_key",
    authDomain: "auth_domain",
    projectId: "project_id"
}


const app = initializeApp(firebaseConfig)


export const auth = getAuth(app)


