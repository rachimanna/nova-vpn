// Thin typed wrapper over Telegram.WebApp. Every call is guarded so the app also runs in a plain browser.

type HapticImpact = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'
type HapticNotice = 'error' | 'success' | 'warning'

interface TgButton {
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
}

interface TgWebApp {
  initData: string
  initDataUnsafe: { user?: { id: number; first_name?: string; username?: string; photo_url?: string } }
  platform: string
  version: string
  colorScheme: 'light' | 'dark'
  isVersionAtLeast(v: string): boolean
  ready(): void
  expand(): void
  disableVerticalSwipes?(): void
  setHeaderColor?(color: string): void
  setBackgroundColor?(color: string): void
  setBottomBarColor?(color: string): void
  onEvent(event: string, cb: () => void): void
  offEvent(event: string, cb: () => void): void
  showConfirm?(message: string, cb: (ok: boolean) => void): void
  openLink?(url: string, options?: { try_instant_view?: boolean }): void
  downloadFile?(params: { url: string; file_name: string }, cb?: (accepted: boolean) => void): void
  BackButton?: TgButton
  HapticFeedback?: {
    impactOccurred(style: HapticImpact): void
    notificationOccurred(type: HapticNotice): void
    selectionChanged(): void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TgWebApp }
  }
}

export const tg: TgWebApp | undefined = window.Telegram?.WebApp

/** True only when opened from Telegram (initData present). */
export const inTelegram = Boolean(tg?.initData)

const atLeast = (v: string) => Boolean(tg?.isVersionAtLeast?.(v))

export function initTelegram() {
  if (!tg) return
  tg.ready()
  tg.expand()
  if (atLeast('7.7')) tg.disableVerticalSwipes?.()
}

export function paintChrome(color: string) {
  if (!tg || !atLeast('6.1')) return
  try {
    tg.setHeaderColor?.(color)
    tg.setBackgroundColor?.(color)
    if (atLeast('7.10')) tg.setBottomBarColor?.(color)
  } catch {
    /* older clients reject custom colors */
  }
}

export const haptic = {
  tap: (style: HapticImpact = 'light') => atLeast('6.1') && tg?.HapticFeedback?.impactOccurred(style),
  notify: (type: HapticNotice) => atLeast('6.1') && tg?.HapticFeedback?.notificationOccurred(type),
  select: () => atLeast('6.1') && tg?.HapticFeedback?.selectionChanged(),
}

export function confirm(message: string): Promise<boolean> {
  if (tg?.showConfirm && atLeast('6.2')) {
    return new Promise((resolve) => tg!.showConfirm!(message, resolve))
  }
  return Promise.resolve(window.confirm(message))
}

export function openLink(url: string) {
  if (tg?.openLink) tg.openLink(url)
  else window.open(url, '_blank', 'noopener')
}

/** Telegram >= 8.0 can save files natively; otherwise fall back to a Blob download. */
export function downloadText(text: string, fileName: string, absoluteUrl?: string) {
  if (absoluteUrl && tg?.downloadFile && atLeast('8.0')) {
    tg.downloadFile({ url: absoluteUrl, file_name: fileName })
    return
  }
  const blob = new Blob([text], { type: 'application/octet-stream' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

export function onBackButton(cb: () => void): () => void {
  const bb = tg?.BackButton
  if (!bb || !atLeast('6.1')) return () => {}
  bb.onClick(cb)
  bb.show()
  return () => {
    bb.offClick(cb)
    bb.hide()
  }
}

export type Platform = 'ios' | 'android' | 'windows' | 'macos'

export function detectPlatform(): Platform {
  const p = tg?.platform ?? ''
  if (p === 'ios') return 'ios'
  if (p === 'android' || p === 'android_x') return 'android'
  if (p === 'macos') return 'macos'
  if (p === 'tdesktop') return navigator.userAgent.includes('Mac') ? 'macos' : 'windows'
  const ua = navigator.userAgent
  if (/iPhone|iPad|iPod/.test(ua)) return 'ios'
  if (/Android/.test(ua)) return 'android'
  if (/Mac/.test(ua)) return 'macos'
  return 'windows'
}
