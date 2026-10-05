import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { ToastProvider } from './components/Toast'
import { MiniApp } from './MiniApp'
import { StoreProvider } from './lib/store'
import { initTelegram } from './lib/telegram'
import './styles/tokens.css'
import './styles/base.css'
import './styles/app.css'

const Admin = lazy(() => import('./admin/Admin'))
const isAdmin = window.location.pathname.replace(/\/$/, '').endsWith('/admin')

if (!isAdmin) initTelegram()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <div className="aurora" aria-hidden />
      {isAdmin ? (
        <Suspense fallback={null}>
          <Admin />
        </Suspense>
      ) : (
        <StoreProvider>
          <MiniApp />
        </StoreProvider>
      )}
    </ToastProvider>
  </StrictMode>,
)
