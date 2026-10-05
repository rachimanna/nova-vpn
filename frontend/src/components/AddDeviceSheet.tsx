import { Apple, Laptop, Monitor, Smartphone } from 'lucide-react'
import { useState } from 'react'
import type { DevicePlatform } from '../lib/api'
import { PLATFORM_NAMES, useDeviceActions } from '../lib/actions'
import { useStore } from '../lib/store'
import { detectPlatform } from '../lib/telegram'
import { Sheet } from './Sheet'

export const PLATFORM_ICON: Record<DevicePlatform, typeof Smartphone> = {
  ios: Apple,
  android: Smartphone,
  windows: Monitor,
  macos: Laptop,
  linux: Monitor,
  other: Smartphone,
}

const CHOICES: DevicePlatform[] = ['ios', 'android', 'windows', 'macos']

export function AddDeviceSheet() {
  const { addDeviceOpen, setAddDeviceOpen, servers, serverId } = useStore()
  const { create, busy } = useDeviceActions()
  const [platform, setPlatform] = useState<DevicePlatform>(detectPlatform)
  const [server, setServer] = useState<number | null>(null)
  const [name, setName] = useState('')

  if (!addDeviceOpen) return null
  const chosen = server ?? serverId

  const submit = async () => {
    const res = await create({ platform, server: chosen, name: name || undefined })
    if (res) {
      setName('')
      setAddDeviceOpen(false)
    }
  }

  return (
    <Sheet title="Новое устройство" onClose={() => setAddDeviceOpen(false)}>
      <div className="field">
        <label>Платформа</label>
        <div className="chips">
          {CHOICES.map((p) => {
            const Icon = PLATFORM_ICON[p]
            return (
              <button key={p} className={`chip ${platform === p ? 'active' : ''}`} onClick={() => setPlatform(p)}>
                <Icon size={15} /> {PLATFORM_NAMES[p]}
              </button>
            )
          })}
        </div>
      </div>

      <div className="field">
        <label htmlFor="dev-name">Название</label>
        <input
          id="dev-name"
          className="input"
          maxLength={48}
          placeholder={PLATFORM_NAMES[platform]}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div className="field">
        <label>Сервер</label>
        <div className="chips">
          {servers
            ?.filter((s) => s.status === 'online')
            .map((s) => (
              <button key={s.id} className={`chip ${chosen === s.id ? 'active' : ''}`} onClick={() => setServer(s.id)}>
                {s.flag} {s.name}
              </button>
            ))}
        </div>
      </div>

      <button className="btn primary block" onClick={submit} disabled={busy || !chosen}>
        {busy ? <span className="spinner" /> : 'Создать конфигурацию'}
      </button>
    </Sheet>
  )
}
