import { Activity, Gauge, HardDrive, LogOut, Server as ServerIcon, ShieldCheck, Users as UsersIcon, UserPlus, Wifi } from 'lucide-react'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AreaChart } from '../components/AreaChart'
import { useToast } from '../components/Toast'
import { Bar, Card, Logo, Skeleton } from '../components/ui'
import { adminApi, adminSession, ApiError, type Overview as OverviewData } from '../lib/api'
import { bytes } from '../lib/format'
import { ServersPanel } from './ServersPanel'
import { UsersPanel } from './UsersPanel'
import './admin.css'

type Section = 'overview' | 'users' | 'servers'

export default function Admin() {
  const [token, setToken] = useState(adminSession.get())
  const [section, setSection] = useState<Section>('overview')
  const toast = useToast()

  useEffect(() => {
    const dark = !window.matchMedia?.('(prefers-color-scheme: light)').matches
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    document.title = 'NOVA VPN · Admin'

    // one-time link from the bot (/admin): exchange it and strip it from the address bar
    const params = new URLSearchParams(window.location.search)
    const link = params.get('t')
    if (link) {
      window.history.replaceState(null, '', window.location.pathname)
      adminApi
        .exchange(link)
        .then((r) => {
          adminSession.set(r.token)
          setToken(r.token)
        })
        .catch((e) => toast(e.message, 'error'))
    }
  }, [])

  const logout = useCallback(() => {
    adminSession.set(null)
    setToken(null)
  }, [])

  // any 401 from a panel drops the session
  const onError = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) logout()
      toast((e as Error).message, 'error')
    },
    [logout, toast],
  )

  if (!token) return <Login onToken={(t) => { adminSession.set(t); setToken(t) }} />

  const NAV: { id: Section; label: string; Icon: typeof Activity }[] = [
    { id: 'overview', label: 'Обзор', Icon: Activity },
    { id: 'users', label: 'Пользователи', Icon: UsersIcon },
    { id: 'servers', label: 'Серверы', Icon: ServerIcon },
  ]

  return (
    <div className="admin">
      <aside className="admin-side">
        <div className="brand" style={{ padding: '4px 8px 18px' }}>
          <span className="brand-mark"><Logo /></span>
          <span>NOVA <span className="faint" style={{ fontWeight: 600 }}>Admin</span></span>
        </div>
        <nav className="admin-nav">
          {NAV.map(({ id, label, Icon }) => (
            <button key={id} className={section === id ? 'active' : ''} onClick={() => setSection(id)}>
              <Icon size={17} /> {label}
            </button>
          ))}
        </nav>
        <button className="btn ghost small admin-logout" onClick={logout}>
          <LogOut size={15} /> Выйти
        </button>
      </aside>
      <main className="admin-main">
        {section === 'overview' && <OverviewPanel onError={onError} />}
        {section === 'users' && <UsersPanel onError={onError} />}
        {section === 'servers' && <ServersPanel onError={onError} />}
      </main>
    </div>
  )
}

function Login({ onToken }: { onToken: (t: string) => void }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      onToken((await adminApi.login(password)).token)
    } catch (err) {
      toast((err as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center-screen" style={{ position: 'relative', zIndex: 1, minHeight: '100dvh' }}>
      <form className="card admin-login" onSubmit={submit}>
        <span className="brand-mark" style={{ width: 56, height: 56, borderRadius: 18, margin: '0 auto' }}>
          <ShieldCheck size={26} />
        </span>
        <h1 style={{ fontSize: 22, textAlign: 'center' }}>NOVA Admin</h1>
        <p className="muted" style={{ textAlign: 'center', fontSize: 14 }}>
          Войдите паролем из <code>ADMIN_PASSWORD</code> или командой <code>/admin</code> в боте.
        </p>
        <input
          className="input"
          type="password"
          autoComplete="current-password"
          placeholder="Пароль администратора"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        <button className="btn primary block" disabled={busy || !password}>
          {busy ? <span className="spinner" /> : 'Войти'}
        </button>
      </form>
    </div>
  )
}

export function PanelHead({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="card-row" style={{ marginBottom: 18, flexWrap: 'wrap' }}>
      <h1 className="screen-title">{title}</h1>
      {right}
    </div>
  )
}

function Kpi({ icon, label, value, hint }: { icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card className="stat">
      <div className="stat-head"><span className="stat-icon">{icon}</span>{label}</div>
      <div className="stat-value" style={{ fontSize: 26 }}>{value}</div>
      {hint && <div className="faint" style={{ fontSize: 12 }}>{hint}</div>}
    </Card>
  )
}

function OverviewPanel({ onError }: { onError: (e: unknown) => void }) {
  const [data, setData] = useState<OverviewData | null>(null)

  useEffect(() => {
    const load = () => adminApi.overview().then(setData).catch(onError)
    load()
    const t = setInterval(load, 20000)
    return () => clearInterval(t)
  }, [onError])

  if (!data) {
    return (
      <>
        <PanelHead title="Обзор" />
        <div className="kpi-grid">{[...Array(6)].map((_, i) => <Skeleton key={i} h={110} r={20} />)}</div>
      </>
    )
  }
  const s = data.stats

  return (
    <>
      <PanelHead title="Обзор" right={<span className="pill"><span className="dot ok" /> Обновляется автоматически</span>} />
      <div className="kpi-grid">
        <Kpi icon={<UsersIcon size={15} />} label="Всего пользователей" value={s.total_users} hint={<>+{s.new_users_24h} за 24 ч</>} />
        <Kpi icon={<UserPlus size={15} />} label="Активных" value={s.active_users} hint={<>{s.banned_users} заблокировано</>} />
        <Kpi icon={<ShieldCheck size={15} />} label="Конфигураций" value={s.active_configs} />
        <Kpi icon={<Wifi size={15} />} label="Подключений" value={s.active_connections} hint="handshake < 3 мин" />
        <Kpi icon={<HardDrive size={15} />} label="Трафик" value={bytes(s.total_traffic)} hint="за всё время" />
        <Kpi icon={<ServerIcon size={15} />} label="Серверы онлайн" value={`${s.servers_online}/${s.servers_total}`} />
      </div>

      <div className="admin-two">
        <Card>
          <div className="card-row" style={{ marginBottom: 12 }}>
            <div className="card-title">Трафик сервиса · 24 ч</div>
            <div className="legend">
              <span><i style={{ background: '#8b5cf6' }} />Download</span>
              <span><i style={{ background: '#22d3ee' }} />Upload</span>
            </div>
          </div>
          <AreaChart data={data.traffic} range="24h" />
        </Card>
        <Card>
          <div className="card-title" style={{ marginBottom: 10 }}>Нагрузка серверов</div>
          {data.servers.map((srv) => (
            <div key={srv.id} className="kv" style={{ alignItems: 'center' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={`dot ${srv.status === 'online' ? 'ok' : 'bad'}`} />
                {srv.flag} {srv.name}
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 170, justifyContent: 'flex-end' }}>
                <span className="faint" style={{ fontWeight: 500, fontSize: 12 }}>
                  <Gauge size={12} /> {srv.ping_ms ?? '—'}ms · {srv.peers_online} онлайн
                </span>
                <span style={{ width: 60 }}><Bar value={srv.load} tone={srv.load_level === 'low' ? 'ok' : srv.load_level === 'medium' ? 'warn' : 'bad'} /></span>
              </span>
            </div>
          ))}
        </Card>
      </div>
    </>
  )
}
