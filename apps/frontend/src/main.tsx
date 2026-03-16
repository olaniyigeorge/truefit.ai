// import { StrictMode } from 'react'
import "@/helpers/api.interceptors"
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AppProviders from './providers/AppProviders.tsx'

createRoot(document.getElementById('root')!).render(
  // <StrictMode>
    <AppProviders>
        <App />
    </AppProviders>
  // </StrictMode>,
)
