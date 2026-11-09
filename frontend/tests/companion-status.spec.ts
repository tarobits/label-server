import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`companion presence and versions refresh at ${width}px`, async ({ page }) => {
    test.setTimeout(60000)
    await page.setViewportSize({ width, height: 900 })
    let failed = false
    const common = {
      location_id: 'workshop',
      bound_user_id: null,
      revision: 1,
      enabled: true,
      grants: [],
      last_seen_at: 1794211200,
      software_version: '0.13.0-pre4',
      server_version: '0.13.0-pre4',
    }
    const items = [
      { ...common, id: 'one', name: 'Packing station', status: 'online' },
      {
        ...common,
        id: 'two',
        name: 'Workshop station',
        status: 'offline',
        software_version: '0.13.0-pre3',
      },
      {
        ...common,
        id: 'three',
        name: 'New station',
        status: 'never_connected',
        last_seen_at: null,
        software_version: null,
      },
      { ...common, id: 'four', name: 'Retired station', status: 'revoked', enabled: false },
    ]
    await page.route('**/api/companions', (route) =>
      failed
        ? route.fulfill({ status: 503, json: { detail: 'Connection interrupted' } })
        : route.fulfill({ json: items }),
    )
    await page.route('**/api/resource-access', async (route) => {
      const response = await route.fetch()
      const catalog = await response.json()
      await route.fulfill({
        json: { ...catalog, locations: [{ id: 'workshop', name: 'Workshop' }] },
      })
    })
    await page.goto('/#/companions')
    const rows = page.locator('.companion-row')
    const packing = rows.filter({ has: page.getByRole('heading', { name: 'Packing station' }) })
    const workshop = rows.filter({ has: page.getByRole('heading', { name: 'Workshop station' }) })
    await expect(packing.getByText('Online', { exact: true })).toBeVisible()
    await expect(workshop.getByText('Offline', { exact: true })).toBeVisible()
    await expect(workshop.getByText('v0.13.0-pre3', { exact: true })).toBeVisible()
    await expect(workshop.getByText('Version mismatch · Main server v0.13.0-pre4')).toBeVisible()
    await expect(page.getByText('Never connected', { exact: true })).toBeVisible()
    await expect(page.getByText('Key revoked', { exact: true })).toBeVisible()
    await expect(page.getByText('Version unknown', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    const details = (await packing.locator('.companion-details').boundingBox())!
    const controls = (await packing.locator(':scope > .row').boundingBox())!
    expect(
      Math.max(controls.x - details.x - details.width, controls.y - details.y - details.height),
    ).toBeGreaterThanOrEqual(16)
    await page.screenshot({
      path: `test-results/companion-status-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })

    await packing.getByRole('button', { name: 'Settings', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Packing station', exact: true })
    await dialog.getByLabel('Name', { exact: true }).fill('Unsaved station name')
    items[1]!.status = 'online'
    items[1]!.software_version = '0.13.0-pre4'
    await expect(workshop.getByText('Online', { exact: true })).toBeVisible({ timeout: 10000 })
    await expect(workshop.locator('.companion-version-warning')).not.toBeVisible()
    await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Unsaved station name')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()

    failed = true
    await expect(packing.getByText('Status unavailable', { exact: true })).toBeVisible({
      timeout: 10000,
    })
    await expect(packing.getByText('Online', { exact: true })).not.toBeVisible()
    failed = false
    items[1]!.software_version = '0.13.0-pre3'
    await expect(packing.getByText('Online', { exact: true })).toBeVisible({ timeout: 10000 })
    await expect(workshop.locator('.companion-version-warning')).toBeVisible()
    await expect(page.getByText('Connection interrupted', { exact: true })).not.toBeVisible()
  })
}
