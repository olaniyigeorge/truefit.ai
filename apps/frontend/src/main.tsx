// crypto.randomUUID polyfill for non-HTTPS environments
if (!crypto.randomUUID) {
  (crypto as any).randomUUID = () => {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = Math.random() * 16 | 0
      const v = c === 'x' ? r : (r & 0x3 | 0x8)
      return v.toString(16)
    })
  }
}

import "@/helpers/api.interceptors"
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AppProviders from './providers/AppProviders.tsx'

createRoot(document.getElementById('root')!).render(
    <AppProviders>
        <App />
    </AppProviders>
)