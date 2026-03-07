import { useParams, Navigate } from "react-router"
import ITVRoom from "@/components/ItvRoom"


export default function ITVPage() {
  const { jobId, candidateId } = useParams<{ jobId: string; candidateId: string }>()

  if (!jobId || !candidateId) return <Navigate to="/" />

  return (
    <>
      <ITVRoom jobId={jobId} candidateId={candidateId} />
    </>
  )
}
