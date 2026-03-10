import { useState, useEffect } from "react"
import { isSignInWithEmailLink, signInWithEmailLink } from "firebase/auth"
import { useNavigate, useLocation } from "react-router"
import {auth, getFirebaseErrorMessage} from "@/helpers/firebase"
import { createSession } from "@/helpers/api/auth.api"
import { Button } from "@/components/ui/button"


const Verification = () => {
    const navigate = useNavigate()
    const location = useLocation()
    const from = location.state?.from?.pathname ?? "/dashboard"
    const [error , setError] = useState<string|null>(null)
    const [isProcessing, setIsProcessing] = useState<boolean>(false)



    useEffect(() => {
        const completeSignIn = async () => {
            if(!isSignInWithEmailLink(auth, window.location.href)) return

            const email = localStorage.getItem('emailForSignIn')
            if(!email){
                setError("Could not find your email. Please sign in again")
                return
            }

            setIsProcessing(true)
            try {
                await signInWithEmailLink(auth, email, window.location.href)
                localStorage.removeItem('emailForSignIn')
                await createSession()
                navigate(from, {replace: true})
            } catch (error: any) {
                setError(getFirebaseErrorMessage(error.code))
            }finally{
                setIsProcessing(false)
            }
        }

        completeSignIn()
    }, [])
    
    //user lands here after submitting email - no link in URL yet
    if(!isSignInWithEmailLink(auth, window.location.href)){
        return (
            <div className="flex min-h-screen items-center justify-center">
                <div className="w-full max-w-md space-y-4 p-8 text-center">
                    <h1 className="text-2xl font-bold">Check your email</h1>
                    <p className="text-muted-foreground">
                        We sent a sign in link to your email. Click the link to continue.
                    </p>
                    <Button variant="outline" onClick={() => navigate('/auth')}>
                        Back to Sign In
                    </Button>
                </div>
            </div>
        );
    }

    //user lands here after clicking the email link
  return (
     <div className="flex min-h-screen items-center justify-center">
            <div className="w-full max-w-md space-y-4 p-8 text-center">
                {isProcessing && <p className="text-muted-foreground">Signing you in...</p>}
                {error && (
                    <div className="space-y-4">
                        <p className="text-sm text-destructive">{error}</p>
                        <Button variant="outline" onClick={() => navigate('/auth')}>
                            Back to Sign In
                        </Button>
                    </div>
                )}
            </div>
        </div>
  )
}

export default Verification