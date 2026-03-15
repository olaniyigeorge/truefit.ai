import API from "@/helpers/api"

export type UserRole = "candidate" | "recruiter" | "admin"


export type User = {
    id: string,
    email: string,
    display_name: string | null
    role: UserRole
    org_id: string | null
    isActive: boolean
    created_at: string
    updated_at: string
}


export type CreateUserPayload = {
    email: string,
    display_name: string | null
    auth_provider: string
    provider_subject: string
    account_type: "candidate"| "org"
}

export type UpdateUserPayload = {
    display_name?: string
    is_active?: boolean
}



export const usersApi = {
    getById: async (userId: string): Promise<User> => {
        const res = await API.get(`/api/v1/users/${userId}`)
        return res.data
    },

    getByEmail: async(email: string): Promise<User> => {
        const res = await API.get(`/api/v1/users/by-email/${email}`)
        return res.data
    },

    update: async (userId: string, payload: UpdateUserPayload): Promise<User> => {
        const res = await API.patch(`/api/v1/users/${userId}`, payload)
        return res.data
    },

    joinOrg: async(userId: string, orgId: string): Promise<User> => {
        const res = await API.post(`/api/v1/users/${userId}/join-org`, {org_id: orgId})
        return res.data
    }
}