import { test, expect } from '@playwright/test'
import { resolve } from 'node:path'

for (const width of [390, 800]) {
  test(`station recovers and selects user cards at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    let localOnline = false,
      mainOnline = false,
      reads = 0,
      writes = 0
    const state = {
      name: 'Packing station',
      locked: true,
      user: null,
      users: [
        { id: 'alice', username: 'Alice', avatar_version: '1' },
        { id: 'bob', username: 'bob_with_a_long_username_for_the_packing_station' },
      ],
      single_user_id: null,
      printers: [],
      removed_printers: [],
      csrf_token: 'fixture',
      stop_policy: {},
      pin_keypad: { enabled: true, shuffle: 'none' },
    }
    await page.route('http://localhost:12345/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.startsWith('/api/') && route.request().method() !== 'GET') writes++
      if (path === '/api/health')
        return localOnline
          ? route.fulfill({ json: { healthy: true } })
          : route.abort('connectionrefused')
      if (path === '/api/station') {
        reads++
        return localOnline
          ? route.fulfill({ json: { ...state, online: mainOnline } })
          : route.abort('connectionrefused')
      }
      if (path.includes('/avatar')) return route.fulfill({ status: 404 })
      if (path === '/api/station/unlock')
        return route.fulfill({ status: 403, json: { detail: 'Incorrect PIN' } })
      if (path.startsWith('/assets/'))
        return route.fulfill({ path: resolve(`dist-companion${path}`) })
      if (path === '/')
        return route.fulfill({
          path: resolve('dist-companion/companion.html'),
          contentType: 'text/html',
        })
      return route.abort()
    })
    await page.goto('http://localhost:12345/')
    const indicator = page.locator('.station-connection')
    await expect(indicator).toHaveText('Reconnecting to companion…')
    await expect(page.getByRole('button', { name: 'Unlock', exact: true })).toBeDisabled()
    localOnline = true
    await expect(indicator).toHaveText('Main server offline · Reconnecting…', { timeout: 12000 })
    mainOnline = true
    await expect(indicator).toHaveText('Main server connected', { timeout: 12000 })
    await expect(page.getByRole('alert')).toHaveCount(0)
    const unlock = page.getByRole('button', { name: 'Unlock', exact: true })
    const box = (await unlock.boundingBox())!
    expect(Math.abs(box.x + box.width / 2 - width / 2)).toBeLessThan(2)
    const footer = (await page.locator('.station-footer').boundingBox())!
    expect(footer.y + footer.height).toBeCloseTo(800, 0)
    await expect(page.getByRole('link', { name: 'Source', exact: true })).toBeVisible()
    await unlock.click()
    const dialog = page.getByRole('dialog', { name: 'Unlock station' })
    const pin = dialog.getByLabel('PIN', { exact: true })
    await expect(pin).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Alice', exact: true })).toBeVisible()
    await expect(dialog.locator('.user-avatar img')).toHaveCount(0)
    await page.screenshot({
      path: `test-results/station-user-cards-${width}.png`,
      animations: 'disabled',
    })
    await dialog.getByRole('button', { name: 'Alice', exact: true }).click()
    await expect(pin).toBeFocused()
    await pin.fill('1234')
    await dialog.getByRole('button', { name: 'Unlock', exact: true }).click()
    await expect(dialog.getByRole('alert')).toHaveText('Incorrect PIN')
    const before = reads
    await expect.poll(() => reads).toBeGreaterThan(before)
    await expect(dialog.getByRole('alert')).toHaveText('Incorrect PIN')
    await dialog.getByRole('button', { name: 'Change user', exact: true }).click()
    await expect(pin).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Alice', exact: true })).toBeFocused()
    await dialog
      .getByRole('button', {
        name: 'bob_with_a_long_username_for_the_packing_station',
        exact: true,
      })
      .click()
    await expect(pin).toHaveValue('')
    const submit = (await dialog
      .getByRole('button', { name: 'Unlock', exact: true })
      .boundingBox())!
    expect(Math.abs(submit.x + submit.width / 2 - width / 2)).toBeLessThan(2)
    await page.screenshot({
      path: `test-results/station-pin-step-${width}.png`,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    localOnline = false
    await expect(indicator).toHaveText('Reconnecting to companion…', { timeout: 12000 })
    localOnline = true
    await expect(indicator).toHaveText('Main server connected', { timeout: 12000 })
    expect(writes).toBe(1)
  })
}
