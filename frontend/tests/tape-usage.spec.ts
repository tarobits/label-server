import { test, expect } from './fixtures'

test('cartridge prices and requester usage persist with animated details on desktop and mobile', async ({
  page,
  request,
}) => {
  await page.goto('/#/cartridges')
  const cartridge = page.locator('.cartridge-card').filter({ hasText: 'Yellow cassette 1' })
  const summary = cartridge.locator('.cartridge-price > summary')
  await expect(summary).toHaveText('Price: Not set')
  await summary.click()
  const price = cartridge.getByLabel('Cartridge price', { exact: true })
  await expect(price).toBeVisible()
  await price.fill('19.99')
  await cartridge.getByRole('button', { name: 'Save price', exact: true }).click()
  await expect(summary).toHaveText('Price: 19.99 EUR')
  await summary.click()
  await expect(price).toBeHidden()
  await summary.click()
  await expect(price).toHaveValue('19.99')
  await summary.click()
  await expect(price).toBeHidden()

  const profiles = await (await request.get('/api/tape-profiles')).json()
  const job = await request.post('/api/jobs', {
    data: { tape_profile: profiles[0].id, copies: 2, data: { text: 'Usage test' } },
  })
  expect(job.ok()).toBeTruthy()
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => {
      const report = await (await request.get('/api/usage')).json()
      return report.users[0]?.consumed_mm ?? 0
    })
    .toBeGreaterThan(0)
  const usage = await (await request.get('/api/usage')).json()
  expect(usage.users[0].costs.EUR).toBeTruthy()
  expect(usage.users[0].pending_mm).toBe(0)
  await page.getByRole('link', { name: 'Tape usage', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Allocated tape and cost', exact: true }),
  ).toBeVisible()
  await expect(page.locator('.usage-costs')).toContainText('€')
  const detail = page.locator('.usage-entry').first()
  await detail.locator('summary').click()
  await expect(detail.getByText('Cartridge price:', { exact: false })).toBeVisible()
  await expect(detail.getByRole('link', { name: 'Batch details →', exact: true })).toBeVisible()
  await detail.locator('summary').click()
  await expect(detail.getByText('Cartridge price:', { exact: false })).toBeHidden()
  await page.getByRole('combobox', { name: 'View', exact: true }).selectOption('true')
  await expect(page.locator('.usage-entry')).toHaveCount(1)
  await page.screenshot({ path: 'test-results/tape-usage-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/tape-usage-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await detail.locator('summary').click()
  await expect(detail.getByText('Cartridge price:', { exact: false })).toBeVisible()
  await detail.locator('summary').click()
  await expect(detail.getByText('Cartridge price:', { exact: false })).toBeHidden()
})
