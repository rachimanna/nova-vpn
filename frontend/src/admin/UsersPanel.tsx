import { Ban, Plus, RotateCcw, Search, ShieldCheck, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AreaChart } from '../components/AreaChart'
import { Sheet } from '../components/Sheet'
import { useToast } from '../components/Toast'
import { Bar, Card, Segmented, Skeleton } from '../components/ui'
import { adminApi, type Server, type UserDetail, type UserInfo } from '../lib/api'
import { ago, bytes, date } from '../lib/format'
import { PanelHead } from './Admin'

const STATUS: Record<string, [string, string]> = {
  active: ['Активен', 'ok'],
  banned: ['Бан', 'bad'],
  expired: ['Истёк', 'bad'],
  traffic_exceeded: ['Лимит', 'warn'],
}

type Filter = 'all' | 'active' | 'banned' | 'expired'

export function UsersPanel({ onError }: { onError: (e: unknown) => void }) {
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<{ total: number; per_page: number; items: UserInfo[] } | null>(null)
  const [open, setOpen] = useState<number | null>(null)

  const load = () => adminApi.users(q, filter, page).then(setData).catch(onError)

  useEffect(() => {
    const t = setTimeout(load, 250) // debounce typing
    return () => clearTimeout(t)
  }, [q, filter, page])

  const pages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1

  return (
    <>
      <PanelHead title="Пользователи" right={data && <span className="pill">{data.total} найдено</span>} />
      <div className="admin-toolbar">
        <div style={{ position: 'relative', flex: 1, minWidth: 220 }}>
          <Search size={17} className="faint" style={{ position: 'absolute', left: 14, top: 14.5 }} />
          <input
            className="input"
            style={{ paddingLeft: 40 }}
            placeholder="Username, имя или Telegram ID"
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setPage(1)
            }}
          />
        </div>
        <div style={{ minWidth: 320 }}>
          <Segmented<Filter>
            value={filter}
            onChange={(f) => {
              setFilter(f)
              setPage(1)
            }}
            options={[
              { value: 'all', label: 'Все' },
              { value: 'active', label: 'Активные' },
              { value: 'banned', label: 'Бан' },
              { value: 'expired', label: 'Истёк' },
            ]}
          />
        </div>
      </div>

      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Пользователь</th>
                <th>Telegram ID</th>
                <th>Регистрация</th>
                <th>Статус</th>
                <th>Устройства</th>
                <th>Трафик</th>
              </tr>
            </thead>
            <tbody>
              {!data
                ? [...Array(6)].map((_, i) => (
                    <tr key={i}><td colSpan={6}><Skeleton h={22} /></td></tr>
                  ))
                : data.items.map((u) => (
                    <tr key={u.id} onClick={() => setOpen(u.id)}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{u.first_name || '—'}</div>
                        <div className="faint" style={{ fontSize: 12 }}>{u.username ? `@${u.username}` : 'без username'}</div>
                      </td>
                      <td className="tabular">{u.tg_id}</td>
                      <td>{date(u.created_at)}</td>
                      <td><span className={`pill ${STATUS[u.status][1]}`}>{STATUS[u.status][0]}</span></td>
                      <td className="tabular">{u.devices_active}/{u.device_limit}</td>
                      <td style={{ minWidth: 140 }}>
                        <div className="tabular" style={{ fontSize: 13 }}>
                          {bytes(u.traffic_used)} <span className="faint">/ {u.traffic_limit ? bytes(u.traffic_limit, 0) : '∞'}</span>
                        </div>
                        {u.traffic_limit > 0 && <Bar value={(u.traffic_used / u.traffic_limit) * 100} />}
                      </td>
                    </tr>
                  ))}
              {data && data.items.length === 0 && (
                <tr><td colSpan={6} className="empty">Никого не найдено</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {pages > 1 && (
        <div className="card-row" style={{ justifyContent: 'center', marginTop: 14 }}>
          <button className="btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>←</button>
          <span className="muted tabular">{page} / {pages}</span>
          <button className="btn small" disabled={page >= pages} onClick={() => setPage(page + 1)}>→</button>
        </div>
      )}

      {open != null && <UserSheet id={open} onClose={() => { setOpen(null); load() }} onError={onError} />}
    </>
  )
}

