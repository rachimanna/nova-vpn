import { Bell, Calendar, Moon, Plus, QrCode, RefreshCw, Sun, SunMoon, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { PLATFORM_ICON } from '../components/AddDeviceSheet'
import { Avatar, Bar, Card, Segmented, Skeleton, Toggle } from '../components/ui'
import { useToast } from '../components/Toast'
import { api } from '../lib/api'
import { useDeviceActions } from '../lib/actions'
import { ago, bytes, date, plural } from '../lib/format'
import { useStore, type ThemePref } from '../lib/store'

const STATUS: Record<string, { label: string; tone: string }> = {
  active: { label: 'Активен', tone: 'ok' },
  banned: { label: 'Заблокирован', tone: 'bad' },
  expired: { label: 'Истёк', tone: 'bad' },
  traffic_exceeded: { label: 'Лимит трафика', tone: 'warn' },
}

export function Profile() {
  const { me, theme, setTheme, refresh, showConfig } = useStore()
  const { revoke, regenerate, addDevice, busy } = useDeviceActions()
  const toast = useToast()
  const [notif, setNotif] = useState<boolean | null>(null)

  if (!me) {
    return (
      <div className="screen">
        <Skeleton h={150} r={20} />
        <Skeleton h={120} r={20} />
        <Skeleton h={200} r={20} />
      </div>
    )
  }

  const { user } = me
  const st = STATUS[user.status]
  const total = new Date(user.expires_at).getTime() - new Date(user.created_at).getTime()
  const left = new Date(user.expires_at).getTime() - Date.now()
  const trafficPct = user.traffic_limit ? (user.traffic_used / user.traffic_limit) * 100 : 0
  const notifications = notif ?? user.notifications

  return (
    <div className="screen">
      <h1 className="screen-title">Профиль</h1>

      <Card style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <Avatar url={user.photo_url} name={user.first_name || user.username || 'N'} large />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="ellipsis" style={{ fontSize: 19, fontWeight: 750 }}>{user.first_name || 'Пользователь'}</div>
          <div className="muted ellipsis">{user.username ? `@${user.username}` : 'без username'}</div>
          <div className="faint tabular" style={{ fontSize: 12, marginTop: 2 }}>ID {user.tg_id}</div>
        </div>
        <span className={`pill ${st.tone}`}><span className={`dot ${st.tone}`} />{st.label}</span>
      </Card>

      <div className="stats-grid">
        <Card className="stat">
          <div className="stat-head"><span className="stat-icon"><Calendar size={15} /></span> Доступ</div>
          <div className="stat-value">
            {user.days_left}
            <small>{plural(user.days_left, 'день', 'дня', 'дней')}</small>
          </div>
          <Bar value={total > 0 ? (left / total) * 100 : 0} tone={user.days_left < 4 ? 'warn' : 'ok'} />
          <div className="faint" style={{ fontSize: 12 }}>до {date(user.expires_at)}</div>
        </Card>
        <Card className="stat">
          <div className="stat-head"><span className="stat-icon"><RefreshCw size={15} /></span> Трафик</div>
          <div className="stat-value">{bytes(user.traffic_used)}</div>
          {user.traffic_limit > 0 && <Bar value={trafficPct} tone={trafficPct > 90 ? 'bad' : trafficPct > 70 ? 'warn' : ''} />}
          <div className="faint" style={{ fontSize: 12 }}>
            из {user.traffic_limit ? bytes(user.traffic_limit, 0) : '∞'}
          </div>
        </Card>
      </div>

      <div className="card-row" style={{ padding: '6px 4px 0' }}>
        <div className="section-label" style={{ padding: 0 }}>
          Устройства · {user.devices_active}/{user.device_limit}
        </div>
        <button className="btn small ghost" onClick={addDevice} disabled={user.status !== 'active'}>
          <Plus size={16} /> Добавить
        </button>
      </div>

      <Card className="list" style={{ padding: 0 }}>
        {me.devices.length === 0 && <div className="empty">Нет устройств. Нажмите «Добавить», чтобы получить конфигурацию.</div>}
        {me.devices.map((d) => {
          const Icon = PLATFORM_ICON[d.platform]
          return (
            <div key={d.id} className="list-item" style={{ alignItems: 'flex-start' }}>
              <span className="device-icon"><Icon size={19} /></span>
              <div className="grow">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="ellipsis" style={{ fontWeight: 650 }}>{d.name}</span>
                  <span className={`dot ${d.online ? 'ok' : ''}`} />
                </div>
                <div className="faint" style={{ fontSize: 13 }}>
                  {d.server.flag} {d.server.name} · {d.online ? 'активно' : `отключено · ${ago(d.last_handshake_at)}`}
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                  <button className="btn small" onClick={() => showConfig(d.id)}>
                    <QrCode size={14} /> Конфиг
                  </button>
                  <button className="btn small" disabled={busy} onClick={() => regenerate(d)} aria-label="Перевыпустить ключи">
                    <RefreshCw size={14} />
                  </button>
                  <button className="btn small danger" disabled={busy} onClick={() => revoke(d)} aria-label="Удалить">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </Card>

      <div className="section-label">Настройки</div>
      <Card>
        <div className="card-row" style={{ marginBottom: 12 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}><SunMoon size={18} className="muted" /> Тема</span>
        </div>
        <Segmented<ThemePref>
          value={theme}
          onChange={setTheme}
          options={[
            { value: 'system', label: 'Авто' },
            { value: 'dark', label: <><Moon size={14} /> Тёмная</> },
            { value: 'light', label: <><Sun size={14} /> Светлая</> },
          ]}
        />
        <div className="card-row" style={{ marginTop: 16 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Bell size={18} className="muted" /> Напоминать об окончании доступа
          </span>
          <Toggle
            label="Уведомления"
            on={notifications}
            onChange={async (v) => {
              setNotif(v)
              try {
                await api.setNotifications(v)
                await refresh()
              } catch (e) {
                setNotif(!v)
                toast((e as Error).message, 'error')
              }
            }}
          />
        </div>
      </Card>

      <Card>
        <div className="kv"><span>Аккаунт создан</span><span>{date(user.created_at)}</span></div>
        <div className="kv"><span>Протокол</span><span>WireGuard</span></div>
        <div className="kv"><span>Версия</span><span>NOVA 0.1 MVP</span></div>
      </Card>
    </div>
  )
}
