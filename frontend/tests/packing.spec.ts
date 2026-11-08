import { test, expect } from './fixtures'

test('packing preserves separated print positions and sorts by requester on desktop and mobile', async ({
  page,
  request,
}) => {
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  const [printer] = await (await request.get('/api/printers')).json()
  const jobs = []
  for (const text of ['Zoe', 'Alice']) {
    const response = await request.post('/api/jobs', {
      data: {
        tape_profile: cartridge.profile_id,
        destination_id: printer.id,
        copies: 3,
        data: { text },
      },
    })
    expect(response.ok()).toBeTruthy()
    jobs.push(await response.json())
  }
  const items = [jobs[0], jobs[0], jobs[1], jobs[0]].map((job, position) => ({
    copy_id: `copy-${position}`,
    job_id: job.id,
    position,
    outcome: 'printed',
    copy_number: position + 1,
    process_name: job.payload.text,
    width_mm: job.width_mm,
    length_mm: job.length_mm,
    attribution: {
      ...job.attribution,
      requested_by: { id: job.payload.text, name: job.payload.text },
    },
  }))
  await page.route('**/api/batches/packing-test', (route) =>
    route.fulfill({
      json: {
        id: 'packing-test',
        state: 'printed',
        printer_id: printer.id,
        cartridge_id: cartridge.id,
        items,
      },
    }),
  )
  await page.route('**/api/batches/packing-test/items/*/preview', async (route) => {
    const copy = route.request().url().split('/items/')[1]!.split('/')[0]
    const item = items.find((item) => item.copy_id === copy)!
    await route.fulfill({ response: await request.get(`/api/jobs/${item.job_id}/preview`) })
  })
  await page.goto('/#/batches/packing-test/packing')
  const labels = page.locator('.packing-label')
  await expect(labels).toHaveCount(3)
  await expect(labels.locator('h2')).toHaveText(['Zoe', 'Alice', 'Zoe'])
  await expect(labels.first()).toContainText('2 copies')
  await labels
    .first()
    .getByRole('button', { name: 'Enlarge label preview: Zoe', exact: true })
    .click()
  const preview = page.getByRole('dialog', { name: 'Label preview', exact: true })
  await expect(preview).toBeVisible()
  await preview.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(preview).not.toBeVisible()
  await page.getByRole('combobox', { name: 'Sort by', exact: true }).selectOption('requester')
  await expect(labels.locator('h2')).toHaveText(['Alice', 'Zoe', 'Zoe'])
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    )
  })
  await page.screenshot({ path: 'test-results/packing-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('combobox', { name: 'Sort by', exact: true }).selectOption('print')
  await expect(labels.locator('h2')).toHaveText(['Zoe', 'Alice', 'Zoe'])
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    )
  })
  await page.screenshot({ path: 'test-results/packing-mobile.png', fullPage: true })
})
