import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { useNavigate, useLocation } from "react-router"
import { auth, getFirebaseErrorMessage } from "@/helpers/firebase"
import { sendSignInLinkToEmail, signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { authSchema, type authFormValues } from "@/helpers/validations/auth.schemas"
import {Spiral} from "@/components/Spiral"
import {GoogleIcon} from "@/components/GoogleIcon"
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
      const result = await signInWithPopup(auth, googleProvider);
      // const idToken = await result.user.getIdToken()
      // console.log('firebase idToken', idToken)
      // TODO: get the idToken for the result and hit the backend with it (probably in createSession)
      // TODO: use the auth/oauth/token endpoint to exchange the idToken for a JWT from our backend, then store that JWT in cookies for subsequent requests.
      const {is_new_user} = await createSession(result.user)
      await createSession(result.user)
      navigate(is_new_user ? '/onboarding' : from, { replace: true });
    } catch (error: any) {
      form.setError('root', { message: getFirebaseErrorMessage(error.code) });
    }
  };

  return (
    <div className="relative min-h-screen bg-background flex items-center justify-center p-6 overflow-hidden">
      {/* Background overlays */}
      <div className="overlay-noise" />
      <div className="overlay-grid" />
 
      {/* Radial glow */}
      <div
        className="fixed pointer-events-none"
        style={{
          top: "40%", left: "50%", transform: "translate(-50%, -50%)",
          width: 500, height: 500, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(34,197,94,0.06) 0%, transparent 70%)",
        }}
      />
 
      {/* Back link */}
      <a
        href="/"
        className="fixed top-5 left-6 z-10 text-[11px] tracking-wide text-muted-foreground hover:text-foreground transition-colors"
      >
        ← Back
      </a>
 
      {/* Card */}
      <div className="relative z-10 w-full max-w-sm bg-card border border-border rounded-2xl p-10 flex flex-col gap-7">
 
        {/* Logo + heading */}
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="flex items-center gap-2.5">
            <Spiral size={28} />
            <span className="font-serif text-xl font-bold">
              True<span className="text-primary">Fit</span>.ai
            </span>
          </div>
          <div>
            <h1 className="font-serif text-2xl font-bold tracking-tight text-foreground mb-1.5">
              Welcome back
            </h1>
            <p className="text-[12px] text-muted-foreground leading-relaxed">
              Sign in to continue to your dashboard
            </p>
          </div>
        </div>
 
        {/* Google SSO */}
        <Button
          variant="outline"
          className="w-full gap-2.5 border-border bg-transparent text-foreground hover:bg-accent hover:text-foreground"
          onClick={handleGoogleSignIn}
          type="button"
        >
          <GoogleIcon />
          Continue with Google
        </Button>
 
        {/* Divider */}
        <div className="flex items-center gap-3">
          <div className="flex-1 h-px bg-border" />
          <span className="text-[11px] text-muted-foreground tracking-widest">OR</span>
          <div className="flex-1 h-px bg-border" />
        </div>
 
        {/* Email magic link form */}
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-[11px] uppercase tracking-widest text-muted-foreground">
                    Email
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="you@example.com"
                      className="bg-background border-border text-foreground placeholder:text-accent-foreground/30 focus-visible:ring-primary/25 focus-visible:border-primary/40"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-destructive text-[11px]" />
                </FormItem>
              )}
            />
 
            {form.formState.errors.root && (
              <div className="px-3.5 py-2.5 bg-destructive/5 border border-destructive/20 rounded-lg text-[12px] text-destructive">
                {form.formState.errors.root.message}
              </div>
            )}
 
            <Button
              type="submit"
              className="w-full bg-primary text-primary-foreground font-bold tracking-wide hover:brightness-110 transition-all"
              disabled={form.formState.isSubmitting}
            >
              {form.formState.isSubmitting ? "Sending link…" : "Get Magic Link →"}
            </Button>
          </form>
        </Form>
 
        {/* Footer note */}
        <p className="text-[11px] text-muted-foreground text-center leading-relaxed">
          We'll email you a secure sign-in link.
          <br />No password required.
        </p>
      </div>
    </div>
  );
};

export default AuthPage