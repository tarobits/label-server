/// <reference lib="webworker" />
import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
} from 'workbox-precaching'
import type { PrecacheEntry } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: PrecacheEntry[] }

precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Serve the matching cached shell even if the tunnel returns an HTML error page.
// The app probes /api/health before presenting a usable workspace. Hash routes
// all use this entry point; API, downloads, and unknown paths are not rewritten.
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('/index.html'), {
    allowlist: [/^\/(?:index\.html)?(?:\?.*)?$/],
  }),
)

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') event.waitUntil(self.skipWaiting())
  if (event.data?.type === 'CLEAR_NOTIFICATIONS') {
    event.waitUntil(
      self.registration.getNotifications().then((notifications) => {
        notifications.forEach((notification) => notification.close())
      }),
    )
  }
})

self.addEventListener('push', (event) => {
  let payload: Record<string, unknown> = {}
  try {
    const data: unknown = event.data?.json()
    if (data && typeof data === 'object') payload = data as Record<string, unknown>
  } catch {
    // Always display a notification, including for an empty/malformed payload.
  }
  event.waitUntil(
    self.registration.showNotification(
      typeof payload.title === 'string' ? payload.title : "Taro's Label Room",
      {
        body: typeof payload.body === 'string' ? payload.body : 'Open the app to view your alerts.',
        icon: '/pwa-192x192.png',
        tag: typeof payload.tag === 'string' ? payload.tag : undefined,
        data: {
          path:
            typeof payload.path === 'string' && payload.path.startsWith('/#/')
              ? payload.path
              : '/#/',
        },
      },
    ),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const path: unknown = event.notification.data?.path
  const url = new URL(
    typeof path === 'string' && path.startsWith('/#/') ? path : '/#/',
    self.location.origin,
  )
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const existing = windows.find((client) => client.url === url.href)
      if (existing) await existing.focus()
      else await self.clients.openWindow(url.href)
    })(),
  )
})
