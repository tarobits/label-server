import { test, expect } from '@playwright/test'
import { resolve } from 'node:path'
import { languagePicker, selectLanguage, expectLanguage } from './language'

for (const width of [390, 1024]) {
  test(`companion default, account language and delayed save after locking at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 })
    let signedIn = false
    let language = 'en'
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let holdSave = false
    let writes = 0
    await page.route('http://localhost:12345/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/health') return route.fulfill({ json: { healthy: true } })
      if (path === '/api/station')
        return route.fulfill({
          json: {
            name: 'Packing station',
            default_language: 'de',
            online: true,
            locked: !signedIn,
            user: signedIn
              ? {
                  id: 'alice',
                  username: 'Alice',
                  language,
                  permissions: [],
                  location_id: '',
                  printer_permissions: {},
                  groups: {},
                }
              : null,
            users: [{ id: 'alice', username: 'Alice' }],
            single_user_id: 'alice',
            pin_keypad: { enabled: false, shuffle: 'none' },
            lock_remaining_seconds: 300,
            printers: [],
            removed_printers: [],
            csrf_token: 'fixture',
            stop_policy: {},
          },
        })
      if (path === '/api/station/unlock') {
        signedIn = true
        return route.fulfill({ json: { ok: true } })
      }
      if (path === '/api/station/lock') {
        signedIn = false
        return route.fulfill({ json: { ok: true } })
      }
      if (path === '/api/station/language') {
        writes++
        language = route.request().postDataJSON().language
        if (holdSave) await held
        return route.fulfill({ json: { language } })
      }
      if (path === '/api/station/activity')
        return route.fulfill({ json: { lock_remaining_seconds: 300 } })
      if (path.startsWith('/api/proxy/')) return route.fulfill({ json: [] })
      if (path.startsWith('/assets/'))
        return route.fulfill({ path: resolve(`dist-companion${path}`) })
      if (path === '/')
        return route.fulfill({
          path: resolve('dist-companion/companion.html'),
          contentType: 'text/html',
        })
      return route.abort()
    })
    try {
      await page.goto('http://localhost:12345/')
      await expect(page.locator('html')).toHaveAttribute('lang', 'de')
      await expectLanguage(page, 'de')
      const trigger = languagePicker(page)
      const bounds = (await trigger.boundingBox())!
      expect(bounds.x + bounds.width).toBeGreaterThan(width - 45)
      await trigger.focus()
      await trigger.press('ArrowDown')
      await expect(page.getByRole('menuitemradio', { name: 'Deutsch' })).toBeFocused()
      await page.keyboard.press('ArrowUp')
      await page.keyboard.press('Enter')
      await expect(page.locator('html')).toHaveAttribute('lang', 'en')
      await expect(trigger).toBeFocused()
      expect(writes).toBe(0)
      await page.reload()
      await expect(page.locator('html')).toHaveAttribute('lang', 'en')
      await page.getByRole('button', { name: 'Unlock', exact: true }).click()
      await page.locator('input[type="password"]').fill('1234')
      await page.locator('dialog').getByRole('button', { name: 'Unlock', exact: true }).click()
      await expect(page.locator('.station-operator')).toHaveText('Alice')
      await selectLanguage(page, 'de')
      await expect(page.locator('html')).toHaveAttribute('lang', 'de')
      expect(writes).toBe(1)
      await expect(languagePicker(page)).toHaveAttribute('aria-expanded', 'false')
      await languagePicker(page).click()
      await expect(page.getByRole('menu')).toBeVisible()
      await expect(page.getByRole('menu')).not.toHaveClass(/language-menu-enter/)
      await page.screenshot({
        path: `test-results/station-language-${width}.png`,
        animations: 'disabled',
      })
      await page.keyboard.press('Escape')
      await expect(languagePicker(page)).toHaveAttribute('aria-expanded', 'false')
      holdSave = true
      await selectLanguage(page, 'en')
      await expect.poll(() => writes).toBe(2)
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: /^(Sperren|Lock)$/ }).click()
      await expect(page.locator('.station-operator')).toHaveCount(0)
      await expect(page.locator('html')).toHaveAttribute('lang', 'en')
      release()
      await expect(languagePicker(page)).toHaveAttribute('aria-busy', 'false')
      await expect(page.locator('.station-operator')).toHaveCount(0)
      await selectLanguage(page, 'de')
      await expect(page.locator('html')).toHaveAttribute('lang', 'de')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
    } finally {
      release()
      await page.unrouteAll({ behavior: 'wait' })
    }
  })
}
