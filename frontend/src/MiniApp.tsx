import { Send, WifiOff } from 'lucide-react'
import { AddDeviceSheet } from './components/AddDeviceSheet'
import { BottomNav } from './components/BottomNav'
import { ConfigSheet } from './components/ConfigSheet'
import { Logo } from './components/ui'
import { useStore } from './lib/store'
import { Connect } from './screens/Connect'
import { Home } from './screens/Home'
import { Profile } from './screens/Profile'
import { Servers } from './screens/Servers'

export function MiniApp() {
  const { tab, error, me, refresh } = useStore()

  if (error && !me) {
    const auth = error.status === 401
    return (
      <div className="app">
        <div className="center-screen">
          <span className="brand-mark" style={{ width: 64, height: 64, borderRadius: 20 }}>
            {auth ? <Logo size={32} /> : <WifiOff size={28} />}
          </span>
          <h2 style={{ fontSize: 22 }}>{auth ? 'Откройте NOVA VPN в Telegram' : 'Нет соединения'}</h2>
          <p className="muted" style={{ maxWidth: 300 }}>
            {auth ? 'Приложение работает внутри Telegram: запустите бота и нажмите «Открыть NOVA VPN».' : error.message}
          </p>
          {auth ? (
            <span className="pill"><Send size={13} /> Telegram Mini App</span>
          ) : (
            <button className="btn primary" onClick={refresh}>Повторить</button>
          )}
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="app" key={tab}>
        {tab === 'home' && <Home />}
        {tab === 'servers' && <Servers />}
        {tab === 'connect' && <Connect />}
        {tab === 'profile' && <Profile />}
      </div>
      <BottomNav />
      <ConfigSheet />
      <AddDeviceSheet />
    </>
  )
}
