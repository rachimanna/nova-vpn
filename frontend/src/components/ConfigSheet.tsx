import { Copy, Download, QrCode, ShieldAlert, FileText } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { absoluteUrl, api, type ConfigPayload } from '../lib/api'
import { downloadText, haptic } from '../lib/telegram'
import { useStore } from '../lib/store'
import { Sheet } from './Sheet'
import { useToast } from './Toast'
import { Segmented, Skeleton } from './ui'

/** Shows a device config as QR (scan from another screen) or file. Never cached or logged. */
export function ConfigSheet() {
  const { configFor, showConfig, me } = useStore()
  const toast = useToast()
  const [cfg, setCfg] = useState<ConfigPayload | null>(null)
  const [view, setView] = useState<'qr' | 'file'>(() => (/Android|iPhone|iPad/.test(navigator.userAgent) ? 'file' : 'qr'))
  const canvas = useRef<HTMLCanvasElement>(null)
  const device = me?.devices.find((d) => d.id === configFor)

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
    if (view === 'qr' && cfg && canvas.current) {
      QRCode.toCanvas(canvas.current, cfg.config, { width: 480, margin: 1, errorCorrectionLevel: 'M' })
    }
  }, [view, cfg])

  if (configFor == null) return null

  const close = () => {
    setCfg(null)
    showConfig(null)
  }

  const download = () => {
    if (!cfg) return
    haptic.tap('medium')
    downloadText(cfg.config, cfg.filename, absoluteUrl(cfg.download_path))
    toast('Файл конфигурации сохранён')
  }

  const copy = async () => {
    if (!cfg) return
    try {
      await navigator.clipboard.writeText(cfg.config)
      toast('Скопировано в буфер обмена')
    } catch {
      toast('Не удалось скопировать', 'error')
    }
  }

  return (
    <Sheet title={device ? `${device.server.flag} ${device.name}` : 'Конфигурация'} onClose={close}>
      <Segmented
        value={view}
        onChange={setView}
        options={[
          { value: 'qr', label: <><QrCode size={15} /> QR-код</> },
          { value: 'file', label: <><FileText size={15} /> Файл</> },
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
            WireGuard → <b>«+»</b> → <b>«Сканировать QR-код»</b>.
            <br />
            QR удобно сканировать с экрана компьютера или другого телефона.
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

      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10 }}>
        <button className="btn primary" onClick={download} disabled={!cfg}>
          <Download size={18} /> Скачать .conf
        </button>
        <button className="btn" onClick={copy} disabled={!cfg} aria-label="Скопировать">
          <Copy size={18} />
        </button>
      </div>

      <div className="notice">
        <ShieldAlert size={18} />
        <span>Это ваш личный ключ. Не пересылайте файл и не показывайте QR другим людям: при утечке перевыпустите конфигурацию в профиле.</span>
      </div>
    </Sheet>
  )
}
