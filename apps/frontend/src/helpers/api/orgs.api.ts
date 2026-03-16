import API from "@/helpers/api"



export type OrgStatus = "active" | "Suspended" | "deactivated"
export type OrgPlan = "free" | "Starter" | "growth"| "enterprise"
export type OrgHeadcount = "1-10" | "11-50" | "51-200" | "200+"


export type OrgContact = {
    email: string
    phone: string | null
    website: string | null
}

export type OrgBilling = {
    plan: OrgPlan
    max_active_jobs: number
    max_interviews_per_month: number 
}

export type Org = {
    id: string
    name: string
    slug: OrgStatus
    contact: OrgContact
    billing: OrgBilling
    status: OrgStatus
    logo_url: string | null
    description: string | null
    industry: string | null
    headcount: OrgHeadcount | null
    created_by: string
    created_at: string
    updated_at: string
}


export type CreateOrgPayload = {
    name: string
    slug?: string
    created_by: string
    contact: {email: string, phone?: string, website?: string}
    description?: string
    logo_url?: string
    industry?: string
    headcount?: OrgHeadcount
    billing?: {plan?: OrgPlan, max_active_jobs?: number, max_interviews_per_month?: number}
}


export type UpdateOrgPayload = {
    name?: string
    description?: string
    logo_url?: string
    industry?: string
    headcount?: OrgHeadcount
    contact: {email: string, phone?: string, website?: string}
}


export type ListOrgParams = {
    statu?: OrgStatus
    limit?: number
    offset?: number
}


export const orgsApi = {
    create: async(payload: CreateOrgPayload): Promise<Org> => {
        const res = await API.post(`/api/v1/orgs`, payload)
        return res.data
    },

    getById: async(orgId: string): Promise<Org> => {
        const res = await API.get(`/api/v1/orgs/${orgId}`)
        return res.data
    },

    getBySlug: async(slug: string): Promise<Org> => {
        const res = await API.get(`/api/v1/orgs/slug/${slug}`)
        return res.data
    },

    list: async(params?: ListOrgParams): Promise<Org[]> => {
        const res = await API.get(`/api/v1/orgs`, {params})
        return res.data
    },

    update: async(orgId: string, payload: UpdateOrgPayload): Promise<Org> => {
        const res =  await API.patch(`/api/v1/orgs/${orgId}`, payload)
        return res.data
    },

    suspend: async(orgId: string): Promise<Org> => {
        const res = await API.post(`/api/v1/orgs/${orgId}/suspend`)
        return res.data
    },

    reactivate: async(orgId: string): Promise<Org> => {
        const res = await API.post(`/api/v1/orgs/${orgId}/reactivate`)
        return res.data
    },

    delete: async(orgId: string): Promise<void> => {
        await API.delete(`/api/v1/orgs/${orgId}`)
    },
}