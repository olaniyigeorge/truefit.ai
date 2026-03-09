const config = {
    firebaseApiKey: import.meta.env.VITE_FIREBASE_API_KEY || "",
    firebaseAuthDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    firebaseProjectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    publicUrl: import.meta.env.VITE_PUBLIC_URL || "",
    firebaseStorageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
    firebaseMessagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
    firebaseAppId: import.meta.env.VITE_FIREBASE_APP_ID,
    wsUrl: import.meta.env.VITE_PUBLIC_WS_URL || "",
    env: import.meta.env.NODE_ENV || "development",
    dev: import.meta.env.DEV
}

export default config