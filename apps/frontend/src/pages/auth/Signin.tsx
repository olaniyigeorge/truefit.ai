import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { useNavigate, useLocation } from "react-router"
import { auth, getFirebaseErrorMessage } from "@/helpers/firebase"
import { signInWithEmailAndPassword, signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { signInSchema, type signInFormValues } from "@/helpers/validations/auth.schemas"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Form, FormField, FormItem, FormLabel, FormControl, FormMassage } from "@components/ui/form"


const googleProvider = new GoogleAuthProvider()


const SignIn = () => {

    const navigate = useNavigate()
    const location = useLocation()

    const from = location.state?.from?.pathname ?? "/"

    const form = useForm<signInFormValues>({
        resolver: zodResolver(signInSchema),
        defaultValues: { email: '', password: '' }
    })

    const onSubmit = async (values: signInFormValues) => {
        try {
            await signInWithEmailAndPassword(auth, values.email, values.password)
            navigate(from, { replace: true })
        } catch (error: any) {
            form.setError('root', { message: getFirebaseErrorMessage(error.code) })
        }
    }

    const handleGoogleSignIn = async () => {
        try {
            await signInWithPopup(auth, googleProvider)
            navigate(from, { replace: true })
        } catch (error: any) {
            form.setError('root', { message: getFirebaseErrorMessage(error.code) })
        }
    }


    return (
        <div></div>
    )
}

export default SignIn