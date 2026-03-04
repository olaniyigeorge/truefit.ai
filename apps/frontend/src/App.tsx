import './App.css';
import {Routes, Route} from "react-router";
import Landing from "@/pages/Landing"
import Dashboard from "@/pages/Dashboard"
import InterviewPage from '@/pages/InterviewPage';



function App() {
  return (
    <>
     <Routes>
      <Route index element={<Landing />} />
      <Route path="intervew/:sessionId" element={<InterviewPage/>} /> 
     </Routes>
    </>
  )
}

export default App
