import {initializeApp} from "firebase/app"
import {getAuth} from "firebase/auth"
import config from "@/config"


const firebaseConfig = {
  apiKey: config.firebaseApiKey,
  authDomain: config.firebaseAuthDomain,
  projectId: config.firebaseProjectId,
  storageBucket: config.firebaseStorageBucket,
  messagingSenderId: config.firebaseMessagingSenderId,
  appId: config.firebaseAppId
};


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
