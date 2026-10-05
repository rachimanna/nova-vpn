import { Check, Search } from 'lucide-react'
import { useState } from 'react'
import { Sheet } from '../components/Sheet'
import { Bar, Card, Signal, Skeleton } from '../components/ui'
import type { Server } from '../lib/api'
import { useDeviceActions } from '../lib/actions'
import { useStore } from '../lib/store'
import { haptic } from '../lib/telegram'

const LOAD_LABEL = { low: 'Низкая нагрузка', medium: 'Средняя нагрузка', high: 'Высокая нагрузка' }
const LOAD_TONE = { low: 'ok', medium: 'warn', high: 'bad' } as const

export function Servers() {
  const { servers, serverId, setServerId, me } = useStore()
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<Server | null>(null)

  const list = (servers ?? []).filter((s) =>
    `${s.name} ${s.city ?? ''} ${s.country}`.toLowerCase().includes(query.trim().toLowerCase()),
  )
  const best = servers
    ?.filter((s) => s.status === 'online')
    .sort((a, b) => (a.ping_ms ?? 999) + a.load - ((b.ping_ms ?? 999) + b.load))[0]?.id

  const choose = (s: Server) => {
    if (s.status !== 'online') return
    haptic.select()
    setServerId(s.id)
    if (me?.devices.length) setPicked(s)
  }

  return (
    <div className="screen">
      <div className="topbar">
        <h1 className="screen-title">Серверы</h1>
        <span className="pill">{servers?.filter((s) => s.status === 'online').length ?? 0} онлайн</span>
      </div>

      <div style={{ position: 'relative' }}>
        <Search size={17} className="faint" style={{ position: 'absolute', left: 14, top: 14.5 }} />
        <input
          className="input"
          style={{ paddingLeft: 40 }}
          placeholder="Страна или город"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {!servers
        ? [0, 1, 2, 3].map((i) => <Skeleton key={i} h={74} r={20} />)
        : list.map((s) => (
            <button
              key={s.id}
              className={`card server ${serverId === s.id ? 'selected' : ''} ${s.status !== 'online' ? 'offline' : ''}`}
              onClick={() => choose(s)}
            >
              <span className="flag">{s.flag}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 650 }}>
                  {s.name}
                  {s.id === best && <span className="pill ok" style={{ height: 20, fontSize: 10 }}>Лучший</span>}
                </span>
                <span className="faint" style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
                  <span className={`dot ${s.status === 'online' ? LOAD_TONE[s.load_level] : 'bad'}`} />
                  {s.status === 'online' ? LOAD_LABEL[s.load_level] : 'Недоступен'}
                  {s.city && <> · {s.city}</>}
                </span>
              </span>
              <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
                <span className="tabular" style={{ fontWeight: 650, fontSize: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Signal ping={s.ping_ms} /> {s.ping_ms != null ? `${s.ping_ms} ms` : '—'}
                </span>
                <span className="load-mini">
                  <Bar value={s.load} tone={LOAD_TONE[s.load_level]} />
                </span>
              </span>
              {serverId === s.id && (
                <Check size={18} style={{ color: 'var(--nova-1)', flexShrink: 0 }} />
              )}
            </button>
          ))}

      {servers && list.length === 0 && <div className="empty">Ничего не найдено</div>}

      <p className="faint" style={{ fontSize: 12, textAlign: 'center', padding: '0 12px' }}>
        Ping — задержка до сервера из нашей сети. Точное значение для вашего устройства покажет WireGuard после подключения.
      </p>

      {picked && <MoveSheet server={picked} onClose={() => setPicked(null)} />}
    </div>
  )
}

function MoveSheet({ server, onClose }: { server: Server; onClose: () => void }) {
  const { me } = useStore()
  const { regenerate, create, busy } = useDeviceActions()
  const devices = me?.devices ?? []
  const canAdd = me ? me.user.devices_active < me.user.device_limit : false

  return (
    <Sheet title={`${server.flag} ${server.name}`} onClose={onClose}>
      <p className="muted" style={{ fontSize: 14 }}>
        Сервер выбран для новых конфигураций. Перенести существующее устройство?
      </p>
      <Card className="list" style={{ padding: 0 }}>
        {devices.map((d) => (
          <button
            key={d.id}
            className="list-item"
            disabled={busy || d.server.id === server.id}
            onClick={async () => {
              await regenerate(d, server.id)
              onClose()
            }}
          >
            <span className="grow">
              <div style={{ fontWeight: 600 }}>{d.name}</div>
              <div className="faint" style={{ fontSize: 13 }}>
                сейчас: {d.server.flag} {d.server.name}
              </div>
            </span>
            {d.server.id === server.id ? <span className="pill ok">Здесь</span> : <span className="pill">Перенести</span>}
          </button>
        ))}
      </Card>
      {canAdd && (
        <button
          className="btn block"
          disabled={busy}
          onClick={async () => {
            await create({ server: server.id })
            onClose()
          }}
        >
          Новое устройство на этом сервере
        </button>
      )}
    </Sheet>
  )
}
