import { tg } from './telegram'

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
// Outside Telegram during development the backend (DEV_MODE=true) accepts a fake user id.
const DEV_USER = (import.meta.env.VITE_DEV_USER as string | undefined) ?? (import.meta.env.DEV ? '1' : '')

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export const absoluteUrl = (path: string) => new URL(BASE + path, window.location.origin).toString()

async function request<T>(path: string, init: RequestInit = {}, auth?: Record<string, string>): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...auth }
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } })
  } catch {
    throw new ApiError(0, 'Нет соединения с сервером')
  }
  if (!res.ok) {
    let message = `Ошибка ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

function userAuth(): Record<string, string> {
  if (tg?.initData) return { Authorization: `tma ${tg.initData}` }
  if (DEV_USER) return { 'X-Dev-User': DEV_USER }
  return {}
}

// ---------- types ----------
export type Access = 'active' | 'banned' | 'expired' | 'traffic_exceeded'
export type DevicePlatform = 'ios' | 'android' | 'windows' | 'macos' | 'linux' | 'other'

export interface ShortServer {
  id: number
  code: string
  name: string
  city: string | null
  flag: string
}

export interface Device {
  id: number
  name: string
  platform: DevicePlatform
  protocol: string
  status: 'active' | 'revoked'
  online: boolean
  address: string
  server: ShortServer
  created_at: string
  last_handshake_at: string | null
  session_started_at: string | null
  download: number
  upload: number
}

export interface UserInfo {
  id: number
  tg_id: number
  username: string | null
  first_name: string | null
  photo_url: string | null
  status: Access
  is_banned: boolean
  created_at: string
  expires_at: string
  days_left: number
  device_limit: number
  devices_active: number
  traffic_used: number
  traffic_limit: number
  notifications: boolean
  last_seen_at: string
}

export interface Me {
  user: UserInfo
  vpn: {
    state: 'connected' | 'ready' | 'none'
    online_devices: number
    server: (ShortServer & { ping_ms: number | null }) | null
    session_started_at: string | null
    download: number
    upload: number
    speed: { download: number; upload: number }
  }
  devices: Device[]
  demo: boolean
}

export interface Server extends ShortServer {
  country: string
  protocol: string
  ping_ms: number | null
  load: number
  load_level: 'low' | 'medium' | 'high'
  status: 'online' | 'offline'
}

export interface Point {
  ts: string
  download: number
  upload: number
}

export interface ConfigPayload {
  protocol: 'wireguard' | 'vless'
  config: string
  filename: string
  download_path: string
  subscription_path: string | null
}

// ---------- Mini App API ----------
const u = <T,>(path: string, init?: RequestInit) => request<T>(path, init, userAuth())
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body ? JSON.stringify(body) : undefined })

export const api = {
  me: () => u<Me>('/api/me'),
  setNotifications: (notifications: boolean) => u('/api/me', json('PATCH', { notifications })),
  servers: () => u<Server[]>('/api/servers'),
  stats: (range: '24h' | '7d') => u<{ series: Point[] }>(`/api/stats?range=${range}`),
  createDevice: (server_id: number, name: string, platform: DevicePlatform) =>
    u<Device>('/api/devices', json('POST', { server_id, name, platform })),
  renameDevice: (id: number, name: string) => u<Device>(`/api/devices/${id}`, json('PATCH', { name })),
  revokeDevice: (id: number) => u(`/api/devices/${id}`, json('DELETE')),
  regenerate: (id: number, server_id?: number) => u<Device>(`/api/devices/${id}/regenerate`, json('POST', { server_id })),
  config: (id: number) => u<ConfigPayload>(`/api/devices/${id}/config`),
}

// ---------- Admin API ----------
const ADMIN_KEY = 'nova-admin-token'

export const adminSession = {
  get: () => {
    try {
      return sessionStorage.getItem(ADMIN_KEY)
    } catch {
      return null
    }
  },
  set: (t: string | null) => {
    try {
      if (t) sessionStorage.setItem(ADMIN_KEY, t)
      else sessionStorage.removeItem(ADMIN_KEY)
    } catch {
      /* storage blocked */
    }
  },
}

const a = <T,>(path: string, init?: RequestInit) =>
  request<T>(path, init, { Authorization: `Bearer ${adminSession.get() ?? ''}` })

export interface AdminServer extends Server {
  configs: number
  max_peers: number
  peers_online: number
  host?: string
  port?: number
  driver?: string
  is_active?: boolean
  last_seen_at?: string | null
}

export interface Overview {
  stats: {
    total_users: number
    active_users: number
    banned_users: number
    new_users_24h: number
    active_configs: number
    active_connections: number
    total_traffic: number
    servers_total: number
    servers_online: number
  }
  servers: AdminServer[]
  traffic: Point[]
}

export interface UserDetail {
  user: UserInfo
  devices: Device[]
  traffic: Point[]
}

export const adminApi = {
  login: (password: string) => request<{ token: string }>('/api/admin/login', json('POST', { password })),
  exchange: (token: string) => request<{ token: string }>('/api/admin/exchange', json('POST', { token })),
  overview: () => a<Overview>('/api/admin/overview'),
  users: (q: string, status: string, page: number) =>
    a<{ total: number; page: number; per_page: number; items: UserInfo[] }>(
      `/api/admin/users?${new URLSearchParams({ q, status, page: String(page) })}`,
    ),
  user: (id: number) => a<UserDetail>(`/api/admin/users/${id}`),
  ban: (id: number) => a<UserDetail>(`/api/admin/users/${id}/ban`, json('POST')),
  unban: (id: number) => a<UserDetail>(`/api/admin/users/${id}/unban`, json('POST')),
  patchUser: (id: number, body: { device_limit?: number; traffic_limit_gb?: number; extend_days?: number; reset_traffic?: boolean }) =>
    a<UserDetail>(`/api/admin/users/${id}`, json('PATCH', body)),
  createDevice: (id: number, server_id: number, name: string) =>
    a<UserDetail>(`/api/admin/users/${id}/devices`, json('POST', { server_id, name })),
  revokeDevice: (id: number) => a(`/api/admin/devices/${id}`, json('DELETE')),
  servers: () => a<AdminServer[]>('/api/admin/servers'),
  addServer: (body: Record<string, unknown>) => a<Server>('/api/admin/servers', json('POST', body)),
  patchServer: (id: number, body: Record<string, unknown>) => a(`/api/admin/servers/${id}`, json('PATCH', body)),
}
