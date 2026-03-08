import './App.css';
import { Routes, Route } from "react-router";
import Landing from "@/pages/Landing"
// import Dashboard from "@/pages/Dashboard"
import ProtectedRoute from "@/components/ProtectedRoute";
import {ProtectedLayout} from "@/components/ProtectedLayout"
import InterviewPage from '@/pages/InterviewPage';
import ITVPage from '@/pages/ItvPage';
import SignIn from "@/pages/auth/Signin"
import SignUp from "@/pages/auth/Signup"




function App() {
  return (
    <div className="w-full min-h-screen">
      <Routes>
        <Route index element={<Landing />} />
        <Route path="/signup" element={<SignUp />} />
        <Route path="/signin" element={<SignIn />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<ProtectedLayout />} >
            <Route path="intervew/:sessionId" element={<InterviewPage />} />
          </Route>
        </Route>
        {/* Test interview setup */}
        <Route path="itv/:jobId/:candidateId" element={<ITVPage/>} />
      </Routes>
    </div>
  )
}

export default App
