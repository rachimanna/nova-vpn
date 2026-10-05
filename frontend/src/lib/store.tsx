import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, type Me, type Server } from './api'
import { inTelegram, paintChrome, tg } from './telegram'

export type Tab = 'home' | 'servers' | 'connect' | 'profile'
export type ThemePref = 'system' | 'dark' | 'light'

interface Store {
  me: Me | null
  servers: Server[] | null
  error: ApiError | null
  refresh: () => Promise<void>
  tab: Tab
  go: (tab: Tab) => void
  serverId: number | null
  setServerId: (id: number) => void
  theme: ThemePref
  setTheme: (t: ThemePref) => void
  configFor: number | null
  showConfig: (deviceId: number | null) => void
  addDeviceOpen: boolean
  setAddDeviceOpen: (v: boolean) => void
}

const Ctx = createContext<Store>(null as unknown as Store)
export const useStore = () => useContext(Ctx)

const store = {
  get(key: string) {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(key, value)
    } catch {
      /* private mode */
    }
  },
}

function resolveTheme(pref: ThemePref): 'dark' | 'light' {
  if (pref !== 'system') return pref
  // outside Telegram the SDK still reports a default 'light' scheme, so only trust it inside
  if (inTelegram && tg?.colorScheme) return tg.colorScheme
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function initialTab(): Tab {
  const screen = new URLSearchParams(window.location.search).get('screen')
  return screen === 'servers' || screen === 'connect' || screen === 'profile' ? screen : 'home'
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [servers, setServers] = useState<Server[] | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [tab, setTab] = useState<Tab>(initialTab)
  const [serverId, setServerIdState] = useState<number | null>(() => Number(store.get('nova-server')) || null)
  const [theme, setThemeState] = useState<ThemePref>(() => (store.get('nova-theme') as ThemePref) || 'system')
  const [configFor, showConfig] = useState<number | null>(null)
  const [addDeviceOpen, setAddDeviceOpen] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [m, s] = await Promise.all([api.me(), api.servers()])
      setMe(m)
      setServers(s)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'Неизвестная ошибка'))
    }
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(() => document.visibilityState === 'visible' && refresh(), 15000)
    return () => clearInterval(t)
  }, [refresh])

  useEffect(() => {
    const apply = () => {
      const mode = resolveTheme(theme)
      document.documentElement.dataset.theme = mode
      const bg = mode === 'dark' ? '#07070c' : '#f3f4f9'
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg)
      paintChrome(bg)
    }
    apply()
    tg?.onEvent('themeChanged', apply)
    return () => tg?.offEvent('themeChanged', apply)
  }, [theme])

  const go = (t: Tab) => {
    setTab(t)
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
  }

  // default server = remembered one if still available, otherwise the best online one
  const fallback = servers
    ?.filter((s) => s.status === 'online')
    // VLESS first: it works with Happ & co. and survives DPI better than WireGuard
    .sort(
      (a, b) =>
        Number(a.protocol === 'wireguard') - Number(b.protocol === 'wireguard') ||
        a.load - b.load ||
        (a.ping_ms ?? 999) - (b.ping_ms ?? 999),
    )[0]?.id
  const effectiveServer = servers?.some((s) => s.id === serverId && s.status === 'online') ? serverId : fallback ?? null

  return (
    <Ctx.Provider
      value={{
        me,
        servers,
        error,
        refresh,
        tab,
        go,
        serverId: effectiveServer,
        setServerId: (id) => {
          setServerIdState(id)
          store.set('nova-server', String(id))
        },
        theme,
        setTheme: (t) => {
          setThemeState(t)
          store.set('nova-theme', t)
        },
        configFor,
        showConfig,
        addDeviceOpen,
        setAddDeviceOpen,
      }}
    >
      {children}
    </Ctx.Provider>
  )
}