function UserSheet({ id, onClose, onError }: { id: number; onClose: () => void; onError: (e: unknown) => void }) {
  const [d, setD] = useState<UserDetail | null>(null)
  const [servers, setServers] = useState<Server[]>([])
  const [limit, setLimit] = useState('')
  const [traffic, setTraffic] = useState('')
  const [serverId, setServerId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const apply = (res: UserDetail) => {
    setD(res)
    setLimit(String(res.user.device_limit))
    setTraffic(String(Math.round((res.user.traffic_limit / 1024 ** 3) * 10) / 10))
  }

  useEffect(() => {
    adminApi.user(id).then(apply).catch(onError)
    adminApi.servers().then((s) => {
      setServers(s)
      setServerId(s.find((x) => x.status === 'online')?.id ?? null)
    }).catch(onError)
  }, [id])

  const act = async (fn: () => Promise<UserDetail | unknown>, ok: string) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res && typeof res === 'object' && 'user' in res) apply(res as UserDetail)
      else apply(await adminApi.user(id))
      toast(ok)
    } catch (e) {
      onError(e)
    } finally {
      setBusy(false)
    }
  }

  const u = d?.user
  return (
    <Sheet title={u ? `${u.first_name || 'Пользователь'} ${u.username ? '@' + u.username : ''}` : 'Пользователь'} onClose={onClose}>
      {!d || !u ? (
        <Skeleton h={300} />
      ) : (
        <>
          <div className="stats-grid">
            <Card className="stat">
              <div className="stat-head">Статус</div>
              <span className={`pill ${STATUS[u.status][1]}`} style={{ alignSelf: 'flex-start' }}>{STATUS[u.status][0]}</span>
              <div className="faint" style={{ fontSize: 12 }}>ID {u.tg_id} · был {ago(u.last_seen_at)}</div>
            </Card>
            <Card className="stat">
              <div className="stat-head">Доступ до</div>
              <div className="stat-value" style={{ fontSize: 17 }}>{date(u.expires_at)}</div>
              <div className="faint" style={{ fontSize: 12 }}>осталось {u.days_left} дн.</div>
            </Card>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {u.is_banned ? (
              <button className="btn small" disabled={busy} onClick={() => act(() => adminApi.unban(id), 'Разблокирован')}>
                <ShieldCheck size={15} /> Unban
              </button>
            ) : (
              <button className="btn small danger" disabled={busy} onClick={() => act(() => adminApi.ban(id), 'Заблокирован')}>
                <Ban size={15} /> Ban
              </button>
            )}
            <button className="btn small" disabled={busy} onClick={() => act(() => adminApi.patchUser(id, { extend_days: 30 }), 'Продлено на 30 дней')}>
              +30 дней
            </button>
            <button className="btn small" disabled={busy} onClick={() => act(() => adminApi.patchUser(id, { reset_traffic: true }), 'Трафик сброшен')}>
              <RotateCcw size={15} /> Сбросить трафик
            </button>
          </div>

          <Card>
            <div className="card-title" style={{ marginBottom: 12 }}>Лимиты</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 10, alignItems: 'end' }}>
              <div className="field">
                <label>Устройства</label>
                <input className="input" type="number" min={0} max={50} value={limit} onChange={(e) => setLimit(e.target.value)} />
              </div>
              <div className="field">
                <label>Трафик, GB (0 = ∞)</label>
                <input className="input" type="number" min={0} step="0.5" value={traffic} onChange={(e) => setTraffic(e.target.value)} />
              </div>
              <button
                className="btn primary"
                disabled={busy}
                onClick={() =>
                  act(() => adminApi.patchUser(id, { device_limit: Number(limit), traffic_limit_gb: Number(traffic) }), 'Лимиты сохранены')
                }
              >
                Сохранить
              </button>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>
                Использовано {bytes(u.traffic_used)} из {u.traffic_limit ? bytes(u.traffic_limit) : '∞'}
              </div>
              {u.traffic_limit > 0 && <Bar value={(u.traffic_used / u.traffic_limit) * 100} />}
            </div>
          </Card>

          <Card style={{ padding: 0 }}>
            <div className="card-row" style={{ padding: '14px 16px 6px' }}>
              <div className="card-title">Конфигурации</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <select className="input" style={{ height: 36, width: 'auto' }} value={serverId ?? ''} onChange={(e) => setServerId(Number(e.target.value))}>
                  {servers.map((s) => (
                    <option key={s.id} value={s.id}>{s.flag} {s.name}</option>
                  ))}
                </select>
                <button
                  className="btn small"
                  disabled={busy || !serverId}
                  onClick={() => act(() => adminApi.createDevice(id, serverId!, 'Admin config'), 'Конфигурация создана')}
                >
                  <Plus size={15} /> Создать
                </button>
              </div>
            </div>
            {d.devices.length === 0 && <div className="empty">Нет конфигураций</div>}
            {d.devices.map((dev) => (
              <div key={dev.id} className="list-item" style={{ opacity: dev.status === 'revoked' ? 0.5 : 1 }}>
                <span className={`dot ${dev.online ? 'ok' : dev.status === 'revoked' ? 'bad' : ''}`} />
                <div className="grow">
                  <div style={{ fontWeight: 600 }}>{dev.name} <span className="faint" style={{ fontWeight: 400 }}>· {dev.platform}</span></div>
                  <div className="faint" style={{ fontSize: 12 }}>
                    {dev.server.flag} {dev.server.code} · {dev.address} · ↓{bytes(dev.download)} ↑{bytes(dev.upload)} ·{' '}
                    {dev.status === 'revoked' ? 'отозвана' : `handshake ${ago(dev.last_handshake_at)}`}
                  </div>
                </div>
                {dev.status === 'active' && (
                  <button
                    className="btn small danger"
                    disabled={busy}
                    aria-label="Удалить конфигурацию"
                    onClick={() => act(() => adminApi.revokeDevice(dev.id), 'Конфигурация удалена')}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
          </Card>

          <Card>
            <div className="card-title" style={{ marginBottom: 10 }}>Трафик · 7 дней</div>
            <AreaChart data={d.traffic} range="7d" />
          </Card>
        </>
      )}
    </Sheet>
  )
}
