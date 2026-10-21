import { test, expect } from './fixtures'

for (const path of ['/new', '/runs']) {
  test(`${path} follows template names until edited and resumes on revert`, async ({
    page,
    request,
  }) => {
    const templates = []
    for (const name of ['Cable labels', 'Storage labels']) {
      const created = await request.post('/api/templates', {
        data: {
          name,
          document: {
            fields: [
              { name: 'text', label: 'Label text', default: 'Field value', sample: 'Field value' },
            ],
            elements: [],
          },
        },
      })
      expect(created.ok(), await created.text()).toBeTruthy()
      templates.push(await created.json())
    }
    await page.goto(`/#${path}?template=${templates[0].id}`)
    const name = page.getByRole('textbox', { name: 'Process name', exact: true })
    const template = page.getByRole('combobox', { name: 'Template', exact: true })
    await expect(name).toHaveValue('Cable labels')
    await template.selectOption(templates[1].id)
    await expect(name).toHaveValue('Storage labels')
    await name.fill('Network installation')
    await template.selectOption(templates[0].id)
    await expect(name).toHaveValue('Network installation')
    await page.getByRole('button', { name: 'Revert to original', exact: true }).click()
    await expect(name).toHaveValue('Cable labels')
    await template.selectOption(templates[1].id)
    await expect(name).toHaveValue('Storage labels')
    await name.fill('Final process name')
    await page.screenshot({
      path: `test-results/process-name-${path.slice(1)}-form.png`,
      fullPage: true,
    })
    if (path === '/new') {
      await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
      await expect(page.locator('.queue-label-name')).toHaveText('Final process name')
      await expect(page.getByText('Field value', { exact: true })).toBeHidden()
      await page.locator('.queue-label-details > summary').click()
      const details = page.locator('.label-details')
      await expect(details).toContainText('Field value')
      await expect(details).toContainText('Storage labels')
      await expect(details).toContainText('Desk printer')
      await expect(details).toContainText('Black on Yellow 24 mm')
      await expect(details).toContainText('Queued by')
      await page.screenshot({
        path: 'test-results/process-name-details-desktop.png',
        fullPage: true,
      })
      await page.setViewportSize({ width: 390, height: 844 })
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true)
      await page.screenshot({ path: 'test-results/process-name-details-mobile.png' })
    } else {
      await page.getByLabel('CSV content', { exact: true }).fill('text\nFirst cable\nSecond cable')
      await page.getByRole('button', { name: 'Read CSV', exact: true }).click()
      await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
      await expect(page).toHaveURL(/#\/runs\/[^/]+$/)
      const id = page.url().split('/runs/')[1].split('?')[0]
      const draft = await (await request.get(`/api/runs/${id}`)).json()
      expect(draft.process_name).toBe('Final process name')
      expect(draft.name).toBe('CSV labels')
      await page.reload()
      await page.getByRole('button', { name: 'Submit entire run', exact: true }).click()
      await expect(page.getByText('Run submitted.', { exact: false })).toBeVisible()
      const jobs = await (await request.get('/api/jobs')).json()
      expect(jobs.map((job: { process_name: string }) => job.process_name)).toEqual([
        'Final process name',
        'Final process name',
      ])
    }
  })
}

test('activity loads complete label information and previews only when opened', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const [printer] = await (await request.get('/api/printers')).json()
  const created = await request.post('/api/jobs', {
    data: {
      process_name: 'Equipment rollout',
      tape_profile: profile.id,
      data: { text: 'RACK-07' },
      copies: 2,
    },
  })
  expect(created.ok()).toBeTruthy()
  const job = await created.json()
  expect((await request.post(`/api/destinations/${printer.id}/print`)).status()).toBe(202)
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('printed')
  const reads: string[] = []
  page.on('request', (outgoing) => {
    if (/\/api\/batches\/[^/?]+/.test(outgoing.url())) reads.push(outgoing.url())
  })
  await page.goto('/#/activity')
  const batch = page.locator('.activity-batch').first()
  await expect(batch).toBeVisible()
  await expect(batch.locator('.grow > strong')).toHaveText('Equipment rollout')
  expect(reads).toEqual([])
  await batch.locator('.activity-labels > summary').click()
  const label = batch.locator('.activity-label')
  await expect(label.locator('strong').first()).toHaveText('Equipment rollout')
  await expect(label).toContainText('2 copies')
  await expect(label).toContainText('RACK-07')
  await expect(label).toContainText('Desk printer')
  await expect(label).toContainText('Simple text')
  await expect(label).toContainText('Black on Yellow 24 mm')
  await expect(label).toContainText('Queued by')
  expect(reads).toHaveLength(1)
  await expect(label.locator('img')).toHaveCount(0)
  await label.locator('.queue-preview > summary').click()
  await expect(label.getByRole('img', { name: 'Label preview: Equipment rollout' })).toBeVisible()
  await expect
    .poll(() => label.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await page.screenshot({ path: 'test-results/process-name-activity.png', fullPage: true })
})
