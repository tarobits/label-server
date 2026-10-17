import { test, expect } from './fixtures'
import type { APIRequestContext, Page } from '@playwright/test'

interface RaceStores {
  workspace: {
    refresh(force?: boolean): Promise<void>
    cartridges: { id: string; remaining_mm: number }[]
    busy: boolean
  }
  auth: { refresh(force?: boolean): Promise<void>; user: { role_ids: string[] } }
  resources: { entries: Record<string, { fetchedAt: number }> }
  oldRead?: Promise<void>
  forcedRead?: Promise<void>
  concurrentForcedRead?: Promise<void>
}
declare global {
  interface Window {
    __storeRaces: RaceStores
  }
}

async function installHarness(page: Page) {
  await page.evaluate(() => {
    const app = (
      document.querySelector('#app') as unknown as {
        __vue_app__: { _context: { provides: Record<PropertyKey, unknown> } }
      }
    ).__vue_app__
    const provides = app._context.provides
    const pinia = Reflect.ownKeys(provides)
      .map((key) => provides[key] as { _s?: Map<string, unknown> })
      .find((value) => value?._s instanceof Map)
    if (!pinia?._s) throw new Error('Pinia was not installed')
    window.__storeRaces = {
      workspace: pinia._s.get('workspace'),
      auth: pinia._s.get('auth'),
      resources: pinia._s.get('resources'),
    } as RaceStores
    // Pause the live scheduler as for a background tab. Only explicit reads
    // may repair the stale state in these regressions.
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

async function adminChange(
  request: APIRequestContext,
  resource: string,
  method: string,
  payload: unknown,
  identifier?: string,
) {
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method, payload, identifier },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const result = await request.fetch(
    `/api/admin/${resource}${identifier ? '/' + identifier : ''}`,
    {
      method,
      data: payload,
      headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
    },
  )
  expect(result.ok(), await result.text()).toBeTruthy()
  return result.json()
}

test('saving a cartridge refreshes an already-applied snapshot after an overlapping workspace read', async ({
  page,
}) => {
  await page.goto('/#/cartridges')
  const card = page.getByRole('article').filter({ hasText: 'Yellow cassette 1' })
  await expect(card).toBeVisible()
  await installHarness(page)
  const fetchedAt = await page.evaluate(
    () => window.__storeRaces.resources.entries['/cartridges']!.fetchedAt,
  )
  let cartridgeReads = 0
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/cartridges' && request.method() === 'GET')
      cartridgeReads++
  })
  let release!: () => void
  const held = new Promise<void>((resolve) => (release = resolve))
  let captured!: () => void
  const intercepted = new Promise<void>((resolve) => (captured = resolve))
  let firstStatus = true
  await page.route('**/api/printers/status', async (route) => {
    if (!firstStatus) return route.continue()
    firstStatus = false
    const response = await route.fetch()
    captured()
    await held
    await route.fulfill({ response })
  })
  try {
    await page.evaluate(() => {
      window.__storeRaces.oldRead = window.__storeRaces.workspace.refresh(true)
    })
    await intercepted
    await expect
      .poll(() =>
        page.evaluate(() => window.__storeRaces.resources.entries['/cartridges']!.fetchedAt),
      )
      .toBeGreaterThan(fetchedAt)
    expect(cartridgeReads).toBe(1)
    await card.getByRole('button', { name: 'Correct estimate', exact: true }).click()
    await card.getByLabel('Remaining tape (m)', { exact: true }).fill('2')
    const saved = page.waitForResponse(
      (response) => response.url().includes('/remaining') && response.request().method() === 'PUT',
    )
    await card.getByRole('button', { name: 'Save estimate', exact: true }).click()
    expect((await saved).ok()).toBeTruthy()
    await expect.poll(() => page.evaluate(() => window.__storeRaces.workspace.busy)).toBe(true)
    release()
    await expect(page.getByRole('status')).toContainText('Remaining tape estimate updated.')
    await expect(card.locator('.remaining')).toContainText('2.00 m')
    expect(
      await page.evaluate(() => window.__storeRaces.workspace.cartridges[0]!.remaining_mm),
    ).toBe(2000)
    expect(cartridgeReads).toBe(2)
  } finally {
    release()
  }
})

test('forced session reads after an access mutation share a fresh follow-up instead of an older pending snapshot', async ({
  page,
  request,
}) => {
  const role = await adminChange(request, 'roles', 'POST', {
    name: 'Concurrent access grant',
    permissions: [],
  })
  const users = await (await request.get('/api/admin/users')).json()
  const owner = users.find((user: { username: string }) => user.username === 'owner')
  await page.goto('/#/cartridges')
  await expect(page.getByRole('heading', { name: 'Yellow cassette 1', exact: true })).toBeVisible()
  await installHarness(page)
  let sessionReads = 0
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/auth/session') sessionReads++
  })
  let release!: () => void
  const held = new Promise<void>((resolve) => (release = resolve))
  let captured!: () => void
  const intercepted = new Promise<void>((resolve) => (captured = resolve))
  let firstSession = true
  await page.route('**/api/auth/session', async (route) => {
    if (!firstSession) return route.continue()
    firstSession = false
    const response = await route.fetch()
    const oldSession = await response.json()
    expect(oldSession.user.role_ids).not.toContain(role.id)
    captured()
    await held
    await route.fulfill({ response, json: oldSession })
  })
  try {
    await page.evaluate(() => {
      window.__storeRaces.oldRead = window.__storeRaces.auth.refresh(true)
    })
    await intercepted
    await adminChange(
      request,
      'users',
      'PUT',
      { role_ids: [...owner.role_ids, role.id], disabled: false },
      owner.id,
    )
    await page.evaluate(() => {
      window.__storeRaces.forcedRead = window.__storeRaces.auth.refresh(true)
      window.__storeRaces.concurrentForcedRead = window.__storeRaces.auth.refresh(true)
    })
    expect(sessionReads).toBe(1)
    release()
    await page.evaluate(async () => {
      await Promise.all([
        window.__storeRaces.oldRead,
        window.__storeRaces.forcedRead,
        window.__storeRaces.concurrentForcedRead,
      ])
    })
    expect(await page.evaluate(() => window.__storeRaces.auth.user.role_ids)).toContain(role.id)
    expect(sessionReads).toBe(2)
  } finally {
    release()
  }
})
