import { Globe2, Home, Link2, UserRound } from 'lucide-react'
import { useStore, type Tab } from '../lib/store'
import { haptic } from '../lib/telegram'

const ITEMS: { tab: Tab; label: string; Icon: typeof Home }[] = [
  { tab: 'home', label: 'Главная', Icon: Home },
  { tab: 'servers', label: 'Серверы', Icon: Globe2 },
  { tab: 'connect', label: 'Подключение', Icon: Link2 },
  { tab: 'profile', label: 'Профиль', Icon: UserRound },
]

export function BottomNav() {
  const { tab, go } = useStore()
  return (
    <nav className="nav" aria-label="Навигация">
      {ITEMS.map(({ tab: t, label, Icon }) => (
        <button
          key={t}
          className={`nav-item ${tab === t ? 'active' : ''}`}
          aria-current={tab === t ? 'page' : undefined}
          onClick={() => {
            if (t !== tab) haptic.select()
            go(t)
          }}
        >
          <Icon size={21} strokeWidth={tab === t ? 2.3 : 1.9} />
          {label}
        </button>
      ))}
    </nav>
  )
}
