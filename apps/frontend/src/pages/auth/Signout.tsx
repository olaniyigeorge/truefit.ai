import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { useNavigate, useLocation } from "react-router"
import { auth, getFirebaseErrorMessage } from "@/helpers/firebase"
import { createUserWithEmailAndPassword, signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { signUpSchema, type signUpFormValues } from "@/helpers/validations/auth.schemas"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Form, FormField, FormItem, FormLabel, FormControl, FormMassage } from "@components/ui/form"


const googleProvider = new GoogleAuthProvider()


const SignUp = () => {

    const navigate = useNavigate()
    const location = useLocation()

    const from = location.state?.from?.pathname ?? "/"

    const form = useForm<signUpFormValues>({
        resolver: zodResolver(signUpSchema),
        defaultValues: { email: '', password: '', confirmPassword: '' }
    })

    const onSubmit = async (values: signUpFormValues) => {
        try {
            await createUserWithEmailAndPassword(auth, values.email, values.password)
            navigate("/", { replace: true })
        } catch (error: any) {
            form.setError('root', { message: getFirebaseErrorMessage(error.code) })
        }
    }

    const handleGoogleSignIn = async () => {
        try {
            await signInWithPopup(auth, googleProvider)
            navigate("/", { replace: true })
        } catch (error: any) {
            form.setError('root', { message: getFirebaseErrorMessage(error.code) })
        }
    }


    return (
        <div></div>
    )
}

export default SignUp