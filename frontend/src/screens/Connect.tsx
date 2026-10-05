import { ArrowDown, ArrowUp, Clock, Download, ExternalLink, Info, Link2, QrCode } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AreaChart } from '../components/AreaChart'
import { Card, Segmented, Skeleton } from '../components/ui'
import { api, type Device, type Point } from '../lib/api'
import { useDeviceActions } from '../lib/actions'
import { ago, bytes, duration } from '../lib/format'
import { useStore } from '../lib/store'
import { detectPlatform, openLink, type Platform } from '../lib/telegram'
import { useTicker } from './Home'

interface Guide {
  label: string
  app: string
  store: string
  storeName: string
  importHint: string
  connectHint: string
}

const LABELS: Record<Platform, string> = { ios: 'iPhone', android: 'Android', windows: 'Windows', macos: 'macOS' }

const HAPP_IMPORT =
  'Нажмите «Скопировать подписку», затем откройте Happ — он предложит добавить её из буфера. Или в Happ: «+» → «Вставить из буфера».'

const VLESS_GUIDES: Record<Platform, Omit<Guide, 'label'>> = {
  ios: {
    app: 'Happ',
    store: 'https://apps.apple.com/app/happ-proxy-utility/id6504287215',
    storeName: 'App Store',
    importHint: HAPP_IMPORT,
    connectHint: 'Нажмите кнопку подключения в Happ и разрешите добавление VPN-конфигурации.',
  },
  android: {
    app: 'Happ',
    store: 'https://play.google.com/store/apps/details?id=com.happproxy',
    storeName: 'Google Play',
    importHint: HAPP_IMPORT,
    connectHint: 'Нажмите кнопку подключения в Happ и подтвердите запрос Android на создание VPN.',
  },
  windows: {
    app: 'Happ',
    store: 'https://www.happ.su/main',
    storeName: 'happ.su',
    importHint: HAPP_IMPORT,
    connectHint: 'Нажмите кнопку подключения. Для всего трафика системы включите режим TUN в настройках Happ.',
  },
  macos: {
    app: 'Happ',
    store: 'https://www.happ.su/main',
    storeName: 'happ.su',
    importHint: HAPP_IMPORT,
    connectHint: 'Нажмите кнопку подключения и разрешите добавление VPN-конфигурации.',
  },
}

const WG_GUIDES: Record<Platform, Omit<Guide, 'label'>> = {
  ios: {
    app: 'WireGuard',
    store: 'https://apps.apple.com/app/wireguard/id1441195209',
    storeName: 'App Store',
    importHint: 'Нажмите «Скачать .conf», затем «Поделиться» → WireGuard. Или в WireGuard: «+» → «Создать из файла или архива».',
    connectHint: 'Разрешите добавление VPN-конфигурации и включите переключатель напротив туннеля.',
  },
  android: {
    app: 'WireGuard',
    store: 'https://play.google.com/store/apps/details?id=com.wireguard.android',
    storeName: 'Google Play',
    importHint: 'Скачайте файл, затем в WireGuard нажмите «+» → «Импорт из файла» и выберите его в «Загрузках».',
    connectHint: 'Подтвердите запрос Android на создание VPN и включите переключатель туннеля.',
  },
  windows: {
    app: 'WireGuard',
    store: 'https://www.wireguard.com/install/',
    storeName: 'wireguard.com',
    importHint: 'В WireGuard нажмите «Import tunnel(s) from file» и выберите скачанный .conf.',
    connectHint: 'Выберите туннель в списке и нажмите «Activate».',
  },
  macos: {
    app: 'WireGuard',
    store: 'https://apps.apple.com/app/wireguard/id1451685025',
    storeName: 'Mac App Store',
    importHint: 'В WireGuard: «Import Tunnel(s) from File…» и выберите скачанный .conf.',
    connectHint: 'Нажмите «Activate» и разрешите добавление VPN-конфигурации.',
  },
}

function guideFor(platform: Platform, protocol: string): Guide {
  const g = protocol === 'wireguard' ? WG_GUIDES[platform] : VLESS_GUIDES[platform]
  return { ...g, label: LABELS[platform] }
}

