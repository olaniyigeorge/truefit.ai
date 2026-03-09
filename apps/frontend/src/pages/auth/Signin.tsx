import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { useNavigate, useLocation, Link } from "react-router"
import { auth, getFirebaseErrorMessage } from "@/helpers/firebase"
import { signInWithEmailAndPassword, signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { signInSchema, type signInFormValues } from "@/helpers/validations/auth.schemas"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"


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
        <div className="flex min-h-screen items-center justify-center">
            <div className="w-full max-w-md space-y-6 p-8">
                <h1 className="text-2xl font-bold">Sign In </h1>

                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                        <FormField 
                        control={form.control}
                        name="email"
                        render={({ field}) => (
                            <FormItem>
                                <FormLabel>Email</FormLabel>
                                <FormControl>
                                    <Input type="email" placeholder="Email" {...field} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                        />

                        <FormField 
                        control={form.control}
                        name="password"
                        render={({ field}) => (
                            <FormItem>
                                <FormLabel>Password</FormLabel>
                                <FormControl>
                                    <Input type="password" placeholder="Password" {...field} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                        />


                        {form.formState.errors.root && (
                            <p className="text-sm text-destructive">{form.formState.errors.root.message}</p>
                        )}
                        <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? 'Signing In...' : 'Sign In'}</Button>
                    </form>
                </Form>

                <div className="relative">
                <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t" />
                </div>
                <div className="relative flex justify-center text-sm">
                    <span className="bg-background px-2 text-muted-foreground">or</span>
                </div>
                </div>

                <Button variant="outline" className="w-full text-red-400 hover:text-white" onClick={handleGoogleSignIn}>
                    Continue with Google
                </Button>

                <p>
                    Don't have an account?{' '}
                    <Link to="/signup" className="text-primary hover:underline">
                        Sign Up
                    </Link>
                </p>
            </div>
        </div>
    )
}

export default SignIn