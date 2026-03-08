import './App.css';
import {Routes, Route} from "react-router";
import Landing from "@/pages/Landing"
import ITVPage from '@/pages/ItvPage';



function App() {
  return (
    <>
     <Routes>
      <Route index element={<Landing />} />
      <Route path="itv/:jobId/:candidateId" element={<ITVPage/>} /> 
     </Routes>
    </>
  )
}

export default App
