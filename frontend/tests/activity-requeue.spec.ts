import { test, expect } from './fixtures'

test('Activity authorizes a selected free retry and safely retries a lost response', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const created = await request.post('/api/jobs', {
    data: {
      tape_profile: profile.id,
      process_name: 'Cable identification',
      data: { text: 'Cable 42' },
      copies: 3,
    },
  })
  expect(created.ok()).toBeTruthy()
  const original = await created.json()
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${original.id}`)).json()).status)
    .toBe('printed')

  await page.goto('/#/activity')
  const details = page.locator('.activity-labels').first()
  const summary = details.locator(':scope > summary')
  await summary.focus()
  await page.keyboard.press('Enter')
  const button = details.getByRole('button', { name: 'Retry labels', exact: true })
  await expect(button).toBeVisible()
  await expect(details).toContainText('3 copies')
  await details.locator('.queue-preview > summary').click()
  const preview = details.getByRole('img', { name: 'Label preview: Cable identification' })
  await expect(preview).toBeVisible()
  await expect
    .poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await button.click()
  const dialog = page.getByRole('dialog', { name: 'Retry labels', exact: true })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.retry-copies input')).toHaveCount(0)
  await dialog.getByLabel('Include confirmed printed copies', { exact: true }).check()
  await dialog.locator('.retry-copies input').first().check()
  await dialog.getByRole('combobox', { name: 'Funding', exact: true }).selectOption('free')
  await expect(dialog.getByRole('combobox', { name: 'Retry cartridge', exact: true })).toBeVisible()
  await page.screenshot({
    path: 'test-results/activity-requeue-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 402, height: 874 })
  await dialog.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(402)
  await page.screenshot({
    path: 'test-results/activity-requeue-mobile.png',
    animations: 'disabled',
  })

  const keys: string[] = []
  await page.route('**/api/batches/*/retry-offers', async (route) => {
    keys.push(route.request().postDataJSON().request_id)
    const response = await route.fetch()
    // The server saved the new copy, but its response did not reach the UI.
    if (keys.length === 1)
      await route.fulfill({ status: 409, json: { detail: 'Response interrupted. Try again.' } })
    else await route.fulfill({ response })
  })
  await dialog.getByRole('button', { name: 'Authorize free retry', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Response interrupted. Try again.')
  await dialog.getByRole('button', { name: 'Authorize free retry', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Free retry queued.' })).toBeVisible()
  const jobs = await (await request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(2)
  const extra = jobs.find((job: { id: string }) => job.id !== original.id)
  expect(extra.copies).toBe(1)
  expect(extra.payload).toEqual(original.payload)
  expect(extra.template_snapshot.document).toEqual(original.template_snapshot.document)
  expect(extra.status).toBe('queued')
  expect(keys[0]).toBe(keys[1])
  await button.click()
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await summary.click()
  await expect(button).toBeHidden()
  await summary.click()
  await expect(button).toBeVisible()
  await page.unrouteAll({ behavior: 'wait' })
})

test('paid retry approval shows a fresh total and waits for acceptance', async ({
  page,
  request,
}) => {
  const [tape] = await (await request.get('/api/tape-profiles')).json()
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/price`, {
        data: { price_minor: 2000, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  const original = await (
    await request.post('/api/jobs', {
      data: { tape_profile: tape.id, data: { text: 'Paid retry' } },
    })
  ).json()
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${original.id}`)).json()).status)
    .toBe('printed')
  const [batch] = await (await request.get('/api/batches')).json()
  const result = await request.post(`/api/batches/${batch.id}/retry-offers`, {
    data: {
      request_id: crypto.randomUUID(),
      copy_ids: [original.labels[0].id],
      mode: 'paid',
      include_printed: true,
    },
  })
  expect(result.status()).toBe(201)
  const [offer] = await result.json()
  expect(await (await request.get('/api/jobs')).json()).toHaveLength(1)
  const quote = await (await request.post(`/api/retries/${offer.id}/quote`)).json()
  await page.goto(`/#/retries/${offer.id}`)
  await expect(page.getByRole('spinbutton', { name: 'Maximum total', exact: true })).toHaveValue(
    quote.quotes[0].maximum,
  )
  await page.getByRole('spinbutton', { name: 'Maximum total', exact: true }).fill('0.15')
  await page.getByRole('button', { name: 'Accept paid retry', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: /^Retry queued\.$/ })).toBeVisible()
  const jobs = await (await request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(2)
  expect(
    jobs.find((job: { id: string }) => job.id !== original.id).template_snapshot.pricing.maximum
      .micros,
  ).toBe(150000)
})
