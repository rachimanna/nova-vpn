import { useState } from 'react'
import { useToast } from '../components/Toast'
import { api, type Device, type DevicePlatform } from './api'
import { confirm, detectPlatform, haptic } from './telegram'
import { useStore } from './store'

export const PLATFORM_NAMES: Record<DevicePlatform, string> = {
  ios: 'iPhone',
  android: 'Android',
  windows: 'Windows',
  macos: 'Mac',
  linux: 'Linux',
  other: 'Устройство',
}

export function useDeviceActions() {
  const { me, refresh, showConfig, serverId, setAddDeviceOpen } = useStore()
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  const run = async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | null> => {
    setBusy(true)
    try {
      const res = await fn()
      if (ok) toast(ok)
      await refresh()
      return res
    } catch (e) {
      toast((e as Error).message, 'error')
      return null
    } finally {
      setBusy(false)
    }
  }

  /** Create a config and immediately show it. */
  const create = async (opts: { platform?: DevicePlatform; server?: number | null; name?: string } = {}) => {
    const server = opts.server ?? serverId
    if (!server) {
      toast('Нет доступных серверов', 'error')
      return null
    }
    const platform = opts.platform ?? detectPlatform()
    const taken = new Set(me?.devices.map((d) => d.name))
    let name = opts.name?.trim() || PLATFORM_NAMES[platform]
    for (let i = 2; taken.has(name) && !opts.name; i++) name = `${PLATFORM_NAMES[platform]} ${i}`
    haptic.tap('medium')
    const device = await run(() => api.createDevice(server, name, platform), 'Конфигурация готова')
    if (device) showConfig(device.id)
    return device
  }

  /** Smart main action: show the existing config or create the first one. */
  const primary = async () => {
    const devices = me?.devices ?? []
    if (devices.length === 0) return create()
    const own = devices.find((d) => d.platform === detectPlatform()) ?? devices[devices.length - 1]
    haptic.tap('medium')
    showConfig(own.id)
  }

  const revoke = async (d: Device) => {
    const ok = await confirm(`Удалить «${d.name}»? Конфигурация на этом устройстве сразу перестанет работать.`)
    if (!ok) return
    await run(() => api.revokeDevice(d.id), 'Устройство удалено')
  }

  const regenerate = async (d: Device, server?: number) => {
    const msg = server
      ? `Перенести «${d.name}» на другой сервер? Старая конфигурация перестанет работать, нужно будет импортировать новую.`
      : `Перевыпустить ключи для «${d.name}»? Старая конфигурация перестанет работать.`
    if (!(await confirm(msg))) return
    const res = await run(() => api.regenerate(d.id, server), server ? 'Сервер изменён' : 'Ключи перевыпущены')
    if (res) showConfig(res.id)
  }

  const addDevice = () => {
    if (me && me.user.devices_active >= me.user.device_limit) {
      toast(`Лимит устройств: ${me.user.device_limit}. Удалите неиспользуемое.`, 'error')
      return
    }
    setAddDeviceOpen(true)
  }

  return { busy, create, primary, revoke, regenerate, addDevice }
}
