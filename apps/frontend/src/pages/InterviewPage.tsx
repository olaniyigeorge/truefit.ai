import { useParams, Navigate } from "react-router"
import InterviewRoom from "@/components/InterviewRoom"


export default function InterviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>()

  if (!sessionId) return <Navigate to="/" />

  return (
    <>
      <InterviewRoom sessionId={sessionId} />
    </>
  )
}
