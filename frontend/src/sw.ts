/// <reference lib="webworker" />
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching'
import type { PrecacheEntry } from 'workbox-precaching'

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: PrecacheEntry[] }

precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Keep the normal waiting lifecycle: updates must not take over an open editor.
// Push handlers and user-controlled activation are added in subsequent steps.
