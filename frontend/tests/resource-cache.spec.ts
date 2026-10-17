import type { useResourceStore } from '../src/stores/resources'
import { test, expect } from './fixtures'

declare global {
  interface Window {
    resourceTest: ReturnType<typeof useResourceStore>
  }
}

test.beforeEach(async ({ page }) => {
  await page.goto('/#/')
  await expect(page.getByRole('heading', { name: 'Your printers', exact: true })).toBeVisible()
  await page.evaluate(() => {
    // Inspect the installed Pinia instance without adding a test API to the app.
    const root = document.querySelector('#app') as HTMLElement & {
      __vue_app__: { _context: { provides: Record<PropertyKey, unknown> } }
    }
    const provided = root.__vue_app__._context.provides
    const pinia = Reflect.ownKeys(provided)
      .map((key) => provided[key])
      .find((value) => value && typeof value === 'object' && '_s' in value) as {
      _s: Map<string, unknown>
    }
    window.resourceTest = pinia._s.get('resources') as typeof window.resourceTest
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
})

test('concurrent readers share one request and cache empty successful responses', async ({
  page,
}) => {
  let requests = 0
  await page.route('**/api/cache-empty', async (route) => {
    requests++
    await route.fulfill({ json: [] })
  })
  expect(
    await page.evaluate(async () => {
      const [first, second] = await Promise.all([
        window.resourceTest.get('/cache-empty'),
        window.resourceTest.get('/cache-empty'),
      ])
      const again = await window.resourceTest.get('/cache-empty')
      return [first, second, again]
    }),
  ).toEqual([[], [], []])
  expect(requests).toBe(1)
})

test('an invalidated slow read returns the newer snapshot without another request', async ({
  page,
}) => {
  let requests = 0,
    release!: () => void,
    ready!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const captured = new Promise<void>((resolve) => {
    ready = resolve
  })
  await page.route('**/api/cache-race', async (route) => {
    requests++
    if (requests === 1) {
      ready()
      await gate
      await route.fulfill({ json: { revision: 'before-write' } })
    } else await route.fulfill({ json: { revision: 'after-write' } })
  })
  const earlier = page.evaluate(() => window.resourceTest.get('/cache-race'))
  try {
    await captured
    const newer = await page.evaluate(async () => {
      window.resourceTest.invalidate(['/cache-race'])
      return window.resourceTest.get('/cache-race', { force: true })
    })
    expect(newer).toEqual({ revision: 'after-write' })
    release()
    expect(await earlier).toEqual(newer)
    expect(await page.evaluate(() => window.resourceTest.get('/cache-race'))).toEqual(newer)
    expect(requests).toBe(2)
  } finally {
    release()
  }
})

test('clearing the session rejects delayed reads and removes private cache entries', async ({
  page,
}) => {
  let release!: () => void, ready!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const captured = new Promise<void>((resolve) => {
    ready = resolve
  })
  await page.route('**/api/cache-private', async (route) => {
    ready()
    await gate
    await route.fulfill({ json: { private: 'old-session' } })
  })
  const earlier = page.evaluate(async () => {
    try {
      return await window.resourceTest.get('/cache-private')
    } catch (error) {
      return (error as Error).message
    }
  })
  try {
    await captured
    await page.evaluate(() => window.resourceTest.clear())
    release()
    expect(await earlier).toBe('The session changed while loading data.')
    expect(await page.evaluate(() => window.resourceTest.entries)).toEqual({})
  } finally {
    release()
  }
})

test('identical previews share cached rendering until their inputs change', async ({ page }) => {
  let requests = 0
  await page.route('**/api/preview', async (route) => {
    requests++
    await route.fulfill({ json: { result: route.request().postDataJSON() } })
  })
  const results = await page.evaluate(async () => {
    const body = { document: { text: 'same input' } },
      capabilities = { dpi_x: 180 }
    const first = await Promise.all([
      window.resourceTest.preview(body, capabilities),
      window.resourceTest.preview(body, capabilities),
    ])
    const repeat = await window.resourceTest.preview(body, capabilities)
    await window.resourceTest.preview(body, { dpi_x: 360 })
    window.resourceTest.invalidate(['/preview'])
    await window.resourceTest.preview(body, capabilities)
    return [...first, repeat]
  })
  expect(results[0]).toEqual(results[1])
  expect(results[1]).toEqual(results[2])
  expect(requests).toBe(3)
})

test('preview retries keep the original render inputs when the editor changes', async ({
  page,
}) => {
  let release!: () => void,
    ready!: () => void,
    requests = 0
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const captured = new Promise<void>((resolve) => {
    ready = resolve
  })
  await page.route('**/api/preview', async (route) => {
    requests++
    const body = route.request().postDataJSON()
    if (requests === 1) {
      ready()
      await gate
    }
    await route.fulfill({ json: body })
  })
  const earlier = page.evaluate(async () => {
    const body = { text: 'Original text' }
    const result = window.resourceTest.preview(body, {})
    body.text = 'Changed text'
    return result
  })
  try {
    await captured
    await page.evaluate(() => window.resourceTest.invalidate(['/preview']))
    release()
    expect(await earlier).toEqual({ text: 'Original text' })
    expect(requests).toBe(2)
  } finally {
    release()
  }
})
