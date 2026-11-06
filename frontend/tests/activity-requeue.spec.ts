import { test, expect } from './fixtures'

test('Activity queues one saved copy and safely retries an uncertain response', async ({
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
  const button = details.getByRole('button', { name: 'Requeue Cable identification', exact: true })
  await expect(button).toBeVisible()
  await expect(details).toContainText('3 copies')
  await details.locator('.queue-preview > summary').click()
  const preview = details.getByRole('img', { name: 'Label preview: Cable identification' })
  await expect(preview).toBeVisible()
  await expect
    .poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await page.screenshot({
    path: 'test-results/activity-requeue-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 402, height: 874 })
  await button.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(402)
  await page.screenshot({
    path: 'test-results/activity-requeue-mobile.png',
    animations: 'disabled',
  })

  const keys: string[] = []
  await page.route('**/api/batches/*/items/*/requeue', async (route) => {
    keys.push(route.request().headers()['idempotency-key']!)
    const response = await route.fetch()
    // The server saved the new copy, but its response did not reach the UI.
    if (keys.length === 1)
      await route.fulfill({ status: 409, json: { detail: 'Response interrupted. Try again.' } })
    else await route.fulfill({ response })
  })
  await button.click()
  await expect(page.getByRole('alert')).toContainText('Response interrupted. Try again.')
  await button.click()
  await expect(
    page.getByRole('status').filter({ hasText: 'One copy added to the print queue.' }),
  ).toBeVisible()
  let jobs = await (await request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(2)
  const extra = jobs.find((job: { id: string }) => job.id !== original.id)
  expect(extra.copies).toBe(1)
  expect(extra.payload).toEqual(original.payload)
  expect(extra.template_snapshot.document).toEqual(original.template_snapshot.document)
  expect(extra.status).toBe('queued')
  expect(keys[0]).toBe(keys[1])
  await button.click()
  await expect(button).toBeEnabled()
  jobs = await (await request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(3)
  expect(keys[2]).not.toBe(keys[1])
  await summary.click()
  await expect(button).toBeHidden()
  await summary.click()
  await expect(button).toBeVisible()
  await page.unrouteAll({ behavior: 'wait' })
})
