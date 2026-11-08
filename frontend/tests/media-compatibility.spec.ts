import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`media tags and cartridge compatibility at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/profiles')
    await page.getByRole('button', { name: 'Add tape profile', exact: true }).click()
    await page.getByLabel('Profile name', { exact: true }).fill('24 × 40 fixed labels')
    await page
      .getByRole('combobox', { name: 'Media family', exact: true })
      .selectOption('fixed_label')
    await page.getByLabel('Stock label length (mm)', { exact: true }).fill('40')
    await page.getByRole('button', { name: 'Save tape profile', exact: true }).click()
    await expect(page.getByText('Fixed labels · 24 × 40 mm', { exact: true })).toBeVisible()
    const stock = (await (await request.get('/api/tape-profiles')).json()).find(
      (item: { name: string }) => item.name === '24 × 40 fixed labels',
    )
    expect(stock.media_family).toBe('fixed_label')
    await request.post('/api/cartridges', {
      data: { profile_id: stock.id, name: 'Fixed stock', nominal_length_mm: 4000 },
    })
    await page.goto('/#/cartridges')
    await page.reload()
    const card = page
      .locator('article')
      .filter({ has: page.getByRole('heading', { name: 'Fixed stock', exact: true }) })
    await expect(
      card.getByRole('button', { name: 'Install cartridge', exact: true }),
    ).toBeDisabled()
    await expect(card.getByText('Fixed labels · 24 × 40 mm', { exact: true })).toBeVisible()
    await card.screenshot({
      path: `test-results/fixed-cartridge-${width}.png`,
      animations: 'disabled',
    })
    await page.goto('/#/templates/new')
    await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(stock.id)
    await expect(page.getByLabel('Label length (mm)', { exact: true })).toHaveValue('40')
    await expect(
      page.getByRole('checkbox', { name: 'Automatic label length', exact: true }),
    ).toBeDisabled()
    await expect(
      page.getByText(/selected printer does not support this media family/).first(),
    ).toBeVisible()
    await page
      .locator('.editor-toolbar')
      .screenshot({ path: `test-results/fixed-design-${width}.png`, animations: 'disabled' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })
}
