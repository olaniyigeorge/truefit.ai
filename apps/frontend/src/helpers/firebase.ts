import {initializeApp} from "firebase/app"
import {getAuth} from "firebase/auth"



const firebaseConfig = {
    apiKey: "api_key",
    authDomain: "auth_domain",
    projectId: "project_id"
}


const app = initializeApp(firebaseConfig)


export const auth = getAuth(app)

export const getFirebaseErrorMessage = (code: string): string => {
    switch (code) {
        case 'auth/email-already-in-use':
            return "An account with this email already exists"
        case "auth/invalid-email":
            return "Invalid email address"
        case "auth/weak-password":
            return "Password is too weak"
        case "auth/user-not-found":
            return "No account found with this email"
        case "auth/wrong-password":
            return "Incorrect password"
        case "auth/too-many-requests":
            return "Too many attempts. Please try again later."
        case "auth/popup-closed-by-user":
            return "Sign in was cancelled"
        default:
            return "Something went wrong. Please try again."
    }
}
