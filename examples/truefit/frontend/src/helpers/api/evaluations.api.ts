import API from "../api"

export type HiringRecommendation =
  | "strong_hire"
  | "hire"
  | "maybe"
  | "no_hire"
  | "strong_no_hire"

export interface SkillScore {
  skill_name: string
  score: number
  rationale: string
}

export interface EvaluationResponse {
  evaluation_id: string
  interview_id: string
  candidate_id: string
  job_id: string
  org_id: string
  recommendation: HiringRecommendation
  overall_score: number | null
  technical_score: number | null
  communication_score: number | null
  problem_solving_score: number | null
  culture_fit_score: number | null
  skill_scores: SkillScore[]
  summary: string
  strengths: string[]
  weaknesses: string[]
  has_report: boolean
  model_version: string | null
  /** Present when the provider could not return a validated evaluation. */
  is_fallback?: boolean
  created_at: string
}

export async function getEvaluation(evaluationId: string): Promise<EvaluationResponse> {
  const response = await API.get<EvaluationResponse>(`/api/v1/evaluations/${evaluationId}`)
  return response.data
}

export async function getEvaluationForInterview(
  interviewId: string,
): Promise<EvaluationResponse> {
  const response = await API.get<EvaluationResponse>(
    `/api/v1/evaluations/by-interview/${interviewId}`,
  )
  return response.data
}
