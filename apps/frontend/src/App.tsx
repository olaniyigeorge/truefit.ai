import './App.css';
import { Routes, Route } from "react-router";
import Landing from "@/pages/Landing"
// import Dashboard from "@/pages/Dashboard"
import ProtectedRoute from "@/components/ProtectedRoute";
import InterviewPage from '@/pages/InterviewPage';
import ITVPage from '@/pages/ItvPage';




function App() {
  return (
    <>
      <Routes>
        {/* Public Routes */}
        <Route index element={<Landing />} />
        {/* Protected Routes */}
        <Route element={<ProtectedRoute />} >
          <Route path="intervew/:sessionId" element={<InterviewPage />} />
        </Route>
        {/* Test interview setup */}
        <Route path="itv/:jobId/:candidateId" element={<ITVPage/>} />
      </Routes>
    </>
  )
}

export default App
