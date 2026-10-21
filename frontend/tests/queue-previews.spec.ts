import { test, expect } from './fixtures'

test('queue process names stay visible while details and previews remain collapsed', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const created = await request.post('/api/templates', {
    data: {
      name: 'Cable identification label',
      document: {
        elements: [
          { id: 'text', kind: 'text', x: 2, y: 4, width: 40, height: 12, content: 'Cable 42' },
        ],
      },
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const template = await created.json()
  const queued = await request.post('/api/jobs', {
    data: { template: template.id, tape_profile: profile.id, data: {} },
  })
  expect(queued.ok(), await queued.text()).toBeTruthy()
  const job = await queued.json()
  const other = await (
    await request.post('/api/jobs', {
      data: {
        process_name: 'Unopened label',
        tape_profile: profile.id,
        data: { text: 'Unopened label' },
      },
    })
  ).json()
  const previews: string[] = []
  let failOther = true
  await page.route('**/api/jobs/*/preview*', async (route) => {
    const path = new URL(route.request().url()).pathname
    previews.push(path)
    if (path.includes(other.id) && failOther) {
      failOther = false
      await route.fulfill({ status: 503, body: 'Unavailable' })
    } else await route.continue()
  })
  await page.goto('/#/queue')
  const row = page.locator('tbody tr').filter({ hasText: 'Cable identification label' })
  const otherRow = page.locator('tbody tr').filter({ hasText: 'Unopened label' })
  await expect(row.locator('.queue-label-name')).toHaveText('Cable identification label')
  await expect(row).not.toContainText(template.id)
  await expect(row.locator('.label-details')).toBeHidden()
  await row.locator('.queue-label-details > summary').click()
  await expect(row.locator('.label-details')).toContainText('Queued by')
  await expect(row.locator('.label-details')).toContainText('owner')
  await expect(page.locator('.queue-preview img')).toHaveCount(0)
  expect(previews).toEqual([])
  await page.screenshot({ path: 'test-results/queue-previews-collapsed.png', fullPage: true })

  await row.locator('.queue-preview > summary').focus()
  await page.keyboard.press('Enter')
  const image = row.getByRole('img', { name: 'Label preview: Cable identification label' })
  await expect(image).toBeVisible()
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  expect(previews).toEqual([`/api/jobs/${job.id}/preview`])
  await row.locator('.queue-preview > summary').click()
  await expect(image).toBeHidden()
  await row.locator('.queue-preview > summary').click()
  await expect(image).toBeVisible()
  expect(previews).toHaveLength(1)

  await request.post('/api/jobs', {
    data: {
      process_name: 'Arrived during polling',
      tape_profile: profile.id,
      data: { text: 'Arrived during polling' },
    },
  })
  await expect(
    page.locator('.queue-label-name').filter({ hasText: 'Arrived during polling' }),
  ).toBeVisible({
    timeout: 15000,
  })
  await expect(image).toBeVisible()
  expect(previews).toHaveLength(1)

  await otherRow.locator('.queue-preview > summary').click()
  await expect(otherRow.getByText('Preview unavailable.', { exact: false })).toBeVisible()
  await expect(otherRow.getByRole('button', { name: 'Remove', exact: true })).toBeEnabled()
  await otherRow.getByRole('button', { name: 'Retry preview', exact: true }).click()
  await expect
    .poll(() => otherRow.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  expect(previews.filter((path) => path.includes(other.id))).toHaveLength(2)
  await page.screenshot({ path: 'test-results/queue-previews-expanded.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true)
  await page.screenshot({ path: 'test-results/queue-previews-mobile.png' })
})

test('opening a CSV run does not fetch its previews', async ({ page, request }) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const prepared = await request.post('/api/runs/prepare', {
    data: {
      request_key: 'lazy-csv-labels',
      name: 'Lazy CSV labels',
      template: 'text',
      expected_revision: 2,
      tape_profile: profile.id,
      csv_text: 'Text\nFirst CSV label\nSecond CSV label\n',
      mapping: { text: 'Text' },
      rows: [
        { source_row: 2, copies: 1 },
        { source_row: 3, copies: 1 },
      ],
    },
  })
  expect(prepared.ok(), await prepared.text()).toBeTruthy()
  const run = (await prepared.json()).run
  expect((await request.post(`/api/runs/${run.id}/submit`)).ok()).toBeTruthy()
  const previews: string[] = []
  page.on('request', (outgoing) => {
    if (/\/api\/jobs\/[^/]+\/preview/.test(outgoing.url())) previews.push(outgoing.url())
  })
  await page.goto('/#/queue')
  await page.getByRole('button', { name: 'Toggle Lazy CSV labels', exact: true }).click()
  await expect(page.locator('.queue-label-name')).toHaveText(['Simple text', 'Simple text'])
  await expect(page.locator('.queue-preview img')).toHaveCount(0)
  expect(previews).toEqual([])
  const row = page.locator('tbody tr').filter({ hasText: 'First CSV label' })
  await row.locator('.queue-preview > summary').click()
  await expect(row.getByRole('img', { name: 'Label preview: Simple text' })).toBeVisible()
  await expect.poll(() => previews.length).toBe(1)
})
