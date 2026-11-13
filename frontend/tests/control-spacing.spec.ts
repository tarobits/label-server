import { readFile } from 'node:fs/promises'
import type { Locator } from '@playwright/test'
import { test, expect } from './fixtures'
import { selectLanguage } from './language'

async function clearance(first: Locator, second: Locator, minimum = 10) {
  await expect(first).toBeVisible()
  await expect(second).toBeVisible()
  await expect
    .poll(async () => {
      const a = (await first.boundingBox())!
      const b = (await second.boundingBox())!
      return Math.max(
        b.x - a.x - a.width,
        a.x - b.x - b.width,
        b.y - a.y - a.height,
        a.y - b.y - b.height,
      )
    })
    .toBeGreaterThanOrEqual(minimum - 0.5)
}

for (const language of ['en', 'de'] as const) {
  for (const width of [390, 1280]) {
    test(`text and actions retain clearance in ${language} at ${width}px`, async ({
      page,
      request,
    }) => {
      await page.setViewportSize({ width, height: 900 })
      const upload = await request.post('/api/font-assets', {
        data: await readFile('../app/fonts/NotoSans-Bold.ttf'),
        headers: { 'Content-Type': 'application/octet-stream' },
      })
      expect(upload.ok(), await upload.text()).toBeTruthy()
      expect((await request.post('/api/test/inbox')).ok()).toBeTruthy()
      await page.goto('/#/account')
      await selectLanguage(page, language)
      const pin = page.getByRole('region', {
        name: language === 'de' ? 'Companion-PIN' : 'Companion PIN',
        exact: true,
      })
      const heading = pin.getByRole('heading')
      const toggle = pin.locator(':scope > button')
      await clearance(heading, toggle, 24)
      await toggle.click()
      await expect(pin.locator('form')).toBeVisible()
      await clearance(heading, toggle, 24)
      await pin.locator('input[autocomplete=current-password]').fill('browser-owner-password')
      await pin.locator('input[autocomplete=new-password]').nth(0).fill('246810')
      await pin.locator('input[autocomplete=new-password]').nth(1).fill('135790')
      await pin.locator('button[type=submit]').click()
      await clearance(heading, pin.getByRole('alert'), 24)
      await clearance(pin.getByRole('alert'), toggle)
      await toggle.click()
      await expect(pin.locator('form')).not.toBeVisible()
      await clearance(heading, toggle, 24)
      await toggle.click()
      await pin.locator('input[autocomplete=current-password]').fill('browser-owner-password')
      await pin.locator('input[autocomplete=new-password]').nth(0).fill('246810')
      await pin.locator('input[autocomplete=new-password]').nth(1).fill('246810')
      await pin.locator('button[type=submit]').click()
      await expect(pin.locator('form')).not.toBeVisible()
      await clearance(heading, pin.getByRole('status'), 24)
      await clearance(pin.getByRole('status'), toggle)
      await pin.screenshot({ path: `test-results/control-spacing-pin-${language}-${width}.png` })

      await page.goto('/#/fonts')
      const actions = page.locator('tbody tr').filter({ has: page.locator('button.danger-text') })
      await actions.locator('button.danger-text').scrollIntoViewIfNeeded()
      await clearance(actions.locator('button').nth(0), actions.locator('button').nth(1))
      await actions.locator('button').nth(0).focus()
      await clearance(actions.locator('button').nth(0), actions.locator('button').nth(1))

      await page.locator('.notification-bell').click()
      const dialog = page.getByRole('dialog')
      const notice = dialog.locator('.notification-list article').first()
      await clearance(notice.locator('button').nth(0), notice.locator('button').nth(1))
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible()

      await page.goto('/#/templates')
      const card = page.locator('.template-card').first()
      await clearance(card.locator(':scope > p.help'), card.locator(':scope > .row'))
      await page.goto('/#/printers')
      const notifications = page.locator('main section.panel').last()
      await clearance(notifications.locator('p.help'), notifications.locator('a.button'))
      await page.goto('/#/templates/new')
      for (const selector of ['.editor-settings-actions', '.editor-add-buttons']) {
        await expect(page.locator(selector)).toBeVisible()
        const buttons = page.locator(selector).getByRole('button')
        expect(await buttons.count()).toBeGreaterThan(1)
        for (let index = 1; index < (await buttons.count()); index++) {
          await clearance(buttons.nth(index - 1), buttons.nth(index))
        }
      }
      await page.screenshot({
        path: `test-results/control-spacing-editor-${language}-${width}.png`,
        animations: 'disabled',
        fullPage: true,
      })
    })
  }
}

test('history loading and failure feedback keep clearance and recover', async ({ page }) => {
  for (const [path, endpoint] of [
    ['/activity', '/api/batches/page'],
    ['/notification-history', '/api/notifications/page'],
    ['/printer-changes', '/api/printer-changes/page'],
  ]) {
    const matchesEndpoint = (url: URL) => url.pathname === endpoint
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route(matchesEndpoint, async (route) => {
      await gate
      await route.fulfill({ status: 503, json: { detail: 'Audit test unavailable' } })
    })
    try {
      await page.goto('/#' + path)
      const panel = page.locator('main section.panel').first()
      await clearance(panel.locator('.pagination').first(), panel.locator('p[role=status]'))
      release()
      await clearance(panel.locator('.pagination').first(), panel.getByRole('alert'))
      await page.unroute(matchesEndpoint)
      await panel.getByRole('alert').getByRole('button').click()
      await expect(panel.getByRole('alert')).not.toBeVisible()
      await expect(panel.locator('p[role=status]')).not.toBeVisible()
    } finally {
      release()
      await page.unrouteAll({ behavior: 'wait' })
    }
  }
})
