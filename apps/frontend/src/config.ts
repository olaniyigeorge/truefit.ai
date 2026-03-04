const config = {
    firebaseApiKey: import.meta.env.VITE_FIREBASE_API_KEY || "",
    firebaseAuthDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    firebaseProjectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    publicUrl: import.meta.env.VITE_PUBLIC_URL || "",
    wsUrl: import.meta.env.VITE_PUBLIC_WS_URL || "",
    env: import.meta.env.NODE_ENV || "development"
}

export default config