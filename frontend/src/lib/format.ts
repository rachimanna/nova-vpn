export function bytes(n: number, digits = 1): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  const v = n / 1024 ** i
  return `${v.toFixed(i < 2 ? 0 : v >= 100 ? 0 : digits)} ${units[i]}`
}

export function speed(bytesPerSec: number): string {
  const bits = bytesPerSec * 8
  if (bits < 1e6) return `${(bits / 1e3).toFixed(0)} Kb/s`
  return `${(bits / 1e6).toFixed(bits < 1e8 ? 1 : 0)} Mb/s`
}

export function duration(fromIso: string | null, now = Date.now()): string {
  if (!fromIso) return '—'
  const s = Math.max(0, Math.floor((now - new Date(fromIso).getTime()) / 1000))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(sec)}`
}

export function ago(iso: string | null): string {
  if (!iso) return 'никогда'
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'только что'
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`
  return `${Math.floor(s / 86400)} дн назад`
}

export function date(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}
