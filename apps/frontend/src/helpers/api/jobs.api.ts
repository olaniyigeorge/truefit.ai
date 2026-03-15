import API from "@/helpers/api"


export type JobStatus = "draft" | "active" | "paused" | "closed"
export type ExperienceLevel = "junior" | "mid" | "senior" | "lead" | "principal"
export type WorkArrangement = "remote" | "hyybrid" | "onsite"

export type JobSkill = {
    name: string
    required: boolean
    weight: number
    min_years: number | null
}

export type JobRequirement = {
    experience_level: ExperienceLevel
    min_total_years: number | null
    education: string | null
    certifications: string[]
    location: string | null
    work_arrangement: WorkArrangement
}


export type InterviewConfig = {
    max_questions: number
    max_duration_minutes: number
    topics: string[]
    custom_instructions: string | null
}


export type Job = {
    id: string
    org_id: string
    createdBy: string
    title: string
    description: string
    status: JobStatus
    requirements: JobRequirement
    skills: JobSkill[]
    interview_config: InterviewConfig
    created_at: string
    updated_at: string
}

export type CreateJobPayload = {
    org_id: string
    createdBy: string
    title: string
    description: string
    requirements: JobRequirement
    skills: JobSkill[]
    interview_config?: Partial<InterviewConfig>
}

export type UpdateJobPayload = {
    description: string
    requirements: JobRequirement
    skills_add?: JobSkill[]
    skills_remove?: string[]
    interview_config?: Partial<InterviewConfig>
}


export type ListJobParams = {
    org_id: string
    status?: JobStatus
    experience_level?: ExperienceLevel
    limit?: number
    offset?: number
}


export const jobsApi = {
    create: async(payload: CreateJobPayload): Promise<Job> => {
        const res = await API.post(`/api/v1/jobs`, payload)
        return res.data
    },
    getById: async(jobId: string): Promise<Job> => {
        const res = await API.get(`/api/v1/jobs/${jobId}`)
        return res.data
    },
    list: async(params: ListJobParams): Promise<Job[]> => {
        const res = await API.get(`/api/v1/jobs`, {params})
        return res.data
    },
    update: async(jobId: string, payload: UpdateJobPayload): Promise<Job> => {
        const res = await API.patch(`/api/v1/jobs/${jobId}`, payload)
        return res.data
    },
    activate: async(jobId: string): Promise<Job> => {
        const res = await API.post(`/api/v1/jobs/${jobId}/activate`)
        return res.data
    },
    close: async(jobId: string): Promise<Job> => {
        const res = await API.post(`/api/v1/jobs/${jobId}/close`)
        return res.data
    },
    delete: async(jobId: string): Promise<void> => {
        await API.delete(`/api/v1/jobs/${jobId}`)
    },
}
