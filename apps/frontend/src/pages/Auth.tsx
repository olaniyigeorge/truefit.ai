import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { useNavigate, useLocation } from "react-router"
import { auth, getFirebaseErrorMessage } from "@/helpers/firebase"
import { sendSignInLinkToEmail, signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { authSchema, type authFormValues } from "@/helpers/validations/auth.schemas"
import { createSession } from "@/helpers/api/auth.api"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"


const googleProvider = new GoogleAuthProvider();

const AuthPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname ?? '/dashboard';

  const form = useForm<authFormValues>({
    resolver: zodResolver(authSchema),
    defaultValues: { email: ''},
  });

  const actionCodeSettings = {
    // URL you want to redirect back to. The domain (www.example.com) for this
    // URL must be in the authorized domains list in the Firebase Console.
    url: `${window.location.origin}/verify`,
    // This must be true.
    handleCodeInApp: true,
  };

  const onSubmit = async (values: authFormValues) => {
    try {
      await sendSignInLinkToEmail(auth, values.email, actionCodeSettings);
      // navigate(from, { replace: true });
      localStorage.setItem('emailForSignIn', values.email)
      navigate("/verify")
    } catch (error: any) {
      form.setError('root', { message: getFirebaseErrorMessage(error.code) });
    }
  };

  const handleGoogleSignIn = async () => {
    try {
      await signInWithPopup(auth, googleProvider);
      // TODO: get the idToken for the result and hit the backend with it (probably in createSession)
      // TODO: use the auth/oauth/token endpoint to exchange the idToken for a JWT from our backend, then store that JWT in cookies for subsequent requests.
      await createSession()
      navigate(from, { replace: true });
    } catch (error: any) {
      form.setError('root', { message: getFirebaseErrorMessage(error.code) });
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-md space-y-6 p-8">
        <h1 className="text-2xl font-bold">Sign In</h1>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" placeholder="you@example.com" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />


            {form.formState.errors.root && (
              <p className="text-sm text-destructive">{form.formState.errors.root.message}</p>
            )}

            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? 'Getting Link...' : 'Get Link'}
            </Button>
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

        <Button variant="outline" className="w-full text-red-600 hover:text-white" onClick={handleGoogleSignIn}>
          Continue with Google
        </Button>

        <p className="text-center text-sm text-muted-foreground">
          Don't have an account?{' '}
          <a href="/signup" className="text-primary underline">Sign up</a>
        </p>
      </div>
    </div>
  );
};

export default AuthPage