export function Connect() {
  const { me, showConfig, servers, serverId } = useStore()
  const { create, busy } = useDeviceActions()
  const [platform, setPlatform] = useState<Platform>(detectPlatform)
  const [range, setRange] = useState<'24h' | '7d'>('24h')
  const [series, setSeries] = useState<Point[] | null>(null)
  const [installed, setInstalled] = useState(false)

  useEffect(() => {
    setSeries(null)
    api.stats(range).then((r) => setSeries(r.series)).catch(() => setSeries([]))
  }, [range])

  const device = me?.devices.find((d) => d.platform === platform)
  const protocol = device?.protocol ?? servers?.find((s) => s.id === serverId)?.protocol ?? 'vless'
  const guide = guideFor(platform, protocol)
  const online = me?.devices.filter((d) => d.online) ?? []
  useTicker(online.length > 0)

  const totals = series?.reduce((acc, p) => ({ d: acc.d + p.download, u: acc.u + p.upload }), { d: 0, u: 0 })

  return (
    <div className="screen">
      <h1 className="screen-title">Подключение</h1>

      <Segmented
        value={platform}
        onChange={setPlatform}
        options={(Object.keys(LABELS) as Platform[]).map((p) => ({ value: p, label: LABELS[p] }))}
      />

      <Card>
        <div className="steps">
          <Step n={1} done={installed || Boolean(device)} title={`Установите ${guide.app}`}>
            <span>
              Бесплатное приложение, {guide.storeName}.
              {guide.app === 'Happ' && ' Подойдут и v2RayTun, Hiddify, Streisand, v2rayNG.'}
            </span>
            <button
              className="btn small"
              style={{ alignSelf: 'flex-start' }}
              onClick={() => {
                setInstalled(true)
                openLink(guide.store)
              }}
            >
              <ExternalLink size={15} /> Открыть {guide.storeName}
            </button>
          </Step>

          <Step n={2} done={Boolean(device)} title="Получите конфигурацию">
            {device ? (
              <span>
                Готово: <b>{device.name}</b> · {device.server.flag} {device.server.name}
              </span>
            ) : (
              <>
                <span>Персональные ключи создаются на сервере только для вас.</span>
                <button
                  className="btn small primary"
                  style={{ alignSelf: 'flex-start' }}
                  disabled={busy || me?.user.status !== 'active'}
                  onClick={() => create({ platform })}
                >
                  {busy ? <span className="spinner" /> : `Получить для ${guide.label}`}
                </button>
              </>
            )}
          </Step>

          <Step n={3} done={Boolean(device?.last_handshake_at)} title="Импортируйте конфигурацию">
            <span>{guide.importHint}</span>
            {device && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn small" onClick={() => showConfig(device.id)}>
                  {device.protocol === 'wireguard' ? <><Download size={15} /> Файл</> : <><Link2 size={15} /> Подписка</>}
                </button>
                <button className="btn small" onClick={() => showConfig(device.id)}>
                  <QrCode size={15} /> QR-код
                </button>
              </div>
            )}
          </Step>

          <Step n={4} done={Boolean(device?.online)} title="Нажмите Connect">
            <span>{guide.connectHint}</span>
            {device?.online && <span className="pill ok" style={{ alignSelf: 'flex-start' }}>● Соединение установлено</span>}
          </Step>
        </div>
      </Card>

      <div className="section-label">Активные соединения</div>
      {!me ? (
        <Skeleton h={120} r={20} />
      ) : me.devices.length === 0 ? (
        <Card className="empty">Пока нет устройств — выполните шаги выше.</Card>
      ) : (
        me.devices.map((d) => <ConnectionCard key={d.id} d={d} />)
      )}

      <Card>
        <div className="card-row" style={{ marginBottom: 12 }}>
          <div className="card-title">Статистика</div>
          <div style={{ width: 132 }}>
            <Segmented
              value={range}
              onChange={setRange}
              options={[
                { value: '24h', label: '24ч' },
                { value: '7d', label: '7д' },
              ]}
            />
          </div>
        </div>
        {series ? <AreaChart data={series} range={range} /> : <Skeleton h={150} />}
        {totals && (
          <div className="stats-grid" style={{ marginTop: 14 }}>
            <div>
              <div className="faint" style={{ fontSize: 12 }}>Download</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{bytes(totals.d)}</div>
            </div>
            <div>
              <div className="faint" style={{ fontSize: 12 }}>Upload</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{bytes(totals.u)}</div>
            </div>
          </div>
        )}
      </Card>

      <div className="notice info">
        <Info size={18} />
        <span>
          VPN включается в приложении ({guide.app}) — браузер и Telegram не могут управлять сетью устройства. Статус
          здесь обновляется по данным сервера в течение минуты.
        </span>
      </div>
    </div>
  )
}

function Step({ n, done, title, children }: { n: number; done: boolean; title: string; children: React.ReactNode }) {
  return (
    <div className={`step ${done ? 'done' : ''}`}>
      <div className="step-num">{done ? '✓' : n}</div>
      <div>
        <div className="step-title">{title}</div>
        <div className="step-body">{children}</div>
      </div>
    </div>
  )
}

function ConnectionCard({ d }: { d: Device }) {
  return (
    <Card>
      <div className="card-row" style={{ marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="flag" style={{ width: 38, height: 38, fontSize: 22, borderRadius: 12 }}>{d.server.flag}</span>
          <div>
            <div style={{ fontWeight: 650 }}>{d.name}</div>
            <div className="faint" style={{ fontSize: 13 }}>{d.server.name} · {d.protocol === 'wireguard' ? 'WireGuard' : 'VLESS'}</div>
          </div>
        </div>
        <span className={`pill ${d.online ? 'ok' : ''}`}>
          <span className={`dot ${d.online ? 'ok' : ''}`} /> {d.online ? 'Онлайн' : 'Офлайн'}
        </span>
      </div>
      <div className="kv"><span><Clock size={13} /> Сессия</span><span>{d.online ? duration(d.session_started_at) : '—'}</span></div>
      <div className="kv"><span>Последняя активность</span><span>{ago(d.last_handshake_at)}</span></div>
      {d.protocol === 'wireguard' && (
        <div className="kv"><span>Внутренний IP</span><span>{d.address.replace('/32', '')}</span></div>
      )}
      <div className="kv"><span><ArrowDown size={13} /> Download</span><span>{bytes(d.download)}</span></div>
      <div className="kv"><span><ArrowUp size={13} /> Upload</span><span>{bytes(d.upload)}</span></div>
    </Card>
  )
}
