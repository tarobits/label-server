import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`move and retire printer registrations at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 900 })
    const source = (await (await request.get('/api/printers')).json())[0]
    const location = { kind: 'location', identifier: crypto.randomUUID(), name: 'Packing room' }
    const preview = await (
      await request.post('/api/resource-access/preview', { data: location })
    ).json()
    expect(
      (
        await request.post('/api/resource-access/apply', {
          data: location,
          headers: { 'X-Access-Confirmation': preview.confirmation_token },
        })
      ).ok(),
    ).toBeTruthy()
    const companion = await (
      await request.post('/api/companions', {
        data: { name: 'Packing station', location_id: location.identifier, grants: [] },
      })
    ).json()
    const registration = await request.post('/api/companion/printers', {
      headers: { Authorization: `Bearer ${companion.api_key}` },
      data: {
        local_id: 'usb-one',
        name: 'New connection',
        driver: source.driver,
        configuration: source.config,
      },
    })
    expect(registration.ok()).toBeTruthy()
    const target = (await registration.json()).printer_id
    await page.goto('/#/printers')
    const card = page
      .locator('.printer-device')
      .filter({ has: page.getByRole('heading', { name: source.name, exact: true }) })
    await card.getByRole('button', { name: 'Move to companion', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Move printer to companion', exact: true })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await card.getByRole('button', { name: 'Move to companion', exact: true }).click()
    await dialog
      .getByRole('combobox', { name: 'Companion printer', exact: true })
      .selectOption(target)
    await expect(dialog.locator('.validation-summary')).toHaveCount(0)
    const moveUrl = `**/api/printers/${source.id}/move-to-companion`
    await page.route(moveUrl, (route) =>
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Finish queued work before moving this printer' }),
      }),
    )
    await dialog.getByRole('button', { name: 'Move printer', exact: true }).click()
    await expect(dialog.getByRole('alert')).toHaveText(
      'Finish queued work before moving this printer',
    )
    await page.unroute(moveUrl)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await card.getByRole('button', { name: 'Move to companion', exact: true }).click()
    await expect(dialog.getByRole('alert')).not.toBeVisible()
    await dialog
      .getByRole('combobox', { name: 'Companion printer', exact: true })
      .selectOption(target)

    await page.screenshot({
      path: `test-results/printer-move-${width}.png`,
      animations: 'disabled',
    })
    await dialog.getByRole('button', { name: 'Move printer', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(page.locator('.printer-device')).toHaveCount(1)
    await expect(
      card.getByRole('button', { name: 'Resume automatic printing', exact: true }),
    ).toBeVisible()
    const printers = await (await request.get('/api/printers')).json()
    expect(printers[0].id).toBe(source.id)
    expect(printers[0].connection_kind).toBe('companion')
    const configure = await card
      .getByRole('button', { name: 'Configure', exact: true })
      .boundingBox()
    const retire = await card
      .getByRole('button', { name: 'Retire printer', exact: true })
      .boundingBox()
    expect(
      Math.max(
        retire!.x - configure!.x - configure!.width,
        retire!.y - configure!.y - configure!.height,
      ),
    ).toBeGreaterThanOrEqual(8)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await page.screenshot({
      path: `test-results/printer-moved-${width}.png`,
      animations: 'disabled',
      fullPage: true,
    })
    await card.getByRole('button', { name: 'Retire printer', exact: true }).click()
    const confirm = page.getByRole('dialog')
    await expect(confirm).toContainText('Print history and audit records will be retained')
    await confirm.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(confirm).not.toBeVisible()
    await card.getByRole('button', { name: 'Retire printer', exact: true }).click()
    await confirm.getByRole('button', { name: 'Retire printer', exact: true }).click()
    await expect(page.locator('.printer-device')).toHaveCount(0)
    await expect(page.getByText('No printers registered.', { exact: true })).toBeVisible()
    expect(await (await request.get('/api/printers')).json()).toEqual([])
  })
}
