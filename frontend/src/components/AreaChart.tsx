import { useId, useMemo, useState } from 'react'
import type { Point } from '../lib/api'
import { bytes } from '../lib/format'

const W = 340
const H = 120
const PAD_TOP = 8

function path(values: number[], max: number) {
  if (values.length < 2) return ''
  const step = W / (values.length - 1)
  const pts = values.map((v, i) => [i * step, H - (v / max) * (H - PAD_TOP)] as const)
  // smooth curve: cubic segments with horizontal tangents
  let d = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1]
    const [x1, y1] = pts[i]
    const cx = (x0 + x1) / 2
    d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`
  }
  return d
}

export function AreaChart({ data, range }: { data: Point[]; range: '24h' | '7d' }) {
  const id = useId().replace(/:/g, '')
  const [hover, setHover] = useState<number | null>(null)
  const down = data.map((p) => p.download)
  const up = data.map((p) => p.upload)
  const max = Math.max(1, ...down, ...up) * 1.15

  const { downLine, upLine } = useMemo(() => ({ downLine: path(down, max), upLine: path(up, max) }), [data, max])

  const onMove = (clientX: number, rect: DOMRect) => {
    const i = Math.round(((clientX - rect.left) / rect.width) * (data.length - 1))
    setHover(Math.max(0, Math.min(data.length - 1, i)))
  }

  const label = (iso: string) => {
    const d = new Date(iso)
    return range === '24h'
      ? d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  }

  const hx = hover == null ? 0 : (hover / Math.max(1, data.length - 1)) * 100

  return (
    <div
      className="chart"
      onMouseMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())}
      onMouseLeave={() => setHover(null)}
      onTouchStart={(e) => onMove(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())}
      onTouchMove={(e) => onMove(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())}
      onTouchEnd={() => setHover(null)}
    >
      {hover != null && data[hover] && (
        <div className="chart-tip" style={{ left: `${Math.min(80, Math.max(20, hx))}%` }}>
          <span className="faint">{label(data[hover].ts)}</span> · ↓ {bytes(data[hover].download)} · ↑{' '}
          {bytes(data[hover].upload)}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height: 130 }}>
        <defs>
          <linearGradient id={`d${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#8b5cf6" stopOpacity="0.45" />
            <stop offset="1" stopColor="#8b5cf6" stopOpacity="0" />
          </linearGradient>
          <linearGradient id={`s${id}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#8b5cf6" />
            <stop offset="1" stopColor="#6366f1" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} stroke="var(--border)" strokeDasharray="3 5" />
        ))}
        {downLine && (
          <>
            <path d={`${downLine} L${W},${H} L0,${H} Z`} fill={`url(#d${id})`} />
            <path d={downLine} fill="none" stroke={`url(#s${id})`} strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
          </>
        )}
        {upLine && (
          <path d={upLine} fill="none" stroke="#22d3ee" strokeWidth="1.8" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
        )}
        {hover != null && (
          <line
            x1={(hover / Math.max(1, data.length - 1)) * W}
            x2={(hover / Math.max(1, data.length - 1)) * W}
            y1="0"
            y2={H}
            stroke="var(--text-3)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      <div className="card-row faint" style={{ fontSize: 11, marginTop: 6 }}>
        {data.length > 0 && <span>{label(data[0].ts)}</span>}
        {data.length > 2 && <span>{label(data[Math.floor(data.length / 2)].ts)}</span>}
        <span>сейчас</span>
      </div>
    </div>
  )
}
