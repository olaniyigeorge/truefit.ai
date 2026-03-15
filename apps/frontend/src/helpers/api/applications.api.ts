import API from "@/helpers/api"


export type ApplicationStatus = "new" | "interviewing" | "shortlisted" | "rejected" | "hired"

export type ApplicationSource = "appliied" | "invited"

export type Application = {
    id: string
    job_id: string
    candidate_id: string
    source: ApplicationSource
    status: ApplicationStatus
    meta: Record<string, unknown>
    created_at: string
    updated_at: string
}


export type CreateApplicationPayload = {
    job_id: string
    candidate_id: string
    source?: ApplicationSource
    meta?: Record<string, unknown>
}



export type UpdateApplicationStatusPayload = {
    status: ApplicationStatus
    meta_updates: Record<string, unknown>
}


export type ListApplicationsParams = {
    job_id?: string
    candidate_id?: string
    status?: ApplicationStatus
    limit?: number
    offset?: number
}

export const applicationsApi = {
    create: async (payload: CreateApplicationPayload): Promise<Application> => {
        const res = await API.post(`/api/v1/applications`, payload)
        return res.data
    },
    getById: async (applicationId: string): Promise<Application> => {
        const res = await API.get(`/api/v1/applications/${applicationId}`)
        return res.data
    },
    list: async (params?: ListApplicationsParams): Promise<Application[]> => {
        const res = await API.get(`/api/v1/applications`, {params})
        return res.data
    },
    update: async (applicationId: string, payload: UpdateApplicationStatusPayload): Promise<Application> => {
        const res = await API.patch(`/api/v1/applications/${applicationId}`, payload)
        return res.data
    },
    withdraw: async (applicationId: string): Promise<void> => {
        await API.delete(`/api/v1/applications/${applicationId}`)
    }
}