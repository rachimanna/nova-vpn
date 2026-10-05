import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Sheet } from '../components/Sheet'
import { useToast } from '../components/Toast'
import { Bar, Card, Skeleton, Toggle } from '../components/ui'
import { adminApi, type AdminServer } from '../lib/api'
import { ago } from '../lib/format'
import { PanelHead } from './Admin'

export function ServersPanel({ onError }: { onError: (e: unknown) => void }) {
  const [list, setList] = useState<AdminServer[] | null>(null)
  const [adding, setAdding] = useState(false)
  const toast = useToast()

  const load = () => adminApi.servers().then(setList).catch(onError)
  useEffect(() => {
    load()
  }, [])

  const toggle = async (s: AdminServer, v: boolean) => {
    try {
      await adminApi.patchServer(s.id, { is_active: v })
      toast(v ? 'Сервер включён' : 'Сервер скрыт от пользователей')
      load()
    } catch (e) {
      onError(e)
    }
  }

  return (
    <>
      <PanelHead
        title="Серверы"
        right={
          <button className="btn primary small" onClick={() => setAdding(true)}>
            <Plus size={16} /> Добавить сервер
          </button>
        }
      />
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Сервер</th>
                <th>Endpoint</th>
                <th>Статус</th>
                <th>Ping</th>
                <th>Онлайн</th>
                <th>Конфиги</th>
                <th>Нагрузка</th>
                <th>Активен</th>
              </tr>
            </thead>
            <tbody>
              {!list
                ? [...Array(4)].map((_, i) => <tr key={i}><td colSpan={8}><Skeleton h={22} /></td></tr>)
                : list.map((s) => (
                    <tr key={s.id} style={{ cursor: 'default' }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{s.flag} {s.name}</div>
                        <div className="faint" style={{ fontSize: 12 }}>{s.code} · {s.driver}</div>
                      </td>
                      <td className="tabular" style={{ fontSize: 13 }}>{s.host}:{s.port}</td>
                      <td>
                        <span className={`pill ${s.status === 'online' ? 'ok' : 'bad'}`}>
                          {s.status === 'online' ? 'online' : 'offline'}
                        </span>
                        <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>{ago(s.last_seen_at ?? null)}</div>
                      </td>
                      <td className="tabular">{s.ping_ms ?? '—'} ms</td>
                      <td className="tabular">{s.peers_online}</td>
                      <td className="tabular">{s.configs}/{s.max_peers}</td>
                      <td style={{ minWidth: 90 }}>
                        <div className="tabular" style={{ fontSize: 12 }}>{s.load}%</div>
                        <Bar value={s.load} tone={s.load_level === 'low' ? 'ok' : s.load_level === 'medium' ? 'warn' : 'bad'} />
                      </td>
                      <td><Toggle label="Активен" on={Boolean(s.is_active)} onChange={(v) => toggle(s, v)} /></td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="faint" style={{ fontSize: 13, marginTop: 12 }}>
        Новый сервер: установите на VPS <code>vpn-agent/install.sh</code>, затем добавьте его здесь — публичный ключ и порт
        backend получит у агента сам.
      </p>
      {adding && <AddServer onClose={() => setAdding(false)} onDone={load} onError={onError} />}
    </>
  )
}

const EMPTY = { code: '', name: '', country: '', city: '', host: '', agent_url: 'http://127.0.0.1:8787', agent_token: '', max_peers: '250' }

function AddServer({ onClose, onDone, onError }: { onClose: () => void; onDone: () => void; onError: (e: unknown) => void }) {
  const [f, setF] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })

  const submit = async () => {
    setBusy(true)
    try {
      await adminApi.addServer({ ...f, driver: 'agent', country: f.country.toUpperCase(), max_peers: Number(f.max_peers), city: f.city || null })
      toast('Сервер добавлен')
      onDone()
      onClose()
    } catch (e) {
      onError(e)
    } finally {
      setBusy(false)
    }
  }

  const field = (k: keyof typeof EMPTY, label: string, placeholder = '', type = 'text') => (
    <div className="field">
      <label>{label}</label>
      <input className="input" type={type} placeholder={placeholder} value={f[k]} onChange={set(k)} />
    </div>
  )

  return (
    <Sheet title="Новый сервер" onClose={onClose}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {field('code', 'Код', 'de-fra-1')}
        {field('name', 'Название', 'Germany')}
        {field('country', 'Страна (ISO)', 'DE')}
        {field('city', 'Город', 'Frankfurt')}
      </div>
      {field('host', 'Публичный IP / домен для клиентов', '203.0.113.10')}
      {field('agent_url', 'URL агента', 'https://node1.example.com')}
      {field('agent_token', 'Токен агента', 'из /etc/nova-agent.env', 'password')}
      {field('max_peers', 'Максимум конфигураций', '250', 'number')}
      <button className="btn primary block" disabled={busy || !f.code || !f.name || !f.host || !f.agent_token} onClick={submit}>
        {busy ? <span className="spinner" /> : 'Проверить агент и добавить'}
      </button>
    </Sheet>
  )
}
