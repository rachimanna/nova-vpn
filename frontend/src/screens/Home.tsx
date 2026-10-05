import { Activity, ArrowDown, ArrowUp, ChevronRight, Gauge, Globe2, HardDrive, Power, ShieldCheck, ShieldOff, Smartphone, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AreaChart } from '../components/AreaChart'
import { Avatar, Bar, Brand, Card, Skeleton } from '../components/ui'
import { api, type Point } from '../lib/api'
import { useDeviceActions } from '../lib/actions'
import { bytes, duration, speed } from '../lib/format'
import { useStore } from '../lib/store'

const BLOCKED: Record<string, string> = {
  banned: 'Аккаунт заблокирован',
  expired: 'Срок доступа истёк',
  traffic_exceeded: 'Лимит трафика исчерпан',
}

export function useTicker(active: boolean) {
  const [, setNow] = useState(0)
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
}

export function Home() {
  const { me, servers, serverId, go } = useStore()
  const { primary, busy } = useDeviceActions()
  const [series, setSeries] = useState<Point[] | null>(null)

  useEffect(() => {
    api.stats('24h').then((r) => setSeries(r.series)).catch(() => setSeries([]))
  }, [me?.user.traffic_used])

  const state = me?.vpn.state
  useTicker(state === 'connected')

  if (!me) return <HomeSkeleton />

  const { user, vpn } = me
  const blocked = user.status !== 'active'
  const selected = servers?.find((s) => s.id === serverId)
  const shown = vpn.server ?? selected
  const ping = vpn.server?.ping_ms ?? selected?.ping_ms ?? null
  const trafficPct = user.traffic_limit ? (user.traffic_used / user.traffic_limit) * 100 : 0
  const orb = blocked ? 'blocked' : state === 'connected' ? 'connected' : state === 'ready' ? 'ready' : 'idle'

  const status = blocked
    ? BLOCKED[user.status]
    : state === 'connected'
      ? 'VPN подключён'
      : state === 'ready'
        ? 'VPN готов'
        : 'VPN не подключён'

  const sub = blocked
    ? 'Обратитесь в поддержку через бота'
    : state === 'connected'
      ? `${vpn.server?.flag} ${vpn.server?.name} · защищённое соединение`
      : state === 'ready'
        ? 'Включите VPN в приложении Happ или WireGuard'
        : 'Получите персональную конфигурацию за 10 секунд'

  return (
    <div className="screen">
      <Brand
        right={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {me.demo && <span className="pill demo">DEMO</span>}
            <button onClick={() => go('profile')} aria-label="Профиль">
              <Avatar url={user.photo_url} name={user.first_name || user.username || 'N'} />
            </button>
          </div>
        }
      />

      <Card className="hero">
        <div className={`orb ${orb}`}>
          <span className="orb-ring" />
          <span className="orb-ring" />
          <span className="orb-ring" />
          <div className="orb-core">
            {blocked ? <ShieldOff size={42} /> : state === 'connected' ? <ShieldCheck size={44} /> : <Power size={40} />}
          </div>
        </div>

        <div>
          <div className="hero-status">
            {state === 'connected' && !blocked ? <span className="grad-text">{status}</span> : status}
          </div>
          <div className="hero-sub">{sub}</div>
        </div>

        {!blocked && (
          <button className={`cta ${state === 'connected' ? 'connected' : ''}`} onClick={primary} disabled={busy}>
            {busy ? (
              <span className="spinner" />
            ) : state === 'connected' ? (
              <>
                <Activity size={18} /> <span className="tabular">СЕССИЯ {duration(vpn.session_started_at)}</span>
              </>
            ) : state === 'ready' ? (
              <>
                <Zap size={18} /> ПОЛУЧИТЬ КЛЮЧ
              </>
            ) : (
              <>
                <Zap size={18} /> ПОДКЛЮЧИТЬ VPN
              </>
            )}
          </button>
        )}
      </Card>

      <div className="stats-grid">
        <Card className="stat wide" onClick={() => go('servers')}>
          <div className="card-row">
            <div className="stat-head">
              <span className="stat-icon"><Globe2 size={15} /></span> Сервер
            </div>
            <ChevronRight size={18} className="faint" />
          </div>
          <div className="stat-value">
            {shown ? `${shown.flag} ${shown.name}` : '—'}
            {shown?.city && <small> · {shown.city}</small>}
          </div>
        </Card>

        <Card className="stat">
          <div className="stat-head">
            <span className="stat-icon"><Gauge size={15} /></span> Ping
          </div>
          <div className="stat-value">
            {ping ?? '—'}
            <small>ms</small>
          </div>
        </Card>

        <Card className="stat">
          <div className="stat-head">
            <span className="stat-icon"><Zap size={15} /></span> Скорость
          </div>
          <div className="stat-value" style={{ fontSize: 15, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span><ArrowDown size={13} style={{ color: 'var(--nova-1)' }} /> {speed(vpn.speed.download)}</span>
            <span><ArrowUp size={13} style={{ color: 'var(--nova-3)' }} /> {speed(vpn.speed.upload)}</span>
          </div>
        </Card>

        <Card className="stat">
          <div className="stat-head">
            <span className="stat-icon"><HardDrive size={15} /></span> Трафик
          </div>
          <div className="stat-value">
            {bytes(user.traffic_used)}
            <small>/ {user.traffic_limit ? bytes(user.traffic_limit, 0) : '∞'}</small>
          </div>
          {user.traffic_limit > 0 && <Bar value={trafficPct} tone={trafficPct > 90 ? 'bad' : trafficPct > 70 ? 'warn' : ''} />}
        </Card>

        <Card className="stat" onClick={() => go('profile')}>
          <div className="stat-head">
            <span className="stat-icon"><Smartphone size={15} /></span> Устройства
          </div>
          <div className="stat-value">
            {user.devices_active}
            <small>/ {user.device_limit}</small>
          </div>
          <Bar value={(user.devices_active / Math.max(1, user.device_limit)) * 100} tone="ok" />
        </Card>
      </div>

      <Card>
        <div className="card-row" style={{ marginBottom: 12 }}>
          <div className="card-title">Трафик за 24 часа</div>
          <div className="legend">
            <span><i style={{ background: '#8b5cf6' }} />Download</span>
            <span><i style={{ background: '#22d3ee' }} />Upload</span>
          </div>
        </div>
        {series ? <AreaChart data={series} range="24h" /> : <Skeleton h={150} />}
      </Card>
    </div>
  )
}

function HomeSkeleton() {
  return (
    <div className="screen">
      <Brand />
      <Card className="hero">
        <Skeleton h={168} w={168} r={84} />
        <Skeleton h={24} w={180} />
        <Skeleton h={58} r={18} />
      </Card>
      <div className="stats-grid">
        <div className="wide" style={{ gridColumn: 'span 2' }}>
          <Skeleton h={84} r={20} />
        </div>
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} h={92} r={20} />
        ))}
      </div>
    </div>
  )
}
