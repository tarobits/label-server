import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`manual-only configuration hides automatic controls at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const [printer] = await (await request.get('/api/printers')).json()
    await page.goto('/#/printers')
    const card = page
      .locator('.printer-device')
      .filter({ has: page.getByRole('heading', { name: printer.name, exact: true }) })
    await card.getByRole('button', { name: 'Configure', exact: true }).click()
    const form = page
      .locator('form')
      .filter({ has: page.getByRole('heading', { name: 'Edit printer', exact: true }) })
    await form.getByRole('checkbox', { name: 'No automatic printing', exact: true }).check()
    await form.getByRole('button', { name: 'Save printer', exact: true }).click()
    await expect(form).toBeHidden()
    await expect(card.getByText('Manual only', { exact: true })).toBeVisible()
    await expect(
      card.getByRole('button', { name: /(?:Hold|Resume) automatic printing/ }),
    ).toHaveCount(0)
    await page.reload()
    await expect(card.getByText('Manual only', { exact: true })).toBeVisible()
    await card.getByRole('button', { name: 'Configure', exact: true }).click()
    await expect(
      form.getByRole('checkbox', { name: 'No automatic printing', exact: true }),
    ).toBeChecked()
    await expect(form).toHaveCSS('opacity', '1')
    await page.screenshot({
      path: `test-results/manual-only-settings-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    await form.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(form).toBeHidden()
    await page.goto('/#/')
    const dashboard = page.getByRole('article', { name: `Printer ${printer.name}`, exact: true })
    await expect(dashboard.getByText('Manual only', { exact: true })).toBeVisible()
    await expect(
      dashboard.getByRole('button', { name: /(?:Hold|Resume) automatic printing/ }),
    ).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })
}
