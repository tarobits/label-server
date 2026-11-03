import { test, expect } from './fixtures'

test('production build exposes an installable manifest and activates its service worker', async ({
  page,
  context,
  baseURL,
}) => {
  await page.goto('/#/')
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
    'href',
    '/manifest.webmanifest',
  )
  const manifestResponse = await page.request.get('/manifest.webmanifest')
  expect(manifestResponse.headers()['content-type']).toContain('application/manifest+json')
  const manifest = await manifestResponse.json()
  expect(manifest).toMatchObject({
    id: '/',
    name: "Taro's Label Room",
    short_name: 'Label Room',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    theme_color: '#1f2937',
    background_color: '#111827',
  })
  expect(manifest.icons).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ sizes: '192x192', purpose: 'any' }),
      expect.objectContaining({ sizes: '512x512', purpose: 'any' }),
      expect.objectContaining({ sizes: '512x512', purpose: 'maskable' }),
    ]),
  )
  for (const icon of manifest.icons) {
    const size = await page.evaluate(async (src: string) => {
      const image = new Image()
      image.src = src
      await image.decode()
      return `${image.naturalWidth}x${image.naturalHeight}`
    }, icon.src)
    expect(size).toBe(icon.sizes)
  }
  const registration = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    return { scope: registration.scope, scriptURL: registration.active?.scriptURL }
  })
  expect(registration).toEqual({ scope: `${baseURL}/`, scriptURL: `${baseURL}/sw.js` })
  await expect(page.getByRole('status', { name: 'App update', exact: true })).not.toBeVisible()
  await page.reload()
  expect(await page.evaluate(() => navigator.serviceWorker.controller?.scriptURL)).toBe(
    `${baseURL}/sw.js`,
  )
  const cdp = await context.newCDPSession(page)
  const { installabilityErrors } = await cdp.send('Page.getInstallabilityErrors')
  // Playwright contexts are incognito, where Chrome disables installation.
  // Every other installability requirement must still pass.
  expect(installabilityErrors.filter((error) => error.errorId !== 'in-incognito')).toEqual([])
  await cdp.detach()
  for (const [name, width, height] of [
    ['phone', 390, 844],
    ['tablet', 820, 1180],
  ] as const) {
    await page.setViewportSize({ width, height })
    await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Desk printer', exact: true })).toBeVisible()
    await expect(page.locator('.route-surface')).toHaveCSS('opacity', '1')
    await page.screenshot({ path: `test-results/pwa-${name}.png`, animations: 'disabled' })
  }
})

test('service worker caches public assets without storing authenticated API responses', async ({
  page,
  context,
}) => {
  await page.goto('/#/')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
  await page.reload()
  const status = await page.evaluate(async () => (await fetch('/api/auth/session')).status)
  expect(status).toBe(200)
  const cachedPaths = await page.evaluate(async () => {
    const requests = await Promise.all(
      (await caches.keys()).map(async (name) => (await caches.open(name)).keys()),
    )
    return requests.flat().map((request) => new URL(request.url).pathname)
  })
  expect(cachedPaths.length).toBeGreaterThan(0)
  expect(cachedPaths.some((path) => path.startsWith('/assets/'))).toBe(true)
  expect(cachedPaths.every((path) => !path.startsWith('/api/'))).toBe(true)

  await context.setOffline(true)
  const apiAvailable = await page.evaluate(() =>
    fetch('/api/auth/session').then(
      () => true,
      () => false,
    ),
  )
  expect(apiAvailable).toBe(false)
})
