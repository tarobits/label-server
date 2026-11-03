import { computed, ref } from 'vue'
import { checkServer, serverUnavailable } from './serverConnection'

const updateAvailable = ref(false)
const dismissed = ref(false)
export const applyingAppUpdate = ref(false)
export const appUpdateError = ref('')
export const showAppUpdate = computed(
  () => updateAvailable.value && !dismissed.value && !serverUnavailable.value,
)
let registration: ServiceWorkerRegistration | undefined
let announcedWorker: ServiceWorker | null = null
let checking: Promise<void> | undefined

function announce(worker: ServiceWorker | null) {
  if (!worker || worker === announcedWorker) return
  announcedWorker = worker
  dismissed.value = false
  updateAvailable.value = true
}

function observeRegistration(value: ServiceWorkerRegistration) {
  if (registration === value) return
  registration = value
  if (value.active) announce(value.waiting)
  function observeInstalling() {
    const worker = value.installing
    worker?.addEventListener('statechange', () => {
      if (worker.state === 'installed' && value.active) announce(value.waiting)
    })
  }
  value.addEventListener('updatefound', observeInstalling)
  observeInstalling()
}

export function registerAppWorker() {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return
  let controller = navigator.serviceWorker.controller
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    const next = navigator.serviceWorker.controller
    // Another window can activate an update. Notify this window, but never
    // reload it: it may have an open editor or an in-progress submission.
    if (controller) announce(next)
    controller = next
  })
  window.addEventListener('load', async () => {
    try {
      // A cached app can open while registration's network update fails. Keep
      // observing its existing worker so updates work again after reconnecting.
      const existing = await navigator.serviceWorker.getRegistration('/')
      if (existing) observeRegistration(existing)
      observeRegistration(
        await navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' }),
      )
    } catch {
      console.warn('The app service worker could not be registered.')
    }
  })
}

export function checkForAppUpdate(): Promise<void> | undefined {
  if (!registration || serverUnavailable.value) return
  if (checking) return checking
  checking = registration
    .update()
    .then(() => {
      if (registration?.active) announce(registration.waiting)
    })
    .catch(() => {
      // A failed update check must not interrupt the currently usable app.
    })
    .finally(() => {
      checking = undefined
    })
  return checking
}

export function dismissAppUpdate() {
  dismissed.value = true
}

async function activate(worker: ServiceWorker): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup()
      reject(new Error('Service worker activation timed out'))
    }, 10000)
    function cleanup() {
      clearTimeout(timer)
      navigator.serviceWorker.removeEventListener('controllerchange', changed)
    }
    function changed() {
      cleanup()
      resolve()
    }
    navigator.serviceWorker.addEventListener('controllerchange', changed)
    try {
      worker.postMessage({ type: 'SKIP_WAITING' })
    } catch (error) {
      cleanup()
      reject(error)
    }
  })
}

export async function reloadForAppUpdate() {
  if (applyingAppUpdate.value) return
  applyingAppUpdate.value = true
  appUpdateError.value = ''
  try {
    if (!(await checkServer())) return
    const waiting = registration?.waiting
    if (waiting) await activate(waiting)
    // Only an explicit click reaches this point. Existing beforeunload guards
    // can still cancel the reload without discarding the mounted editor.
    window.location.reload()
  } catch {
    appUpdateError.value = 'Could not update the app. Try again.'
  } finally {
    applyingAppUpdate.value = false
  }
}
