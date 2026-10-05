import { Copy, Download, FileText, KeyRound, Link2, QrCode, ShieldAlert } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { absoluteUrl, api, type ConfigPayload } from '../lib/api'
import { downloadText, haptic } from '../lib/telegram'
import { useStore } from '../lib/store'
import { Sheet } from './Sheet'
import { useToast } from './Toast'
import { Segmented, Skeleton } from './ui'

/** Shows how to import a device: subscription (VLESS apps) or file/QR (WireGuard). Never cached or logged. */
export function ConfigSheet() {
  const { configFor, showConfig, me } = useStore()
  const toast = useToast()
  const [cfg, setCfg] = useState<ConfigPayload | null>(null)
  const mobile = /Android|iPhone|iPad/.test(navigator.userAgent)
  const [view, setView] = useState<'qr' | 'text'>(mobile ? 'text' : 'qr')
  const canvas = useRef<HTMLCanvasElement>(null)
  const device = me?.devices.find((d) => d.id === configFor)

  const subUrl = cfg?.subscription_path ? absoluteUrl(cfg.subscription_path) : null
  const qrPayload = subUrl ?? cfg?.config

  useEffect(() => {
    if (configFor == null) return
    setCfg(null)
    api
      .config(configFor)
      .then(setCfg)
      .catch((e) => {
        toast(e.message, 'error')
        showConfig(null)
      })
  }, [configFor])

  useEffect(() => {
    if (view === 'qr' && qrPayload && canvas.current) {
      QRCode.toCanvas(canvas.current, qrPayload, { width: 480, margin: 1, errorCorrectionLevel: 'M' })
    }
  }, [view, qrPayload])

  if (configFor == null) return null

  const close = () => {
    setCfg(null)
    showConfig(null)
  }

  const copy = async (text: string, ok: string) => {
    try {
      await navigator.clipboard.writeText(text)
      haptic.tap('medium')
      toast(ok)
    } catch {
      toast('Не удалось скопировать', 'error')
    }
  }

  const download = () => {
    if (!cfg) return
    haptic.tap('medium')
    downloadText(cfg.config, cfg.filename, absoluteUrl(cfg.download_path))
    toast('Файл конфигурации сохранён')
  }

  const isSub = Boolean(subUrl)

  return (
    <Sheet title={device ? `${device.server.flag} ${device.name}` : 'Подключение'} onClose={close}>
      <Segmented
        value={view}
        onChange={setView}
        options={[
          { value: 'text', label: isSub ? <><Link2 size={15} /> Ссылка</> : <><FileText size={15} /> Файл</> },
          { value: 'qr', label: <><QrCode size={15} /> QR-код</> },
        ]}
      />

      {!cfg ? (
        <div style={{ display: 'grid', placeItems: 'center', padding: 8 }}>
          <Skeleton h={268} w={268} r={22} />
        </div>
      ) : view === 'qr' ? (
        <>
          <div className="qr-box">
            <canvas ref={canvas} />
          </div>
          <p className="muted" style={{ textAlign: 'center', fontSize: 13 }}>
            {isSub ? (
              <>Happ → <b>«+»</b> → <b>«Сканировать QR-код»</b>. Удобно сканировать с экрана другого устройства.</>
            ) : (
              <>WireGuard → <b>«+»</b> → <b>«Сканировать QR-код»</b>. Удобно сканировать с экрана другого устройства.</>
            )}
          </p>
        </>
      ) : isSub ? (
        <>
          <div className="code" style={{ maxHeight: 90 }}>{subUrl}</div>
          <p className="muted" style={{ fontSize: 13 }}>
            Скопируйте ссылку и откройте <b>Happ</b>: он сам предложит добавить подписку из буфера обмена (или «+» →
            «Добавить из буфера»). Подходит и для v2RayTun, Hiddify, v2rayNG, Streisand.
          </p>
        </>
      ) : (
        <>
          <div className="code">{cfg.config.replace(/(PrivateKey|PresharedKey) = .+/g, '$1 = ••••••••••••')}</div>
          <p className="muted" style={{ fontSize: 13 }}>
            Скачайте файл <b>{cfg.filename}</b> и откройте его в WireGuard: «+» → «Импорт из файла».
          </p>
        </>
      )}

      {cfg && isSub && subUrl ? (
        <>
          <button className="btn primary block" onClick={() => copy(subUrl, 'Ссылка-подписка скопирована')}>
            <Copy size={18} /> Скопировать подписку
          </button>
          <button className="btn small ghost" onClick={() => copy(cfg.config, 'Ключ vless:// скопирован')}>
            <KeyRound size={15} /> Скопировать ключ vless://
          </button>
        </>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10 }}>
          <button className="btn primary" onClick={download} disabled={!cfg}>
            <Download size={18} /> Скачать .conf
          </button>
          <button className="btn" onClick={() => cfg && copy(cfg.config, 'Скопировано в буфер обмена')} disabled={!cfg} aria-label="Скопировать">
            <Copy size={18} />
          </button>
        </div>
      )}

      <div className="notice">
        <ShieldAlert size={18} />
        <span>
          {isSub
            ? 'Ссылка — это ваш личный доступ. Не пересылайте её: при утечке перевыпустите ключ в профиле, старая ссылка сразу перестанет работать.'
            : 'Это ваш личный ключ. Не пересылайте файл и не показывайте QR другим людям: при утечке перевыпустите конфигурацию в профиле.'}
        </span>
      </div>
    </Sheet>
  )
}
