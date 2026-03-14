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




function App() {
  return (
    <div className="w-full min-h-screen">
      <Routes>
        <Route index element={<Landing />} />
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/verify" element={<Verification />} />
        {/* protectedRoute:  protectes authenticated routes */}
        <Route element={<ProtectedRoute />}>
          {/* you can add protected routes without sidebar below here. */}
          {/* protectedLayout: populates sidebar into protected routes where needed. */}
          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
          </Route>
        </Route>
        {/* Test interview setup */}
        <Route path="itv/:jobId/:candidateId" element={<ITVPage />} />
      </Routes>
    </div>
  )
}

export default App
