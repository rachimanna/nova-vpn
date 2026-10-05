import { AlertCircle, CheckCircle2, Info } from 'lucide-react'
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { haptic } from '../lib/telegram'

type Kind = 'success' | 'error' | 'info'
interface Item {
  id: number
  kind: Kind
  text: string
  leaving?: boolean
}

const ToastCtx = createContext<(text: string, kind?: Kind) => void>(() => {})

export const useToast = () => useContext(ToastCtx)

const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([])
  const seq = useRef(0)

  const push = useCallback((text: string, kind: Kind = 'success') => {
    const id = ++seq.current
    if (kind === 'error') haptic.notify('error')
    else if (kind === 'success') haptic.notify('success')
    setItems((xs) => [...xs.slice(-2), { id, kind, text }])
    setTimeout(() => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, leaving: true } : x))), 2800)
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 3100)
  }, [])

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => {
          const Icon = ICONS[t.kind]
          return (
            <div key={t.id} className={`toast ${t.kind} ${t.leaving ? 'leaving' : ''}`}>
              <span className="toast-icon">
                <Icon size={16} />
              </span>
              {t.text}
            </div>
          )
        })}
      </div>
    </ToastCtx.Provider>
  )
}
