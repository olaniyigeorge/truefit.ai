import './App.css';
import {Routes, Route} from "react-router";
import Landing from "@/pages/Landing"
// import Dashboard from "@/pages/Dashboard"
import InterviewPage from '@/pages/InterviewPage';
import ITVPage from '@/pages/ItvPage';



function App() {
  return (
    <>
     <Routes>
      <Route index element={<Landing />} />
      <Route path="interview/:sessionId" element={<InterviewPage/>} /> 
      <Route path="itv/:jobId/:candidateId" element={<ITVPage/>} /> 
     </Routes>
    </>
  )
}

export default App
