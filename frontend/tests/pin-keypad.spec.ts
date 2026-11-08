import { test, expect } from '@playwright/test'
import { resolve } from 'node:path'

test('station header counts down, resets on activity and hides the timer when locked', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 760 })
  let locked = false,
    remaining = 10
  await page.route('http://localhost:12345/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/station') {
      await route.fulfill({
        json: {
          name: 'Packing station',
          online: true,
          locked,
          user: null,
          users: [],
          single_user_id: null,
          printers: [],
          removed_printers: [],
          csrf_token: 'fixture',
          stop_policy: {},
          lock_remaining_seconds: locked ? null : remaining,
        },
      })
    } else if (path === '/api/station/activity') {
      remaining = 300
      await route.fulfill({ json: { ok: true, lock_remaining_seconds: remaining } })
    } else if (path === '/api/station/lock') {
      locked = true
      await route.fulfill({ json: { ok: true } })
    } else if (path.startsWith('/assets/')) {
      await route.fulfill({ path: resolve(`dist-companion${path}`) })
    } else if (path === '/') {
      await route.fulfill({
        path: resolve('dist-companion/companion.html'),
        contentType: 'text/html',
      })
    } else await route.abort()
  })
  await page.goto('http://localhost:12345/')
  const countdown = page.getByRole('timer')
  await expect(countdown).toHaveText('Locks in 0:10')
  await expect(countdown).toHaveText('Locks in 0:09')
  await page.getByRole('heading', { name: 'Packing station' }).click()
  await expect(countdown).toHaveText('Locks in 5:00')
  await page.screenshot({ path: 'test-results/station-lock-countdown.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Lock', exact: true }).click()
  await expect(countdown).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Unlock', exact: true })).toBeVisible()
})

for (const mode of ['disabled', 'none', 'once', 'each_keypress'] as const) {
  test(`companion PIN entry: ${mode}`, async ({ page }) => {
    await page.setViewportSize({ width: mode === 'once' ? 800 : 390, height: 760 })
    let submitted: { user_id: string; pin: string } | undefined
    await page.route('http://localhost:12345/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/station') {
        await route.fulfill({
          json: {
            name: 'Packing station',
            online: true,
            locked: true,
            user: null,
            users: [
              { id: 'alice', username: 'Alice' },
              { id: 'bob', username: 'Bob' },
            ],
            single_user_id: null,
            printers: [],
            removed_printers: [],
            csrf_token: 'fixture',
            stop_policy: {},
            pin_keypad: {
              enabled: mode !== 'disabled',
              shuffle: mode === 'disabled' ? 'none' : mode,
            },
          },
        })
      } else if (path === '/api/station/unlock') {
        submitted = route.request().postDataJSON()
        await route.fulfill({ status: 403, json: { detail: 'Incorrect PIN' } })
      } else if (path.startsWith('/assets/')) {
        await route.fulfill({ path: resolve(`dist-companion${path}`) })
      } else if (path === '/') {
        await route.fulfill({
          path: resolve('dist-companion/companion.html'),
          contentType: 'text/html',
        })
      } else await route.abort()
    })
    await page.goto('http://localhost:12345/')
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Unlock station' })
    const input = dialog.getByLabel('PIN', { exact: true })
    const keypad = dialog.getByRole('group', { name: 'PIN keypad' })
    await expect(input).toHaveValue('')
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    if (mode === 'disabled') {
      await expect(keypad).toHaveCount(0)
      await expect(input).toHaveAttribute('inputmode', 'numeric')
      await input.fill('1234')
    } else {
      await expect(input).toHaveAttribute('inputmode', 'none')
      const order = () => keypad.locator('.pin-digit').allTextContents()
      const initial = await order()
      expect([...initial].sort()).toEqual(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'])
      if (mode === 'none') expect(initial.join('')).toBe('1234567890')
      else expect(initial.join('')).not.toBe('1234567890')
      for (const digit of '1234') {
        const previous = await order()
        await keypad.getByRole('button', { name: digit, exact: true }).click()
        if (mode === 'each_keypress') expect(await order()).not.toEqual(previous)
        else expect(await order()).toEqual(initial)
      }
      await expect(input).toHaveValue('1234')
      expect(submitted).toBeUndefined()
      await keypad.getByRole('button', { name: 'Backspace' }).click()
      await expect(input).toHaveValue('123')
      await keypad.getByRole('button', { name: 'Clear', exact: true }).click()
      await expect(input).toHaveValue('')
      await input.fill('123456789012')
      await keypad.getByRole('button', { name: '1', exact: true }).click()
      await expect(input).toHaveValue('123456789012')
      await input.fill('1234')
      await dialog.getByRole('combobox', { name: 'User', exact: true }).selectOption('bob')
      await expect(input).toHaveValue('')
      if (mode === 'none') expect(await order()).toEqual(initial)
      // A physical keyboard remains usable with the on-screen keypad enabled.
      await input.pressSequentially('1234')
      await expect(input).toHaveValue('1234')
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        page.viewportSize()!.width,
      )
      await page.screenshot({ path: `test-results/pin-keypad-${mode}.png` })
    }
    await dialog.getByRole('button', { name: 'Unlock', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Incorrect PIN')
    expect(submitted?.pin).toBe('1234')
    await expect(input).toHaveValue('')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
    await expect(input).toHaveValue('')
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()
  })
}
