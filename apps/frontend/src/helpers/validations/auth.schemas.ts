import {z} from "zod"

const emailField = z.string().email('Invalid email address')
const passwordField = z.string().min(8, "Password must be at least 8 characters")

export const signInSchema = z.object({
    email: emailField,
    password: passwordField
})

export const signUpSchema = z.object({
    email: emailField,
    password: passwordField,
    confirmPassword: passwordField
}).refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ['confirmPassword']
})

export type signInFormValues = z.infer<typeof signInSchema>
export type signUpFormValues = z.infer<typeof signUpSchema>