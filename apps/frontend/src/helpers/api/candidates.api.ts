import API from "@/helpers/api"


export type CandidateStatus = "active" | "inactive" | "interviewing"

export type CandidateContact = {
    email: string
    phone: string | null
    linkedin_url: string | null
}

export type CandidateResume = {
    storage_key: string
    filename: string
    content_type: string
    uploaded_at: string
}


export type Candidate = {
    id: string
    user_id: string
    full_name: string
    headline: string
    bio: string | null
    location: string | null
    skills: string[] | null
    contact: CandidateContact
    status: CandidateStatus
    resume: CandidateResume | null
    created_at: string
    updated_at: string
}


export type RegisterCandidatePayload = {
    full_name: string
    email: string
    phone?: string
    linkedin_url?: string
}


export type UpdateCandidatePayload = {
    full_name?: string
    phone?: string
    linkedin_url?: string
}

export type ListCandidateParams = {
    limit?: number
    offset?: number
}


export const candidatesApi = {
    register: async (payload: RegisterCandidatePayload): Promise<Candidate> => {
        const res = await API.post(`/api/v1/candidates`, payload)
        return res.data
    },
    getById: async (candidateId: string): Promise<Candidate> => {
        const res = await API.get(`/api/v1/candidates/${candidateId}`)
        return res.data
    },
    list: async (params?: ListCandidateParams): Promise<Candidate[]> => {
        const res = await API.get(`/api/v1/candidates`, {params})
        return res.data
    },
    update: async (candidateId: string, payload: UpdateCandidatePayload): Promise<Candidate> => {
        const res = await API.patch(`/api/v1/candidates/${candidateId}`, payload)
        return res.data
    },
    getResumeUrl: async (candidateId: string): Promise<{url: string}> => {
        const res = await API.get(`/api/v1/candidates/${candidateId}/resume`)
        return res.data
    },
    deleteResume: async (candidateId: string): Promise<void> => {
        await API.delete(`/api/v1/candidates/${candidateId}/resume`)
    },
}