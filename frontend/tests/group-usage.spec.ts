import { test, expect } from './fixtures'
import { usageSection } from './usage-navigation'

test('group balances, current payers and historical previews stay connected', async ({
  page,
  request,
}) => {
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/price`, {
        data: { price_minor: 2000, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  const response = await request.post('/api/accounts/groups', { data: { name: 'Workshop fund' } })
  expect(response.ok()).toBeTruthy()
  const account = await response.json()
  const job = await request.post('/api/jobs', {
    data: {
      tape_profile: cartridge.profile_id,
      copies: 2,
      data: { text: 'Historic workshop label' },
    },
  })
  expect(job.ok()).toBeTruthy()
  await page.goto('/#/queue')
  await expect(page.locator('.queue-table .payment-attribution')).toHaveText('Payer: owner (user)')
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get('/api/batches')).json())[0]?.state)
    .toBe('printed')
  await page.goto('/#/activity')
  await expect(page.locator('.activity-batch .payment-attribution')).toHaveText(
    'Payer: owner (user)',
  )
  await page.goto(`/#/group-accounts?account=${account.id}`)
  await page.getByRole('button', { name: 'Transfer previous print costs', exact: true }).click()
  const transferDialog = page.getByRole('dialog', { name: 'Previous print costs', exact: true })
  await expect(transferDialog).toBeVisible()
  const historical = page.locator('.historical-charge').first()
  await expect(historical).toContainText('Historic workshop label')
  await expect(historical).toContainText('2 copies')
  const image = historical.getByRole('img', {
    name: 'Label preview: Historic workshop label',
    exact: true,
  })
  await expect(image).toBeVisible()
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await historical
    .getByRole('button', { name: 'Enlarge label preview: Historic workshop label' })
    .click()
  const modal = page.getByRole('dialog', { name: 'Label preview', exact: true })
  await expect(modal).toBeVisible()
  await modal.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(modal).toBeHidden()
  await historical.getByRole('checkbox', { name: 'Historic workshop label', exact: true }).check()
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({
      path: `test-results/group-history-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  }
  await historical.getByRole('button', { name: 'Charge group directly', exact: true }).click()
  await expect(historical).toHaveCount(0)
  await transferDialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(transferDialog).toBeHidden()
  await expect(
    page.getByRole('button', { name: 'Transfer previous print costs', exact: true }),
  ).toBeFocused()
  await page.goto('/#/activity')
  await expect(page.locator('.activity-batch .payment-attribution')).toHaveText(
    'Payer: Workshop fund (group account)',
  )
  await page.goto('/#/usage?section=balances')
  await expect(page.locator('.usage-accounts')).toContainText('Workshop fund')
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await usageSection(page, 'cartridges')
    const row = page.locator('.cartridge-balances tbody tr').filter({ hasText: 'Workshop fund' })
    await expect(row).toContainText(cartridge.name)
    await expect(row).toContainText('Group account')
    await expect(row.getByRole('cell').last()).not.toHaveText('€0.00')
    await page.screenshot({
      path: `test-results/group-usage-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  }
  await page
    .locator('.cartridge-balances')
    .getByRole('link', { name: 'Workshop fund', exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`account=${account.id}`))
  await expect(page.getByRole('heading', { name: 'Balances & charges', exact: true })).toBeVisible()
  await page.goto(`/#/new?template=text&profile=${cartridge.profile_id}`)
  await page.getByRole('combobox', { name: 'Paying account', exact: true }).selectOption(account.id)
  const preview = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/preview') &&
      response.ok() &&
      response.request().postDataJSON()?.data?.text === 'Funding',
  )
  await page.getByLabel('Label text', { exact: true }).fill('Funding')
  await preview
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue/)
  await expect(page.locator('.queue-table .payment-attribution')).toContainText(
    'Payer: Workshop fund (group account) · Awaiting approval',
  )
})
