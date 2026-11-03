export function pushSupported() {
  return (
    window.isSecureContext &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

export function needsHomeScreen() {
  const ios =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  return (
    ios &&
    !window.matchMedia('(display-mode: standalone)').matches &&
    !(navigator as Navigator & { standalone?: boolean }).standalone
  )
}

export async function pushRegistration(): Promise<ServiceWorkerRegistration> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error('The app is not ready yet. Reload and try again.')),
          10000,
        )
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}

export function applicationKey(value: string): Uint8Array<ArrayBuffer> {
  const raw = atob(value.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (character) => character.charCodeAt(0))
}

export async function subscriptionId(subscription: PushSubscription): Promise<string> {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(subscription.endpoint),
  )
  return (
    'push:' +
    Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  )
}

export async function clearBrowserPush() {
  if (!('serviceWorker' in navigator)) return
  try {
    const registration = await navigator.serviceWorker.getRegistration('/')
    registration?.active?.postMessage({ type: 'CLEAR_NOTIFICATIONS' })
    await (await registration?.pushManager.getSubscription())?.unsubscribe()
  } catch {
    // Server-side revocation already succeeded; browser cleanup is best effort.
  }
}
