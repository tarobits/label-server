import { onScopeDispose, ref, watch, type Ref } from 'vue'

// Share admission between template cards and saved-label thumbnails. The server
// still enforces its own limit across tabs, users and other rendering endpoints.
let active = 0
const waiting: Array<() => void> = []

function slot(signal: AbortSignal): Promise<() => void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      const index = waiting.indexOf(start)
      if (index >= 0) waiting.splice(index, 1)
      reject(signal.reason)
    }
    const start = () => {
      signal.removeEventListener('abort', abort)
      active++
      resolve(() => {
        active--
        waiting.shift()?.()
      })
    }
    if (signal.aborted) return reject(signal.reason)
    if (active < 2) start()
    else {
      waiting.push(start)
      signal.addEventListener('abort', abort, { once: true })
    }
  })
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      reject(signal.reason)
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, ms)
    if (signal.aborted) abort()
    else signal.addEventListener('abort', abort, { once: true })
  })
}

async function load(url: string, signal: AbortSignal): Promise<Blob> {
  const release = await slot(signal)
  try {
    for (let attempt = 0; ; attempt++) {
      signal.throwIfAborted()
      const controller = new AbortController()
      const abort = () => controller.abort()
      signal.addEventListener('abort', abort, { once: true })
      const timeout = setTimeout(abort, 20000)
      let delay = 0
      try {
        const response = await fetch(url, {
          signal: controller.signal,
          credentials: 'same-origin',
          cache: 'no-store',
        })
        if (response.ok) return await response.blob()
        const retryAfter = response.headers.get('Retry-After')
        delay =
          retryAfter === null
            ? 1000
            : /^\d+$/.test(retryAfter)
              ? Number(retryAfter) * 1000
              : Date.parse(retryAfter) - Date.now()
        // Bound retries; permanent errors and long maintenance outages retain
        // the existing manual retry control instead of retrying indefinitely.
        if (
          ![429, 503].includes(response.status) ||
          attempt >= 3 ||
          !Number.isFinite(delay) ||
          delay > 30000
        )
          throw new Error(`Preview request failed: ${response.status}`)
        await response.body?.cancel()
      } finally {
        clearTimeout(timeout)
        signal.removeEventListener('abort', abort)
      }
      await pause(Math.max(250, delay), signal)
    }
  } finally {
    release()
  }
}

export function usePreview(source: Ref<string>, target: Ref<HTMLElement | null>) {
  const image = ref('')
  const failed = ref(false)
  const visible = ref(false)
  const retry = ref(0)
  const stop = watch(
    target,
    (element, _, cleanup) => {
      if (!element) return
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            visible.value = true
            observer.disconnect()
          }
        },
        { rootMargin: '200px' },
      )
      observer.observe(element)
      cleanup(() => observer.disconnect())
    },
    { flush: 'post' },
  )
  watch(
    [source, visible, retry],
    ([url, shown], _, cleanup) => {
      image.value = ''
      failed.value = false
      if (!shown) return
      const controller = new AbortController()
      let objectUrl = ''
      cleanup(() => {
        controller.abort()
        if (objectUrl) URL.revokeObjectURL(objectUrl)
      })
      void load(url, controller.signal)
        .then((blob) => {
          if (controller.signal.aborted) return
          objectUrl = URL.createObjectURL(blob)
          image.value = objectUrl
        })
        .catch(() => {
          if (!controller.signal.aborted) failed.value = true
        })
    },
    { immediate: true },
  )
  onScopeDispose(stop)
  return { image, failed, reload: () => retry.value++ }
}
