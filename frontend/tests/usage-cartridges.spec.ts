import { test, expect } from './fixtures'

test('usage identifies cartridges and filters allocations without changing the account balance', async ({
  page,
  request,
}) => {
  const [first] = await (await request.get('/api/cartridges')).json()
  const secondResponse = await request.post('/api/cartridges', {
    data: {
      profile_id: first.profile_id,
      name: 'Yellow cassette 2',
      nominal_length_mm: 8000,
      price_minor: 2500,
    },
  })
  expect(secondResponse.ok()).toBeTruthy()
  const second = await secondResponse.json()
  await request.put(`/api/cartridges/${first.id}/price`, { data: { price_minor: 2000 } })
  for (const [index, cartridge] of [first, second].entries()) {
    expect(
      (
        await request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })
      ).ok(),
    ).toBeTruthy()
    expect(
      (
        await request.post('/api/jobs', {
          data: {
            tape_profile: cartridge.profile_id,
            copies: 1,
            data: { text: `Cartridge ${index + 1}` },
          },
        })
      ).ok(),
    ).toBeTruthy()
    expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
    await expect
      .poll(async () => {
        const report = await (await request.get('/api/usage')).json()
        return report.entries.filter((entry: { state: string }) => entry.state === 'printed').length
      })
      .toBe(index + 1)
  }
  await page.goto('/#/usage')
  await expect(page.locator('.usage-entry')).toHaveCount(2)
  const balance = await page.locator('.account-balance').innerText()
  await expect(page.locator('.usage-entry').first().locator('summary')).toContainText(
    'Yellow cassette 2',
  )
  await page.getByRole('combobox', { name: 'Cartridge', exact: true }).selectOption(first.id)
  await expect(page.locator('.usage-entry')).toHaveCount(1)
  await expect(page.locator('.account-balance')).toHaveText(balance)
  await expect(page.locator('.usage-entry').locator('summary')).toContainText('Yellow cassette 1')
  await expect(page).toHaveURL(new RegExp(`cartridge=${first.id}`))
  const entry = page.locator('.usage-entry')
  await entry.locator('summary').click()
  await expect(
    entry.getByText('Cartridge: Yellow cassette 1 · Black on Yellow 24 mm', { exact: true }),
  ).toBeVisible()
  await page.screenshot({
    path: 'test-results/usage-cartridge-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await entry.locator('summary').click()
  await expect(entry.getByText('Cartridge price:', { exact: false })).toBeHidden()
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Cartridge', exact: true })).toHaveValue(first.id)
  await expect(page.locator('.usage-entry')).toHaveCount(1)
  await page.getByRole('combobox', { name: 'View', exact: true }).selectOption('all')
  await expect(page.locator('.usage-entry')).toHaveCount(1)
  await expect(page).toHaveURL(/user=all/)
  await expect(page).toHaveURL(new RegExp(`cartridge=${first.id}`))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('combobox', { name: 'Cartridge', exact: true }).selectOption(second.id)
  await expect(page.locator('.usage-entry').locator('summary')).toContainText('Yellow cassette 2')
  await expect(page.locator('.account-balance')).toHaveText(balance)
  await page.screenshot({
    path: 'test-results/usage-cartridge-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('combobox', { name: 'Cartridge', exact: true }).selectOption('')
  await expect(page.locator('.usage-entry')).toHaveCount(2)
  await page.goto('/#/usage?cartridge=untracked')
  await expect(
    page.getByText('No tracked usage for this cartridge.', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('.account-balance')).toHaveText(balance)
})
