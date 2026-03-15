import './App.css';
import { Routes, Route } from "react-router";
import Landing from "@/pages/Landing"
// import Dashboard from "@/pages/Dashboard"
import ProtectedRoute from "@/components/ProtectedRoute";
import ProtectedLayout from '@/components/ProtectedLayout';
import Verification from "@/pages/Verification"
import ITVPage from '@/pages/ItvPage';
import Dashboard from "@/pages/Dashboard"
import AuthPage from "@/pages/Auth"
import InterviewPage from "@/pages/InterviewPage"


//Recruiter pages
import JobsPage from "@/pages/Jobs"
import JobsDetailPage from "@/pages/JobDetail"
import CandidatesPage from "@/pages/Candidates"
import CandidateDetailPage from "@/pages/CandidateDetail"
import ApplicationsPage from "@/pages/Applications"
import OrgPage from "@/pages/Org"


//candidate pages
import ProfilePage from "@/pages/Profile"

function App() {
  return (
    <div className="w-full min-h-screen">
      <Routes>
        <Route index element={<Landing />} />
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/verify" element={<Verification />} />
        {/* protectedRoute:  protectes authenticated routes */}
        <Route element={<ProtectedRoute />}>
        <Route path="/interview/:jobId/:candidateId" element={<InterviewPage />} />
          {/* you can add protected routes without sidebar below here. */}
          {/* protectedLayout: populates sidebar into protected routes where needed. */}
          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/jobs/:jobId" element={<JobsDetailPage />} />
            <Route path="/candidates" element={<CandidatesPage />} />
            <Route path="/candidates/:candidateId" element={<CandidateDetailPage />} />
            <Route path="/applications" element={<ApplicationsPage />} />
            <Route path="/org" element={<OrgPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
        </Route>
        {/* Dev Test interview setup */}
        <Route path="itv/:jobId/:candidateId" element={<ITVPage />} />
      </Routes>
    </div>
  )
}

export default App
