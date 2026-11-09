import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

async function station(page: Page) {
  const html = readFileSync(resolve('dist-companion/companion.html'), 'utf8')
  const state = {
    build: 'a'.repeat(64),
    shellBuild: 'a'.repeat(64),
    navigationBuild: '',
    phase: 'ready',
    locked: true,
    requests: 0,
    writes: 0,
    navigations: 0,
    shellChecks: 0,
  }
  await page.route('http://localhost:12345/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/') && request.method() !== 'GET') state.writes++
    if (path === '/api/health')
      return route.fulfill({ status: state.phase === 'down' ? 503 : 200, json: { healthy: true } })
    if (path === '/api/station/activity')
      return route.fulfill({ json: { lock_remaining_seconds: 300 } })
    if (path === '/api/station') {
      state.requests++
      if (state.phase !== 'ready')
        return route.fulfill({ status: 503, json: { detail: 'Update validation in progress' } })
      return route.fulfill({
        json: {
          frontend_build: state.build,
          name: 'Packing station',
          online: true,
          locked: state.locked,
          user: null,
          users: [{ id: 'alice', username: 'Alice' }],
          single_user_id: null,
          printers: [],
          removed_printers: [],
          csrf_token: 'fixture',
          stop_policy: {},
          pin_keypad: { enabled: false, shuffle: 'none' },
        },
      })
    }
    if (path.startsWith('/assets/'))
      return route.fulfill({ path: resolve(`dist-companion${path}`) })
    if (path === '/') {
      if (request.isNavigationRequest()) state.navigations++
      else state.shellChecks++
      const build =
        request.isNavigationRequest() && state.navigationBuild
          ? state.navigationBuild
          : state.shellBuild
      return route.fulfill({
        contentType: 'text/html',
        body: html.replace(/(<meta name="app-build" content=")[^"]+/, `$1${build}`),
      })
    }
    return route.abort()
  })
  await page.goto('http://localhost:12345/')
  await expect(page.locator('.station-connection')).toHaveText('Main server connected')
  return state
}

test('update restart and validation recover and reload the locked kiosk once', async ({ page }) => {
  const state = await station(page)
  state.phase = 'down'
  await expect(page.locator('.station-connection')).toHaveText('Reconnecting to companion…', {
    timeout: 10000,
  })
  state.build = state.shellBuild = 'b'.repeat(64)
  state.phase = 'validation'
  const reads = state.requests
  await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(reads)
  expect(state.navigations).toBe(1)
  state.phase = 'ready'
  await expect.poll(() => state.navigations, { timeout: 10000 }).toBe(2)
  await expect(page.locator('meta[name="app-build"]')).toHaveAttribute('content', state.build)
  await expect(page.locator('.station-connection')).toHaveText('Main server connected')
  const after = state.requests
  await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(after)
  expect(state.navigations).toBe(2)
  expect(state.writes).toBe(0)
})

test('reload waits for a locked station and a closed PIN dialog', async ({ page }) => {
  const state = await station(page)
  await page.getByRole('button', { name: 'Unlock', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Unlock station', exact: true })
  await dialog.getByRole('button', { name: 'Alice', exact: true }).click()
  await dialog.getByLabel('PIN', { exact: true }).fill('1234')
  state.build = state.shellBuild = 'b'.repeat(64)
  let reads = state.requests
  await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(reads)
  expect(state.navigations).toBe(1)
  await expect(dialog.getByLabel('PIN', { exact: true })).toHaveValue('1234')
  state.locked = false
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  reads = state.requests
  await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(reads)
  expect(state.navigations).toBe(1)
  state.locked = true
  await expect.poll(() => state.navigations, { timeout: 10000 }).toBe(2)
  expect(state.writes).toBe(0)
})

test('a stale shell cannot cause an automatic reload loop', async ({ page }) => {
  const state = await station(page)
  state.build = 'b'.repeat(64)
  let reads = state.requests
  await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(reads + 1)
  expect(state.navigations).toBe(1)
  // The validation fetch sees the new shell, but a broken proxy serves the old
  // shell on navigation. Remember the attempted transition across that reload.
  state.shellBuild = state.build
  state.navigationBuild = 'a'.repeat(64)
  await expect.poll(() => state.navigations, { timeout: 10000 }).toBe(2)
  reads = state.requests
  await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(reads + 1)
  expect(state.navigations).toBe(2)
  expect(state.writes).toBe(0)
})

test('reload waits for a pending lock request without replaying it', async ({ page }) => {
  const state = await station(page)
  state.locked = false
  const lock = page.getByRole('button', { name: 'Lock', exact: true })
  await expect(lock).toBeVisible({ timeout: 10000 })
  let finish!: () => void
  let lockWrites = 0
  const gate = new Promise<void>((resolve) => {
    finish = resolve
  })
  await page.route('**/api/station/lock', async (route) => {
    state.writes++
    lockWrites++
    state.locked = true
    await gate
    await route.fulfill({ json: { ok: true } })
  })
  await lock.click()
  await expect.poll(() => lockWrites).toBe(1)
  state.build = state.shellBuild = 'b'.repeat(64)
  const reads = state.requests
  try {
    await expect.poll(() => state.requests, { timeout: 10000 }).toBeGreaterThan(reads + 1)
    expect(state.navigations).toBe(1)
  } finally {
    finish()
  }
  await expect.poll(() => state.navigations, { timeout: 10000 }).toBe(2)
  expect(lockWrites).toBe(1)
})
