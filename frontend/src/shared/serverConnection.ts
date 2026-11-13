import { computed, readonly, ref } from 'vue'
import { t } from './i18n'

export const serverUnavailableMessage = computed(() => t('requestErrors.unavailable'))
const unavailable = ref(false)
const checking = ref(false)
export const serverUnavailable = readonly(unavailable)
export const checkingServer = readonly(checking)
let pending: Promise<boolean> | undefined

// A device can be online while the tunnel or origin is down. Only the server's
// uncached health response proves that it can be reached; proxy HTML does not.
export function checkServer(): Promise<boolean> {
  if (pending) return pending
  checking.value = true
  pending = (async () => {
    try {
      const response = await fetch('/api/health', {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(5000),
      })
      const healthy =
        response.ok &&
        response.headers.get('content-type')?.includes('application/json') &&
        (await response.json()).healthy === true
      unavailable.value = !healthy
    } catch {
      unavailable.value = true
    } finally {
      checking.value = false
      pending = undefined
    }
    return !unavailable.value
  })()
  return pending
}
