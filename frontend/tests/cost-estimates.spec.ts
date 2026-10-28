import { test, expect } from './fixtures'

function displayed(value: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'EUR' }).format(
    Number(value),
  )
}

test('all copies have an approximate cost before submission and in the queue, including CSV runs', async ({
  page,
  request,
}) => {
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  const template = await (await request.get('/api/templates/text')).json()
  await page.goto(`/#/new?template=text&profile=${cartridge.profile_id}`)
  await page.getByLabel('Label text', { exact: true }).fill('Cost preview')
  const cost = page.getByRole('status', { name: 'Estimated cost', exact: true })
  await expect(cost).toContainText('No price set for this tape.')
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/price`, {
        data: { price_minor: 2000, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  await page.reload()
  const first = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/preview') &&
      response.request().postDataJSON()?.data?.text === 'Cost preview' &&
      response.ok(),
  )
  await page.getByLabel('Label text', { exact: true }).fill('Cost preview')
  const one = await (await first).json()
  await expect(cost).toContainText(displayed(one.cost_estimate.quotes[0].minimum))
  const several = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/preview') &&
      response.request().postDataJSON()?.copies === 3 &&
      response.ok(),
  )
  await page.getByLabel('Copies', { exact: true }).fill('3')
  const three = await (await several).json()
  const threePrice = three.cost_estimate.quotes[0].minimum
  expect(Number(threePrice)).toBeGreaterThan(Number(one.cost_estimate.quotes[0].minimum))
  expect(Number(threePrice)).toBeLessThan(Number(one.cost_estimate.quotes[0].minimum) * 3)
  await expect(cost).toContainText(displayed(threePrice))
  await page.setViewportSize({ width: 1440, height: 720 })
  await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeEnabled()
  await page.screenshot({
    path: 'test-results/cost-new-label-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue/)
  await expect(cost).toContainText(displayed(threePrice))
  // The amount is visible without opening label or tape details.
  await expect(page.locator('.queue-label-details[data-expanded="true"]')).toHaveCount(0)

  const prepared = await request.post('/api/runs/prepare', {
    data: {
      name: 'Costed CSV',
      process_name: 'Costed CSV',
      request_key: 'costed-csv',
      template: template.id,
      expected_revision: template.revision,
      tape_profile: cartridge.profile_id,
      csv_text: 'Text\nTiny\nA much longer label\n',
      mapping: { text: 'Text' },
      rows: [
        { source_row: 2, copies: 2 },
        { source_row: 3, copies: 3 },
      ],
    },
  })
  expect(prepared.ok(), await prepared.text()).toBeTruthy()
  const run = (await prepared.json()).run
  const csvPrice = run.cost_estimate.quotes[0].minimum
  await page.goto(`/#/runs/${run.id}`)
  await expect(cost).toContainText(displayed(csvPrice))
  await page.setViewportSize({ width: 390, height: 844 })
  await cost.scrollIntoViewIfNeeded()
  await expect(cost).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/cost-csv-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Submit entire run', exact: true }).click()
  await expect(page.getByText('Run submitted.', { exact: false })).toBeVisible()
  await page.goto('/#/queue')
  const row = page.locator('.queue-run-row').filter({ hasText: 'Costed CSV' })
  await expect(row.getByRole('status', { name: 'Estimated cost', exact: true })).toContainText(
    displayed(csvPrice),
  )
  await expect(page.locator('#queue-profile-filter')).toBeEnabled()
  await page.evaluate(() => {
    ;(document.activeElement as HTMLElement | null)?.blur()
  })
  await page.screenshot({
    path: 'test-results/cost-queue-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
})
