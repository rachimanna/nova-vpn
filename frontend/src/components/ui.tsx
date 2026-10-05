import type { CSSProperties, ReactNode } from 'react'
import { haptic } from '../lib/telegram'

export function Logo({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <defs>
        <linearGradient id="nova-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <path d="M12 1.5l2.1 6.6 6.9 2.1-6.9 2.2L12 19l-2.1-6.6L3 10.2l6.9-2.1z" fill="url(#nova-g)" />
      <circle cx="19" cy="19" r="2" fill="url(#nova-g)" opacity=".7" />
    </svg>
  )
}

export function Brand({ right }: { right?: ReactNode }) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">
          <Logo />
        </span>
        NOVA VPN
      </div>
      {right}
    </header>
  )
}

export function Card({
  children,
  className = '',
  style,
  onClick,
}: {
  children: ReactNode
  className?: string
  style?: CSSProperties
  onClick?: () => void
}) {
  return (
    <div className={`card ${className}`} style={style} onClick={onClick}>
      {children}
    </div>
  )
}

export function Skeleton({ h = 16, w = '100%', r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="sk" style={{ height: h, width: w, borderRadius: r }} />
}

export function Bar({ value, tone = '' }: { value: number; tone?: '' | 'ok' | 'warn' | 'bad' }) {
  return (
    <div className={`bar ${tone}`}>
      <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`toggle ${on ? 'on' : ''}`}
      onClick={() => {
        haptic.select()
        onChange(!on)
      }}
    />
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: { value: T; label: ReactNode }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          className={o.value === value ? 'active' : ''}
          onClick={() => {
            if (o.value !== value) haptic.select()
            onChange(o.value)
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Avatar({ url, name, large }: { url?: string | null; name: string; large?: boolean }) {
  const cls = `avatar ${large ? 'lg' : ''}`
  if (url) return <img className={cls} src={url} alt="" referrerPolicy="no-referrer" />
  return <div className={cls}>{(name || '?').slice(0, 1).toUpperCase()}</div>
}

export function Signal({ ping }: { ping: number | null }) {
  const bars = ping == null ? 0 : ping < 40 ? 4 : ping < 80 ? 3 : ping < 150 ? 2 : 1
  const tone = bars >= 3 ? '' : bars === 2 ? 'medium' : 'weak'
  return (
    <span className={`signal ${tone}`} aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <i key={i} className={i < bars ? 'on' : ''} />
      ))}
    </span>
  )
}
