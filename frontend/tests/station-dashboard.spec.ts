import { test, expect } from '@playwright/test'
import { resolve } from 'node:path'

for (const width of [1024, 390]) {
  test(`operational dashboard and minimal mode at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 600 })
    let details = true,
      online = true
    const dashboard = {
      held: false,
      cartridge_check_pending: false,
      queued_labels: 12,
      shared_queued_labels: 4,
      printed_last_24h: 68,
      cartridge: {
        name: 'White packing tape',
        profile_name: 'Black on white · 24 mm',
        remaining_mm: 6150,
        nominal_length_mm: 8000,
        uncertain: false,
        foreground: '#000000',
        background: '#ffffff',
      },
      active_batch: { total_labels: 8, confirmed_labels: 0, state: 'printing' },
      last_batch: null,
    }
    await page.route('http://localhost:12345/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/station')
        return route.fulfill({
          json: {
            name: 'Packing station',
            locked: true,
            online,
            user: null,
            users: [],
            removed_printers: [],
            csrf_token: 'fixture',
            stop_policy: {},
            printers: [
              {
                local_id: 'left',
                id: 'one',
                name: 'Packing labels',
                status: { connected: true, tape_width_mm: 24 },
                blocked: false,
                printing: true,
                ...(details ? { dashboard, snapshot_age_seconds: online ? 0 : 90 } : {}),
              },
              {
                local_id: 'right',
                id: 'two',
                name: 'Small labels',
                status: { connected: true, tape_width_mm: 12 },
                blocked: false,
                printing: false,
                ...(details
                  ? {
                      dashboard: {
                        ...dashboard,
                        held: true,
                        active_batch: null,
                        last_batch: {
                          state: 'printed',
                          total_labels: 6,
                          confirmed_labels: 6,
                          finished_at: 1794211200,
                        },
                        cartridge: { ...dashboard.cartridge, remaining_mm: 900 },
                      },
                      snapshot_age_seconds: online ? 0 : 90,
                    }
                  : {}),
              },
            ],
          },
        })
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
    await expect(page.getByText('Active batch', { exact: true })).toBeVisible()
    await expect(page.getByText('On hold', { exact: true })).toBeVisible()
    await expect(page.getByText('6 labels completed', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Controls', exact: true })).toHaveCount(0)
    await page.locator('.station-printer').evaluateAll(async (cards) => {
      await Promise.all(
        cards.flatMap((card) => card.getAnimations().map((animation) => animation.finished)),
      )
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    if (width === 1024) {
      const cards = await page.locator('.station-printer').all()
      const first = (await cards[0].boundingBox())!
      const second = (await cards[1].boundingBox())!
      expect(first.y).toBeCloseTo(second.y, 0)
      expect(second.x - first.x - first.width).toBeGreaterThanOrEqual(16)
      const footer = (await page.locator('.station-connection').boundingBox())!
      expect(Math.max(first.y + first.height, second.y + second.height)).toBeLessThan(footer.y)
    }
    await page.screenshot({
      path: `test-results/station-dashboard-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    online = false
    await expect(page.getByText('Last known server data', { exact: true })).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Unlock', exact: true })).toBeDisabled()
    details = false
    online = true
    await expect(page.locator('.printer-telemetry')).toHaveCount(0)
    await expect(page.locator('.station-printer')).toHaveCount(2)
    await expect(page.locator('.station-connection')).toHaveText('Main server connected')
  })
}
