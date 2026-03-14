/**
 * ItvPage — /itv/:jobId/:candidateId
 * 
 * Two states:
 *  1. Setup — shows ID fields pre-filled from URL params, lets user start
 *  2. Live  — full interview room with transcript, audio viz, controls
 */

import { useState } from "react"
import { useParams } from "react-router"
import {InterviewRoom} from "@/components/InterviewRoom"
import {SetupScreen} from "@/components/SetupScreen"





export default function ItvPage() {
  const { jobId: urlJobId, candidateId: urlCandidateId } = useParams<{
    jobId: string; candidateId: string
  }>()
 
  const [jobId,       setJobId]       = useState(urlJobId       ?? "")
  const [candidateId, setCandidateId] = useState(urlCandidateId ?? "")
  const [started,     setStarted]     = useState(false)
 
  const uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  const isConnecting = false
 
  console.log("URL params", {
    urlJobId, urlCandidateId,
    isValidJobId:       uuidRe.test(urlJobId       ?? ""),
    isValidCandidateId: uuidRe.test(urlCandidateId ?? ""),
  })
 
  const handleStart = () => {
    if (!jobId.trim() || !candidateId.trim()) return
    setStarted(true)
  }
 
  if (started && jobId && candidateId) {
    return <InterviewRoom jobId={jobId} candidateId={candidateId} onExit={() => setStarted(false)} />
  }
 
  return (
    <div
      className="min-h-screen flex items-center justify-center p-6 bg-background"
      style={{
        backgroundImage: `
          radial-gradient(ellipse 80% 50% at 50% -10%, rgba(34,197,94,0.12) 6%, transparent 95%),
          linear-gradient(rgba(34,197,94,0.03) 0.5px, transparent 1px),
          linear-gradient(90deg, rgba(34,197,94,0.03) 0.5px, transparent 1px)
        `,
        backgroundSize: "100% 100%, 48px 48px, 48px 48px",
      }}
    >
      <SetupScreen
        jobId={jobId}
        candidateId={candidateId}
        onJobIdChange={setJobId}
        onCandidateIdChange={setCandidateId}
        onStart={handleStart}
        isConnecting={isConnecting}
      />
    </div>
  )
}